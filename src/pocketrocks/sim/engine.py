"""Scalar compatibility facade over the canonical vectorized rules engine."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np

from pocketrocks.internal.bot_wire_v2 import (
    AuctionResolvedEvent,
    CommonEvent,
    GameSetupEvent,
    InfoRevealedEvent,
    TurnOpenedEvent,
)

from .batch_engine import BatchSimEngine
from .constants import (
    ACTION_WIRE_IDS,
    INVEST_PAYOUT,
    LOAN_PRINCIPAL,
    OBJECTIVE_PAYOUTS,
    STARTING_CASH,
)
from .ruleset import PaymentRule, Ruleset, coerce_ruleset
from .state import PlayerSim, RevealRecord, ScoreRow, TurnRecord

_ACTION_BY_WIRE_ID = {wire_id: action for action, wire_id in ACTION_WIRE_IDS.items()}


@dataclass(frozen=True)
class TurnOutcome:
    winner_seat: int
    paid: int
    effective_bids: tuple[int, ...]
    bundle_suits: tuple[int, ...]
    claimed_objective_wire_ids: tuple[int, ...]
    reveal_needed: str | None


class SimEngine:
    """The established scalar API, backed by a size-one ``BatchSimEngine``."""

    def __init__(
        self,
        player_count: int,
        seed: str,
        *,
        value_chart: str | Sequence[int] = "A",
        payment_rule: PaymentRule = "first-price",
        objectives_enabled: bool = True,
        player_names: Sequence[str] | None = None,
        ruleset: Ruleset | None = None,
    ) -> None:
        names = (
            list(player_names)
            if player_names is not None
            else [f"Bot {seat}" for seat in range(player_count)]
        )
        if len(names) != player_count:
            raise ValueError("player_names length must match player_count")
        self.ruleset = coerce_ruleset(
            player_count=player_count,
            ruleset=ruleset,
            value_chart=value_chart,
            payment_rule=payment_rule,
            objectives_enabled=objectives_enabled,
        )
        self._batch = BatchSimEngine.start(seeds=(seed,), rulesets=(self.ruleset,))
        self.seed = seed
        self.value_chart = tuple(int(value) for value in self._batch.value_charts[0])
        self.debug_item_deck_order = tuple(int(card) for card in self._batch.item_decks[0])
        self.debug_action_deck_order = tuple(
            _ACTION_BY_WIRE_ID[int(action)] for action in self._batch.action_decks[0]
        )
        self.initial_info_counts = tuple(int(count) for count in self._batch.initial_info_counts[0])
        self.players = [
            PlayerSim(
                seat=seat,
                name=names[seat],
                cash=int(self._batch.cash[0, seat]),
                hand_suits=[int(card) for card in self._batch.hand_cards[0, seat] if card > 0],
            )
            for seat in range(player_count)
        ]
        self.upcoming = [int(card) for card in self._batch.upcoming[0] if card > 0]
        self.pile = [
            int(card)
            for card in self._batch.resource_decks[
                0,
                int(self._batch.resource_positions[0]) :,
            ]
        ]
        self.action_deck = list(self.debug_action_deck_order)
        self.tiebreak_seat = int(self._batch.tiebreak_seats[0])
        self.active_objectives: list[tuple[int, int | None]] = [
            (int(objective_id), None)
            for objective_id in self._batch.objective_ids[0]
            if objective_id > 0
        ]
        self.current_action: str | None = None
        self.turn_index = 0
        self.history: list[TurnRecord] = []
        self.events: list[CommonEvent] = [
            GameSetupEvent(
                kind="gameSetup",
                player_count=player_count,
                starting_cash=STARTING_CASH[player_count],
                value_chart=self.value_chart,  # type: ignore[arg-type]
                initial_tiebreak_seat=self.tiebreak_seat,
                objective_ids=tuple(objective_id for objective_id, _ in self.active_objectives),
            )
        ]

    @property
    def game_over(self) -> bool:
        return (not self.upcoming and not self.pile) or not self.action_deck

    def _sync_to_batch(self) -> None:
        batch = self._batch
        batch.cash[0] = [player.cash for player in self.players]
        batch.hand_cards[0].fill(0)
        for seat, player in enumerate(self.players):
            batch.hand_cards[0, seat, : len(player.hand_suits)] = player.hand_suits
            for suit_id in range(1, 6):
                batch.won_counts[0, seat, suit_id - 1] = player.won_suits.count(suit_id)
                batch.revealed_counts[0, seat, suit_id - 1] = player.revealed_suits.count(suit_id)
            batch.loan_principal[0, seat] = sum(player.loans)
            batch.investment_values[0, seat] = sum(
                locked + payout for locked, payout in player.investments
            )
        batch.owned_objectives[0].fill(False)
        for seat, player in enumerate(self.players):
            for objective_id in player.objective_wire_ids:
                batch.owned_objectives[0, seat, objective_id - 1] = True
        batch.initial_info_counts[0] = self.initial_info_counts
        batch.tiebreak_seats[0] = self.tiebreak_seat
        batch.objective_ids[0].fill(0)
        batch.objective_claimants[0].fill(-1)
        for index, (objective_id, claimant) in enumerate(self.active_objectives):
            batch.objective_ids[0, index] = objective_id
            batch.objective_claimants[0, index] = -1 if claimant is None else claimant

        batch.upcoming[0].fill(0)
        batch.upcoming[0, : len(self.upcoming)] = self.upcoming
        batch.resource_decks[0].fill(0)
        batch.resource_decks[0, : len(self.pile)] = self.pile
        batch.resource_positions[0] = 0
        batch.resource_limits[0] = len(self.pile)

        batch.action_decks[0].fill(0)
        encoded_actions = [ACTION_WIRE_IDS[action] for action in self.action_deck]
        batch.action_decks[0, : len(encoded_actions)] = encoded_actions
        batch.action_positions[0] = 0
        batch.action_limits[0] = len(encoded_actions)
        batch.current_actions[0] = (
            0 if self.current_action is None else ACTION_WIRE_IDS[self.current_action]
        )
        batch.turn_indices[0] = self.turn_index

    def _sync_from_batch(self) -> None:
        batch = self._batch
        for seat, player in enumerate(self.players):
            player.cash = int(batch.cash[0, seat])
            player.hand_suits[:] = [int(card) for card in batch.hand_cards[0, seat] if card > 0]
        self.tiebreak_seat = int(batch.tiebreak_seats[0])
        self.upcoming[:] = [int(card) for card in batch.upcoming[0] if card > 0]
        resource_position = int(batch.resource_positions[0])
        resource_limit = int(batch.resource_limits[0])
        self.pile[:] = [
            int(card) for card in batch.resource_decks[0, resource_position:resource_limit]
        ]
        action_position = int(batch.action_positions[0])
        action_limit = int(batch.action_limits[0])
        self.action_deck[:] = [
            _ACTION_BY_WIRE_ID[int(action)]
            for action in batch.action_decks[0, action_position:action_limit]
            if action > 0
        ]
        current_action_id = int(batch.current_actions[0])
        self.current_action = (
            None if current_action_id == 0 else _ACTION_BY_WIRE_ID[current_action_id]
        )
        self.turn_index = int(batch.turn_indices[0])
        self.active_objectives[:] = [
            (
                int(objective_id),
                (
                    None
                    if batch.objective_claimants[0, index] < 0
                    else int(batch.objective_claimants[0, index])
                ),
            )
            for index, objective_id in enumerate(batch.objective_ids[0])
            if objective_id > 0
        ]

    def flip_action(self) -> str | None:
        if self.game_over:
            self.current_action = None
            return None
        self._sync_to_batch()
        action_id = int(self._batch.flip_actions()[0])
        self._sync_from_batch()
        action = _ACTION_BY_WIRE_ID[action_id]
        first = self.upcoming[0] if self.upcoming else 0
        second = self.upcoming[1] if len(self.upcoming) > 1 else 0
        self.events.append(
            TurnOpenedEvent(
                kind="turnOpened",
                action_id=action_id,
                resource_ids=(first, second),
            )
        )
        return action

    def legal_max_bid(self, seat: int) -> int:
        self._sync_to_batch()
        return int(self._batch.legal_max_bids()[0, seat])

    def resolve(self, raw_bids: Sequence[int]) -> TurnOutcome:
        action = self.current_action
        if action is None:
            raise RuntimeError("resolve() called with no flipped action")
        if len(raw_bids) != len(self.players):
            raise ValueError("one bid per seat required")
        upcoming_before = tuple(self.upcoming)
        objectives_before = {
            objective_id
            for objective_id, claimant in self.active_objectives
            if claimant is not None
        }
        self._sync_to_batch()
        result = self._batch.resolve_bids(np.asarray([raw_bids], dtype=np.int64))
        winner = int(result.winner_seats[0])
        paid = int(result.paid[0])
        effective = tuple(int(value) for value in result.effective_bids[0])
        self._sync_from_batch()
        if action in LOAN_PRINCIPAL:
            self.players[winner].loans.append(LOAN_PRINCIPAL[action])
        elif action in INVEST_PAYOUT:
            self.players[winner].investments.append((paid, INVEST_PAYOUT[action]))
        claimed = tuple(
            objective_id
            for objective_id, claimant in self.active_objectives
            if claimant == winner and objective_id not in objectives_before
        )
        grants = 1 if action == "Auction1" else (2 if action == "Auction2" else 0)
        bundle = upcoming_before[:grants]
        self.players[winner].won_suits.extend(bundle)
        self.players[winner].objective_wire_ids.extend(claimed)
        self.events.append(AuctionResolvedEvent(kind="auctionResolved", bids_by_seat=effective))
        mode = int(result.reveal_modes[0])
        reveal_needed = {0: None, 1: "auto", 2: "choice"}[mode]
        self.history.append(
            TurnRecord(
                turn_index=self.turn_index - 1,
                action=action,
                upcoming_before=upcoming_before,
                raw_bids=tuple(int(raw) for raw in raw_bids),
                effective_bids=effective,
                winner_seat=winner,
                paid=paid,
                bundle_suits=bundle,
                claimed_objective_wire_ids=claimed,
                reveal=None,
            )
        )
        return TurnOutcome(
            winner_seat=winner,
            paid=paid,
            effective_bids=effective,
            bundle_suits=bundle,
            claimed_objective_wire_ids=claimed,
            reveal_needed=reveal_needed,
        )

    def apply_reveal(self, seat: int, hand_index: int, *, auto: bool) -> RevealRecord:
        if not self.history:
            raise RuntimeError("apply_reveal() called before resolve()")
        if self.history[-1].reveal is not None:
            raise RuntimeError("apply_reveal() called twice for the same turn")
        player = self.players[seat]
        if not player.hand_suits:
            raise RuntimeError("apply_reveal() on an empty hand")
        index = hand_index if 0 <= hand_index < len(player.hand_suits) else 0
        suit = player.hand_suits[index]
        self._sync_to_batch()
        self._batch.pending_reveal_seats[0] = seat
        self._batch.apply_reveals(np.asarray([index], dtype=np.int16))
        self._sync_from_batch()
        player.revealed_suits.append(suit)
        self.events.append(InfoRevealedEvent(kind="infoRevealed", suit_id=suit))
        record = RevealRecord(seat=seat, suit=suit, auto=auto)
        self.history[-1] = replace(self.history[-1], reveal=record)
        return record

    def score(self) -> list[ScoreRow]:
        self._sync_to_batch()
        scores = self._batch.scores()
        rows: list[ScoreRow] = []
        for player in self.players:
            objective_value = sum(
                OBJECTIVE_PAYOUTS[objective_id] for objective_id in player.objective_wire_ids
            )
            items_value = int(scores.items[0, player.seat])
            investments_value = int(scores.investments[0, player.seat])
            loans_value = int(scores.loans[0, player.seat])
            cash = int(scores.cash[0, player.seat])
            rows.append(
                ScoreRow(
                    seat=player.seat,
                    name=player.name,
                    cash=cash,
                    items_value=items_value,
                    objectives_value=objective_value,
                    investments_value=investments_value,
                    loans_value=loans_value,
                    total=(cash + items_value + objective_value + investments_value - loans_value),
                )
            )
        return rows

    def ranking(self) -> list[int]:
        return [row.seat for row in sorted(self.score(), key=lambda row: -row.total)]
