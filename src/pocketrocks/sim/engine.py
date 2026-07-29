"""Local rules engine: a line-for-line mirror of ``apps/server/src/rules/*``.

The engine is a pure state machine — no async, no timers, no I/O. It emits the
same wire events the live server emits, so contexts built over them (Task 7 /
``context.py``) are identical to live ones by construction. Golden traces
exported from the TS engine pin its behavior (``tests/sim/test_conformance.py``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from pocketrocks.internal.bot_wire_v2 import (
    AuctionResolvedEvent,
    CommonEvent,
    GameSetupEvent,
    InfoRevealedEvent,
    TurnOpenedEvent,
)

from .constants import (
    ACTION_DECK,
    ACTION_WIRE_IDS,
    ALL_OBJECTIVE_WIRE_IDS,
    INFO_CARDS_PER_PLAYER,
    INVEST_PAYOUT,
    ITEM_DECK_SUITS,
    LOAN_PRINCIPAL,
    OBJECTIVE_PAYOUTS,
    OBJECTIVES_PER_GAME,
    STARTING_CASH,
    VALUE_CHARTS,
    objective_pattern_met,
)
from .rng import shuffled
from .state import PlayerSim, RevealRecord, ScoreRow, TurnRecord


@dataclass(frozen=True)
class TurnOutcome:
    winner_seat: int
    paid: int
    effective_bids: tuple[int, ...]
    bundle_suits: tuple[int, ...]
    claimed_objective_wire_ids: tuple[int, ...]
    reveal_needed: str | None  # "choice" | "auto" | None


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
        self.history: list[TurnRecord] = []
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

    # --- turn mechanics (mirrors rules/turns.ts) ---

    @property
    def game_over(self) -> bool:
        no_items = not self.upcoming and not self.pile
        return no_items or not self.action_deck

    def flip_action(self) -> str | None:
        if self.game_over:
            self.current_action = None
            return None
        action = self.action_deck.pop(0)
        self.current_action = action
        first = self.upcoming[0] if len(self.upcoming) > 0 else 0
        second = self.upcoming[1] if len(self.upcoming) > 1 else 0
        self.events.append(
            TurnOpenedEvent(
                kind="turnOpened",
                action_id=ACTION_WIRE_IDS[action],
                resource_ids=(first, second),
            )
        )
        return action

    def legal_max_bid(self, seat: int) -> int:
        cash = self.players[seat].cash
        if self.current_action in LOAN_PRINCIPAL:
            return cash + LOAN_PRINCIPAL[self.current_action]
        return cash

    def resolve(self, raw_bids: Sequence[int]) -> TurnOutcome:
        action = self.current_action
        if action is None:
            raise RuntimeError("resolve() called with no flipped action")
        if len(raw_bids) != len(self.players):
            raise ValueError("one bid per seat required")
        effective = tuple(
            max(0, min(int(raw), self.legal_max_bid(seat)))
            for seat, raw in enumerate(raw_bids)
        )
        upcoming_before = tuple(self.upcoming)

        # Winner: highest bid; ties scan clockwise starting AFTER the leader,
        # leader last (rules/turns.ts resolveAuction).
        highest = max(effective)
        seat_count = len(self.players)
        winner_seat = next(
            (self.tiebreak_seat + offset) % seat_count
            for offset in range(1, seat_count + 1)
            if effective[(self.tiebreak_seat + offset) % seat_count] == highest
        )
        winner = self.players[winner_seat]
        winner.cash -= highest
        self.tiebreak_seat = winner_seat

        bundle: list[int] = []
        claimed: list[int] = []
        if action in ("Auction1", "Auction2"):
            grants = 1 if action == "Auction1" else 2
            for _ in range(grants):
                if self.upcoming:
                    suit = self.upcoming.pop(0)
                    bundle.append(suit)
                    winner.won_suits.append(suit)
            counts = [0] * 5
            for suit in winner.won_suits:
                counts[suit - 1] += 1
            for index, (oid, claimed_by) in enumerate(self.active_objectives):
                if claimed_by is None and objective_pattern_met(oid, counts):
                    self.active_objectives[index] = (oid, winner_seat)
                    winner.objective_wire_ids.append(oid)
                    claimed.append(oid)
        elif action in LOAN_PRINCIPAL:
            principal = LOAN_PRINCIPAL[action]
            winner.cash += principal
            winner.loans.append(principal)
        else:  # Invest5 / Invest10
            winner.investments.append((highest, INVEST_PAYOUT[action]))

        self.events.append(
            AuctionResolvedEvent(kind="auctionResolved", bids_by_seat=effective)
        )
        self._refill_upcoming()

        hand_size = len(winner.hand_suits)
        reveal_needed = "choice" if hand_size > 1 else ("auto" if hand_size == 1 else None)
        self.history.append(
            TurnRecord(
                turn_index=self.turn_index,
                action=action,
                upcoming_before=upcoming_before,
                raw_bids=tuple(int(raw) for raw in raw_bids),
                effective_bids=effective,
                winner_seat=winner_seat,
                paid=highest,
                bundle_suits=tuple(bundle),
                claimed_objective_wire_ids=tuple(claimed),
                reveal=None,
            )
        )
        self.turn_index += 1
        self.current_action = None
        return TurnOutcome(
            winner_seat=winner_seat,
            paid=highest,
            effective_bids=effective,
            bundle_suits=tuple(bundle),
            claimed_objective_wire_ids=tuple(claimed),
            reveal_needed=reveal_needed,
        )

    def apply_reveal(self, seat: int, hand_index: int, *, auto: bool) -> RevealRecord:
        player = self.players[seat]
        if not player.hand_suits:
            raise RuntimeError("apply_reveal() on an empty hand")
        index = hand_index if 0 <= hand_index < len(player.hand_suits) else 0
        suit = player.hand_suits.pop(index)
        player.revealed_suits.append(suit)
        self.events.append(InfoRevealedEvent(kind="infoRevealed", suit_id=suit))
        record = RevealRecord(seat=seat, suit=suit, auto=auto)
        self.history[-1] = replace(self.history[-1], reveal=record)
        return record

    # --- scoring (mirrors rules/scoring.ts, with the agreed index clamp) ---

    def score(self) -> list[ScoreRow]:
        rows: list[ScoreRow] = []
        for player in self.players:
            items = sum(
                self.value_chart[min(self.initial_info_counts[suit - 1], 5)]
                for suit in player.won_suits
            )
            investments = sum(lock + payout for lock, payout in player.investments)
            objectives = sum(OBJECTIVE_PAYOUTS[oid] for oid in player.objective_wire_ids)
            loans = sum(player.loans)
            rows.append(
                ScoreRow(
                    seat=player.seat,
                    name=player.name,
                    cash=player.cash,
                    items_value=items,
                    objectives_value=objectives,
                    investments_value=investments,
                    loans_value=loans,
                    total=player.cash + items + investments - loans + objectives,
                )
            )
        return rows

    def ranking(self) -> list[int]:
        return [row.seat for row in sorted(self.score(), key=lambda r: -r.total)]
