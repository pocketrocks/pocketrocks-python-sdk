"""LocalGame: drive real ``PocketRocksBot`` instances through one offline game."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from pocketrocks.bot import PocketRocksBot
from pocketrocks.exceptions import InvalidBotDecision
from pocketrocks.types import BotDecision, DecisionContext, decisionKind

from .context import build_sim_context
from .engine import SimEngine
from .state import ScoreRow, TurnRecord


@dataclass(frozen=True)
class DecisionRecord:
    turn_index: int
    seat: int
    kind: str
    context: DecisionContext
    decision: BotDecision | None
    fallback: str | None  # None | "exception" | "illegal"


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
        engine = self._engine
        while engine.flip_action() is not None:
            raw_bids: list[int] = []
            for seat, bot in enumerate(self._bots):
                raw_bids.append(await self._ask_bid(seat, bot))
            outcome = engine.resolve(raw_bids)
            if outcome.reveal_needed == "auto":
                engine.apply_reveal(outcome.winner_seat, 0, auto=True)
            elif outcome.reveal_needed == "choice":
                index = await self._ask_reveal(outcome.winner_seat, self._bots[outcome.winner_seat])
                engine.apply_reveal(outcome.winner_seat, index, auto=False)
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

    async def _ask(
        self, seat: int, bot: PocketRocksBot, kind: decisionKind
    ) -> tuple[BotDecision | None, str | None, DecisionContext]:
        context = build_sim_context(self._engine, seat, kind, budget_ms=self._budget_ms)
        decision: BotDecision | None = None
        fallback: str | None = None
        try:
            decision = await bot.choose_decision(context)
            context.validate(decision)
        except InvalidBotDecision:
            fallback = "illegal"
        except Exception:  # noqa: BLE001 — a bot bug becomes the timeout fallback
            fallback = "exception"
        if self._record:
            self._decisions.append(
                DecisionRecord(
                    turn_index=self._engine.turn_index,
                    seat=seat,
                    kind=kind,
                    context=context,
                    decision=decision,
                    fallback=fallback,
                )
            )
        return decision, fallback, context

    async def _ask_bid(self, seat: int, bot: PocketRocksBot) -> int:
        decision, fallback, _context = await self._ask(seat, bot, "submitBid")
        if fallback is not None or decision is None or decision.action_kind != "submitBid":
            return 0  # pass, crash, and illegal all bid 0 — the server's fallback
        return decision.value or 0

    async def _ask_reveal(self, seat: int, bot: PocketRocksBot) -> int:
        decision, fallback, _context = await self._ask(seat, bot, "selectInfoToReveal")
        if (
            fallback is not None
            or decision is None
            or decision.action_kind != "selectInfoToReveal"
            or decision.value is None
        ):
            return 0  # auto-reveal-first, the server's timeout fallback
        return decision.value
