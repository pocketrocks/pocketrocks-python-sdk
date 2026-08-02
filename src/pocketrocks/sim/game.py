"""LocalGame: drive real ``PocketRocksBot`` instances through one offline game."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from pocketrocks._reporting import report_rejection
from pocketrocks._update_check import kickoff_update_check
from pocketrocks.bot import PocketRocksBot
from pocketrocks.exceptions import InvalidBotDecision
from pocketrocks.types import (
    BotDecision,
    DecisionContext,
    classify,
    decisionFate,
    decisionKind,
)

from .context import build_sim_request_and_context
from .engine import SimEngine
from .state import ScoreRow, TurnRecord

logger = logging.getLogger("pocketrocks.sim")


@dataclass(frozen=True)
class _PendingRejection:
    """A rejection whose reporting is deferred until the engine has the decision.

    The sim reports illegal decisions *after* the value reaches the engine, so a
    slow or misbehaving telemetry hook can never delay the game or change what the
    engine sees. ``_ask`` builds this and commits the decision record; the game
    loop fires it via ``_report`` once ``engine.resolve`` / ``apply_reveal`` has
    consumed the value.
    """

    bot: PocketRocksBot
    context: DecisionContext
    decision: BotDecision
    error: InvalidBotDecision
    applied: decisionFate
    outgoing: BotDecision


@dataclass(frozen=True)
class DecisionRecord:
    turn_index: int
    seat: int
    kind: str
    context: DecisionContext
    decision: BotDecision | None
    fallback: str | None  # None | "exception" | "illegal"
    corrected: BotDecision | None = None  # the substitute actually dispatched, if any


@dataclass(frozen=True)
class GameResult:
    seats: tuple[str, ...]
    scores: tuple[ScoreRow, ...]
    ranking: tuple[int, ...]
    winner_seat: int
    history: tuple[TurnRecord, ...]
    decisions: tuple[DecisionRecord, ...]


def bot_label(bot: PocketRocksBot) -> str:
    return getattr(bot, "name", None) or type(bot).__name__


class LocalGame:
    """One seeded offline game between 3-5 bots.

    Bots that raise or return an illegal decision get the live server's
    timeout fallback: bid 0 on ``submitBid``, reveal the first card on
    ``selectInfoToReveal``. The game itself never crashes on a bot bug.
    """

    def __init__(
        self,
        bots: Sequence[PocketRocksBot],
        *,
        seed: str | int,
        value_chart: str = "A",
        objectives_enabled: bool = True,
        decision_budget_ms: int = 60_000,
        record_decisions: bool = False,
    ) -> None:
        self._bots = list(bots)
        self._engine = SimEngine(
            len(self._bots),
            str(seed),
            value_chart=value_chart,
            objectives_enabled=objectives_enabled,
            player_names=[bot_label(bot) for bot in self._bots],
        )
        self._budget_ms = decision_budget_ms
        self._record = record_decisions
        self._decisions: list[DecisionRecord] = []

    def play(self) -> GameResult:
        return asyncio.run(self.play_async())

    async def play_async(self) -> GameResult:
        kickoff_update_check()
        engine = self._engine
        while engine.flip_action() is not None:
            turn = engine.turn_index
            raw_bids: list[int] = []
            pending_bids: list[_PendingRejection] = []
            for seat, bot in enumerate(self._bots):
                value, pending = await self._ask_bid(seat, bot, turn)
                raw_bids.append(value)
                if pending is not None:
                    pending_bids.append(pending)
            outcome = engine.resolve(raw_bids)
            # The engine has now consumed every bid, so reporting the rejected
            # ones cannot change the auction or gate it on a telemetry hook.
            for pending in pending_bids:
                await self._report(pending)
            if outcome.reveal_needed == "auto":
                engine.apply_reveal(outcome.winner_seat, 0, auto=True)
            elif outcome.reveal_needed == "choice":
                index, reveal_pending = await self._ask_reveal(
                    outcome.winner_seat, self._bots[outcome.winner_seat], turn
                )
                engine.apply_reveal(outcome.winner_seat, index, auto=False)
                if reveal_pending is not None:
                    await self._report(reveal_pending)
        scores = tuple(engine.score())
        ranking = tuple(engine.ranking())
        return GameResult(
            seats=tuple(player.name for player in engine.players),
            scores=scores,
            ranking=ranking,
            winner_seat=ranking[0],
            history=tuple(engine.history),
            decisions=tuple(self._decisions),
        )

    async def _report(self, pending: _PendingRejection) -> None:
        await report_rejection(
            pending.bot,
            logger,
            context=pending.context,
            decision=pending.decision,
            error=pending.error,
            applied=pending.applied,
            debug=pending.bot.config.debug,
            outgoing=pending.outgoing,
        )

    async def _ask(
        self, seat: int, bot: PocketRocksBot, kind: decisionKind, turn_index: int
    ) -> tuple[BotDecision | None, str | None, _PendingRejection | None]:
        request, context = build_sim_request_and_context(
            self._engine, seat, kind, budget_ms=self._budget_ms, turn_index=turn_index
        )
        decision: BotDecision | None = None
        dispatched: BotDecision | None = None
        corrected: BotDecision | None = None
        fallback: str | None = None
        pending: _PendingRejection | None = None
        try:
            # Mirror the live runtime's dispatch: bots overriding the
            # choose_raw_decision escape hatch get the wire frame too.
            if bot.uses_raw_decision():
                decision = await bot.choose_raw_decision(request, context)
            else:
                decision = await bot.choose_decision(context)
            applied, rejection, outgoing = classify(context, decision)
            # "forwarded" is not a fallback: the raw value goes to the engine,
            # which clamps it with the same formula the server uses. Only
            # "discarded" substitutes, matching the server recording 0 for a
            # player whose decision never arrived.
            if applied == "discarded":
                fallback = "illegal"
            else:
                # For "corrected", `outgoing` is the wire-representable substitute;
                # for "ok" and "forwarded" it is `decision` itself. Using it here is
                # what makes the sim feed its engine exactly what the live runtime
                # puts on the wire. The bot's original decision is kept separately
                # so the record reflects what the bot actually returned.
                dispatched = outgoing
                if applied == "corrected":
                    corrected = outgoing
            if rejection is not None:
                # Defer reporting: report_rejection awaits user telemetry hooks,
                # and the engine must receive the decision (via the caller's
                # resolve / apply_reveal) before any hook runs, so a slow or
                # misbehaving hook can never gate game progress. The record below
                # is committed now, independent of the hook, so training data is
                # never lost to a stalled callback.
                pending = _PendingRejection(
                    bot=bot,
                    context=context,
                    decision=decision,
                    error=rejection,
                    applied=applied,
                    outgoing=outgoing,
                )
        except Exception:  # noqa: BLE001 — a bot bug becomes the timeout fallback
            fallback = "exception"
        if self._record:
            self._decisions.append(
                DecisionRecord(
                    turn_index=turn_index,
                    seat=seat,
                    kind=kind,
                    context=context,
                    decision=decision,
                    fallback=fallback,
                    corrected=corrected,
                )
            )
        return dispatched, fallback, pending

    async def _ask_bid(
        self, seat: int, bot: PocketRocksBot, turn_index: int
    ) -> tuple[int, _PendingRejection | None]:
        decision, fallback, pending = await self._ask(seat, bot, "submitBid", turn_index)
        if fallback is not None or decision is None or decision.action_kind != "submitBid":
            return 0, pending  # pass, crash, and illegal all bid 0 — the server's fallback
        return decision.value or 0, pending

    async def _ask_reveal(
        self, seat: int, bot: PocketRocksBot, turn_index: int
    ) -> tuple[int, _PendingRejection | None]:
        decision, fallback, pending = await self._ask(
            seat, bot, "selectInfoToReveal", turn_index
        )
        if (
            fallback is not None
            or decision is None
            or decision.action_kind != "selectInfoToReveal"
            or decision.value is None
        ):
            return 0, pending  # auto-reveal-first, the server's timeout fallback
        return decision.value, pending
