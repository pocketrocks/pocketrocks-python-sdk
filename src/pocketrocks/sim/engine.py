"""Local rules engine: a line-for-line mirror of ``apps/server/src/rules/*``.

The engine is a pure state machine — no async, no timers, no I/O. It emits the
same wire events the live server emits, so contexts built over them (Task 7 /
``context.py``) are identical to live ones by construction. Golden traces
exported from the TS engine pin its behavior (``tests/sim/test_conformance.py``).
"""

from __future__ import annotations

from collections.abc import Sequence

from pocketrocks.internal.bot_wire_v2 import CommonEvent, GameSetupEvent

from .constants import (
    ACTION_DECK,
    ALL_OBJECTIVE_WIRE_IDS,
    INFO_CARDS_PER_PLAYER,
    ITEM_DECK_SUITS,
    OBJECTIVES_PER_GAME,
    STARTING_CASH,
    VALUE_CHARTS,
)
from .rng import shuffled
from .state import PlayerSim


class SimEngine:
    def __init__(
        self,
        player_count: int,
        seed: str,
        *,
        value_chart: str = "A",
        objectives_enabled: bool = True,
        player_names: Sequence[str] | None = None,
    ) -> None:
        if not 3 <= player_count <= 5:
            raise ValueError("PocketRocks supports 3-5 players")
        if value_chart not in VALUE_CHARTS:
            raise ValueError(f"unknown value chart {value_chart!r} (expected A-E)")
        names = list(player_names) if player_names is not None else [
            f"Bot {seat}" for seat in range(player_count)
        ]
        if len(names) != player_count:
            raise ValueError("player_names length must match player_count")

        self.seed = seed
        self.value_chart_key = value_chart
        self.value_chart: tuple[int, ...] = VALUE_CHARTS[value_chart]

        item_deck = shuffled(ITEM_DECK_SUITS, seed)
        self.debug_item_deck_order: tuple[int, ...] = tuple(item_deck)
        per_player = INFO_CARDS_PER_PLAYER[player_count]
        dealt = item_deck[: player_count * per_player]
        starting_cash = STARTING_CASH[player_count]
        self.players: list[PlayerSim] = [
            PlayerSim(
                seat=seat,
                name=names[seat],
                cash=starting_cash,
                hand_suits=dealt[seat * per_player : (seat + 1) * per_player],
            )
            for seat in range(player_count)
        ]
        counts = [0] * 5
        for suit in dealt:
            counts[suit - 1] += 1
        self.initial_info_counts: tuple[int, ...] = tuple(counts)

        self.pile: list[int] = item_deck[player_count * per_player :]
        self.upcoming: list[int] = []
        self._refill_upcoming()

        self.action_deck: list[str] = shuffled(ACTION_DECK, seed)
        self.debug_action_deck_order: tuple[str, ...] = tuple(self.action_deck)

        self.tiebreak_seat: int = shuffled(list(range(player_count)), seed)[0]
        selected = (
            shuffled(list(ALL_OBJECTIVE_WIRE_IDS), seed)[:OBJECTIVES_PER_GAME]
            if objectives_enabled
            else []
        )
        self.active_objectives: list[tuple[int, int | None]] = [(oid, None) for oid in selected]

        self.current_action: str | None = None
        self.turn_index = 0
        self.events: list[CommonEvent] = [
            GameSetupEvent(
                kind="gameSetup",
                player_count=player_count,
                starting_cash=starting_cash,
                value_chart=self.value_chart,  # type: ignore[arg-type]
                initial_tiebreak_seat=self.tiebreak_seat,
                objective_ids=tuple(oid for oid, _ in self.active_objectives),
            )
        ]

    def _refill_upcoming(self) -> None:
        while len(self.upcoming) < 2 and self.pile:
            self.upcoming.append(self.pile.pop(0))
