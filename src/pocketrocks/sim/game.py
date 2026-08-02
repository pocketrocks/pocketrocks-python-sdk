"""LocalGame: drive real ``PocketRocksBot`` instances through one offline game."""

from __future__ import annotations

import asyncio
import contextlib
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

# Bounded wait, at game end, for reports still in flight. Reporting is best-effort
# telemetry that the game never blocks on while it plays; this covers the tail so a
# well-behaved hook still runs to completion before ``play_async`` returns. A hook
# that never returns costs this much once, at the end, and is then cancelled —
# awaiting it instead would put the hook back on the game's liveness path, and
# simply dropping the task would leak a "Task was destroyed but it is pending"
# warning from the loop with no explanation of why. Mirrors the update check's
# ``_JOIN_TIMEOUT_S`` shutdown wait.
_REPORT_DRAIN_TIMEOUT_S = 1.5


@dataclass(frozen=True)
class _PendingRejection:
    """A rejection handed to the background reporter once the engine has the decision.

    The sim reports illegal decisions *after* the value reaches the engine and
    never on the game's own critical path, so a slow, blocking, or misbehaving
    telemetry hook can neither delay the game nor change what the engine sees.
    ``_ask`` builds this and commits the decision record; the game loop queues it
    for ``_run_reporter`` once ``engine.resolve`` / ``apply_reveal`` has consumed
    the value.
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
        # Created on the first rejection, inside the running loop: a LocalGame is
        # constructed synchronously and may be replayed, so the queue and its
        # worker cannot be bound to a loop here.
        self._reports: asyncio.Queue[_PendingRejection | None] | None = None
        self._reporter: asyncio.Task[None] | None = None

    def play(self) -> GameResult:
        return asyncio.run(self.play_async())

    async def play_async(self) -> GameResult:
        kickoff_update_check()
        engine = self._engine
        try:
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
                # The engine has now consumed every bid, so handing the rejected
                # ones to the reporter cannot change the auction.
                await self._hand_off(pending_bids)
                if outcome.reveal_needed == "auto":
                    engine.apply_reveal(outcome.winner_seat, 0, auto=True)
                elif outcome.reveal_needed == "choice":
                    index, reveal_pending = await self._ask_reveal(
                        outcome.winner_seat, self._bots[outcome.winner_seat], turn
                    )
                    engine.apply_reveal(outcome.winner_seat, index, auto=False)
                    if reveal_pending is not None:
                        await self._hand_off([reveal_pending])
        finally:
            # Also on the way out of a failed game: never leave the worker behind.
            await self._drain_reports()
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

    async def _hand_off(self, pending: Sequence[_PendingRejection]) -> None:
        """Queue rejections for the reporter and give it exactly one scheduling slot.

        The queue hand-off is what takes user telemetry hooks off the game's
        liveness path: nothing here waits on a hook, so a hook that blocks forever
        cannot stop the next seat, the next turn, the reveal, or the result. The
        single ``sleep(0)`` lets a well-behaved reporter keep pace with the game
        (rather than delivering the whole game's reports in a burst at the end)
        and resumes on the next loop iteration no matter what the hook does.
        """
        if not pending:
            return
        queue = self._ensure_reporter()
        for item in pending:
            queue.put_nowait(item)
        await asyncio.sleep(0)

    def _ensure_reporter(self) -> asyncio.Queue[_PendingRejection | None]:
        if self._reports is None:
            self._reports = asyncio.Queue()
            self._reporter = asyncio.create_task(
                self._run_reporter(self._reports),
                name="pocketrocks-sim-rejection-reporter",
            )
        return self._reports

    async def _run_reporter(self, queue: asyncio.Queue[_PendingRejection | None]) -> None:
        """Report queued rejections one at a time, in the order the game made them.

        One worker rather than a task per rejection: a bot's hooks are never
        re-entered concurrently and still see rejections in game order, exactly as
        they did when the loop awaited them inline. The cost is head-of-line
        blocking — a hook that hangs also holds up the reports behind it — which is
        the right trade for best-effort telemetry whose ordering is observable.
        """
        while True:
            pending = await queue.get()
            if pending is None:  # sentinel: everything queued before it is reported
                return
            try:
                await self._report(pending)
            except Exception as error:  # noqa: BLE001 — telemetry never kills the reporter
                logger.warning("reporting a rejected decision failed: %s", error)

    async def _drain_reports(self) -> None:
        """Give in-flight reports a bounded chance to finish, then cancel the worker."""
        queue, reporter = self._reports, self._reporter
        self._reports, self._reporter = None, None
        if queue is None or reporter is None:
            return
        queue.put_nowait(None)
        try:
            await asyncio.wait({reporter}, timeout=_REPORT_DRAIN_TIMEOUT_S)
        finally:
            if not reporter.done():
                logger.warning(
                    "dropping %d unreported decision rejection(s): a reporting hook did "
                    "not return within %s seconds",
                    queue.qsize(),
                    _REPORT_DRAIN_TIMEOUT_S,
                )
                reporter.cancel()
            # Bounded by the hook contract, not by us: a hook must let cancellation
            # through. One that swallows CancelledError would hang any asyncio
            # teardown of the task anyway (asyncio.run's _cancel_all_tasks included),
            # so bounding this await is impossible and is not attempted.
            with contextlib.suppress(asyncio.CancelledError):
                await reporter

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
                # resolve / apply_reveal) before any hook runs. The caller hands
                # this to the background reporter rather than awaiting it, so a
                # slow or blocking hook can never gate game progress. The record
                # below is committed now, independent of the hook, so training
                # data is never lost to a stalled callback.
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
        decision, fallback, pending = await self._ask(seat, bot, "selectInfoToReveal", turn_index)
        if (
            fallback is not None
            or decision is None
            or decision.action_kind != "selectInfoToReveal"
            or decision.value is None
        ):
            return 0, pending  # auto-reveal-first, the server's timeout fallback
        return decision.value, pending
