"""Vectorized PocketRocks simulation state.

The batch engine stores homogeneous-player-count games in compact NumPy arrays.
Its transition kernel is the canonical rules implementation used by bulk RL and
the scalar compatibility facade.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from pocketrocks.internal.bot_wire_v2.constants import bot_wire_objective_definitions

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
)
from .rng import batch_shuffled_many


@dataclass(frozen=True)
class BatchTurnOutcome:
    winner_seats: NDArray[np.int8]
    paid: NDArray[np.int16]
    effective_bids: NDArray[np.int16]
    reveal_modes: NDArray[np.uint8]  # 0 none, 1 auto, 2 choice


@dataclass(frozen=True)
class BatchScores:
    cash: NDArray[np.int16]
    items: NDArray[np.int16]
    objectives: NDArray[np.int16]
    investments: NDArray[np.int16]
    loans: NDArray[np.int16]
    total: NDArray[np.int16]


_LOAN_BY_ACTION_ID = {
    ACTION_WIRE_IDS[action]: principal for action, principal in LOAN_PRINCIPAL.items()
}
_INVEST_PAYOUT_BY_ACTION_ID = {
    ACTION_WIRE_IDS[action]: payout for action, payout in INVEST_PAYOUT.items()
}
_AUCTION_1_ID = ACTION_WIRE_IDS["Auction1"]
_AUCTION_2_ID = ACTION_WIRE_IDS["Auction2"]


def _objective_met(
    objective_ids: NDArray[np.int8],
    counts: NDArray[np.uint8],
) -> NDArray[np.bool_]:
    met = np.zeros(len(objective_ids), dtype=np.bool_)
    for objective_id in range(1, 31):
        rows = objective_ids == objective_id
        if not rows.any():
            continue
        definition = bot_wire_objective_definitions[str(objective_id)]
        pattern = definition.get("pattern")
        if pattern == "same2":
            values = np.any(counts >= 2, axis=1)
        elif pattern == "same3":
            values = np.any(counts >= 3, axis=1)
        elif pattern == "different3":
            values = np.count_nonzero(counts, axis=1) >= 3
        elif pattern == "different4":
            values = np.count_nonzero(counts, axis=1) >= 4
        elif pattern == "twoPairs4":
            values = np.count_nonzero(counts >= 2, axis=1) >= 2
        else:
            requirement = np.asarray(definition["requirement"], dtype=np.uint8)
            values = np.all(counts >= requirement, axis=1)
        met |= rows & values
    return met


class BatchSimEngine:
    """A fixed-size batch of games sharing one player count."""

    def __init__(
        self,
        *,
        player_count: int,
        seeds: tuple[str, ...],
        value_chart_keys: tuple[str, ...],
        objectives_enabled: tuple[bool, ...],
    ) -> None:
        self.player_count = player_count
        self.seeds = seeds
        self.batch_size = len(seeds)
        self.value_chart_keys = value_chart_keys
        self.objectives_enabled = np.asarray(objectives_enabled, dtype=np.bool_)

        action_ids = tuple(ACTION_WIRE_IDS[action] for action in ACTION_DECK)
        item_decks, action_decks, tiebreak_orders, objective_orders = batch_shuffled_many(
            (
                ITEM_DECK_SUITS,
                action_ids,
                tuple(range(player_count)),
                ALL_OBJECTIVE_WIRE_IDS,
            ),
            seeds,
        )
        self.item_decks = item_decks.astype(np.uint8, copy=False)
        self.action_decks = action_decks.astype(np.uint8, copy=False)
        self.tiebreak_seats = tiebreak_orders[:, 0].astype(np.uint8, copy=False)
        self.objective_ids: NDArray[np.int8] = np.zeros(
            (self.batch_size, OBJECTIVES_PER_GAME),
            dtype=np.int8,
        )
        enabled_rows = np.asarray(objectives_enabled, dtype=np.bool_)
        self.objective_ids[enabled_rows] = objective_orders[
            enabled_rows,
            :OBJECTIVES_PER_GAME,
        ].astype(np.int8, copy=False)

        cards_per_player = INFO_CARDS_PER_PLAYER[player_count]
        dealt_count = player_count * cards_per_player
        self.hand_cards: NDArray[np.uint8] = self.item_decks[
            :, :dealt_count
        ].reshape(self.batch_size, player_count, cards_per_player).copy()
        self.initial_info_counts: NDArray[np.uint8] = np.stack(
            [
                np.count_nonzero(self.hand_cards == suit_id, axis=(1, 2))
                for suit_id in range(1, 6)
            ],
            axis=1,
        ).astype(np.uint8, copy=False)
        self.resource_decks: NDArray[np.uint8] = self.item_decks[:, dealt_count:].copy()
        self.upcoming: NDArray[np.uint8] = self.resource_decks[:, :2].copy()
        self.resource_positions: NDArray[np.uint8] = np.full(
            self.batch_size,
            2,
            dtype=np.uint8,
        )
        self.resource_limits: NDArray[np.uint8] = np.full(
            self.batch_size,
            self.resource_decks.shape[1],
            dtype=np.uint8,
        )

        self.cash: NDArray[np.int16] = np.full(
            (self.batch_size, player_count),
            STARTING_CASH[player_count],
            dtype=np.int16,
        )
        self.won_counts: NDArray[np.uint8] = np.zeros(
            (self.batch_size, player_count, 5),
            dtype=np.uint8,
        )
        self.revealed_counts: NDArray[np.uint8] = np.zeros_like(self.won_counts)
        self.objective_claimants: NDArray[np.int8] = np.full(
            (self.batch_size, OBJECTIVES_PER_GAME),
            -1,
            dtype=np.int8,
        )
        self.owned_objectives: NDArray[np.bool_] = np.zeros(
            (self.batch_size, player_count, 30),
            dtype=np.bool_,
        )
        self.loan_principal: NDArray[np.int16] = np.zeros_like(self.cash)
        self.investment_values: NDArray[np.int16] = np.zeros_like(self.cash)
        self.value_charts: NDArray[np.int16] = np.asarray(
            [VALUE_CHARTS[key] for key in value_chart_keys],
            dtype=np.int16,
        )
        self.action_positions: NDArray[np.uint8] = np.zeros(
            self.batch_size,
            dtype=np.uint8,
        )
        self.action_limits: NDArray[np.uint8] = np.full(
            self.batch_size,
            self.action_decks.shape[1],
            dtype=np.uint8,
        )
        self.current_actions: NDArray[np.uint8] = np.zeros(
            self.batch_size,
            dtype=np.uint8,
        )
        self.turn_indices: NDArray[np.uint8] = np.zeros(
            self.batch_size,
            dtype=np.uint8,
        )
        self.pending_reveal_seats: NDArray[np.int8] = np.full(
            self.batch_size,
            -1,
            dtype=np.int8,
        )
        self.reveal_modes: NDArray[np.uint8] = np.zeros(
            self.batch_size,
            dtype=np.uint8,
        )

    @classmethod
    def start(
        cls,
        *,
        player_count: int,
        seeds: Sequence[str | int],
        value_charts: Sequence[str] | None = None,
        objectives_enabled: Sequence[bool] | None = None,
    ) -> BatchSimEngine:
        if not 3 <= player_count <= 5:
            raise ValueError("PocketRocks supports 3-5 players")
        normalized_seeds = tuple(str(seed) for seed in seeds)
        if not normalized_seeds:
            raise ValueError("BatchSimEngine requires at least one seed")
        batch_size = len(normalized_seeds)
        chart_keys = (
            ("A",) * batch_size
            if value_charts is None
            else tuple(chart.upper() for chart in value_charts)
        )
        if len(chart_keys) != batch_size:
            raise ValueError("value_charts length must match seeds")
        unknown_charts = tuple(key for key in chart_keys if key not in VALUE_CHARTS)
        if unknown_charts:
            raise ValueError(f"unknown value charts: {unknown_charts!r}")
        objective_flags = (
            (True,) * batch_size
            if objectives_enabled is None
            else tuple(objectives_enabled)
        )
        if len(objective_flags) != batch_size:
            raise ValueError("objectives_enabled length must match seeds")
        return cls(
            player_count=player_count,
            seeds=normalized_seeds,
            value_chart_keys=chart_keys,
            objectives_enabled=objective_flags,
        )

    def game_over_mask(self) -> NDArray[np.bool_]:
        no_resources = (self.upcoming == 0).all(axis=1) & (
            self.resource_positions >= self.resource_limits
        )
        no_actions = self.action_positions >= self.action_limits
        return np.asarray(no_resources | no_actions, dtype=np.bool_)

    def flip_actions(self) -> NDArray[np.uint8]:
        if np.any(self.reveal_modes):
            raise RuntimeError("cannot flip actions while reveals are pending")
        if np.any(self.current_actions):
            raise RuntimeError("an action is already flipped")
        rows = np.arange(self.batch_size)
        active = ~self.game_over_mask()
        self.current_actions.fill(0)
        self.current_actions[active] = self.action_decks[
            rows[active],
            self.action_positions[active],
        ]
        self.action_positions[active] += 1
        return self.current_actions.copy()

    def legal_max_bids(self) -> NDArray[np.int16]:
        legal = self.cash.copy()
        for action_id, principal in _LOAN_BY_ACTION_ID.items():
            rows = self.current_actions == action_id
            legal[rows] += principal
        legal[self.current_actions == 0] = 0
        return legal

    def resolve_bids(self, bids: NDArray[np.integer]) -> BatchTurnOutcome:
        if bids.shape != (self.batch_size, self.player_count):
            raise ValueError(
                f"bids shape must be {(self.batch_size, self.player_count)}, "
                f"got {bids.shape}"
            )
        if not np.issubdtype(bids.dtype, np.integer):
            raise ValueError("bids must use an integer dtype")
        active = self.current_actions > 0
        if not active.any():
            raise RuntimeError("resolve_bids() requires a flipped action")
        legal = self.legal_max_bids()
        effective = np.minimum(np.maximum(bids, 0), legal).astype(np.int16, copy=False)
        effective[~active] = 0
        highest = effective.max(axis=1)
        winners = np.full(self.batch_size, -1, dtype=np.int8)
        rows = np.arange(self.batch_size)
        unresolved = active.copy()
        for offset in range(1, self.player_count + 1):
            seats = (self.tiebreak_seats + offset) % self.player_count
            selected = unresolved & (effective[rows, seats] == highest)
            winners[selected] = seats[selected].astype(np.int8, copy=False)
            unresolved[selected] = False
        paid = np.zeros(self.batch_size, dtype=np.int16)
        paid[active] = highest[active]
        active_rows = rows[active]
        active_winners = winners[active].astype(np.intp, copy=False)
        self.cash[active_rows, active_winners] -= paid[active]
        self.tiebreak_seats[active] = winners[active].astype(np.uint8, copy=False)

        actions = self.current_actions.copy()
        for action_id, principal in _LOAN_BY_ACTION_ID.items():
            loan_rows = active & (actions == action_id)
            loan_indices = rows[loan_rows]
            loan_winners = winners[loan_rows].astype(np.intp, copy=False)
            self.cash[loan_indices, loan_winners] += principal
            self.loan_principal[loan_indices, loan_winners] += principal
        for action_id, payout in _INVEST_PAYOUT_BY_ACTION_ID.items():
            invest_rows = active & (actions == action_id)
            invest_indices = rows[invest_rows]
            invest_winners = winners[invest_rows].astype(np.intp, copy=False)
            self.investment_values[invest_indices, invest_winners] += (
                paid[invest_rows] + payout
            )

        auction_rows = active & np.isin(actions, (_AUCTION_1_ID, _AUCTION_2_ID))
        grant_counts = np.zeros(self.batch_size, dtype=np.uint8)
        grant_counts[actions == _AUCTION_1_ID] = 1
        grant_counts[actions == _AUCTION_2_ID] = 2
        for resource_slot in range(2):
            granted = (
                auction_rows
                & (grant_counts > resource_slot)
                & (self.upcoming[:, resource_slot] > 0)
            )
            granted_rows = rows[granted]
            granted_winners = winners[granted].astype(np.intp, copy=False)
            suits = self.upcoming[granted, resource_slot].astype(np.intp) - 1
            np.add.at(
                self.won_counts,
                (granted_rows, granted_winners, suits),
                1,
            )
        one_resource = auction_rows & (grant_counts == 1)
        two_resources = auction_rows & (grant_counts == 2)
        self.upcoming[one_resource, 0] = self.upcoming[one_resource, 1]
        self.upcoming[one_resource, 1] = 0
        self.upcoming[two_resources] = 0
        self._refill_upcoming()

        winner_counts = np.zeros((self.batch_size, 5), dtype=np.uint8)
        winner_counts[active] = self.won_counts[
            active_rows,
            active_winners,
        ]
        for objective_index in range(OBJECTIVES_PER_GAME):
            objective_ids = self.objective_ids[:, objective_index]
            claimable = (
                auction_rows
                & (objective_ids > 0)
                & (self.objective_claimants[:, objective_index] < 0)
                & _objective_met(objective_ids, winner_counts)
            )
            claim_rows = rows[claimable]
            claim_winners = winners[claimable].astype(np.intp, copy=False)
            self.objective_claimants[claimable, objective_index] = winners[claimable]
            objective_columns = objective_ids[claimable].astype(np.intp) - 1
            self.owned_objectives[
                claim_rows,
                claim_winners,
                objective_columns,
            ] = True

        hand_lengths = np.count_nonzero(self.hand_cards, axis=2)
        winner_hand_lengths = np.zeros(self.batch_size, dtype=np.uint8)
        winner_hand_lengths[active] = hand_lengths[active_rows, active_winners]
        reveal_modes = np.zeros(self.batch_size, dtype=np.uint8)
        reveal_modes[active & (winner_hand_lengths == 1)] = 1
        reveal_modes[active & (winner_hand_lengths > 1)] = 2
        self.pending_reveal_seats.fill(-1)
        self.pending_reveal_seats[active] = winners[active]
        self.reveal_modes = reveal_modes

        self.turn_indices[active] += 1
        self.current_actions.fill(0)
        return BatchTurnOutcome(
            winner_seats=winners,
            paid=paid,
            effective_bids=effective.copy(),
            reveal_modes=reveal_modes.copy(),
        )

    def _refill_upcoming(self) -> None:
        rows = np.arange(self.batch_size)
        for slot in range(2):
            needs_card = (self.upcoming[:, slot] == 0) & (
                self.resource_positions < self.resource_limits
            )
            positions = self.resource_positions[needs_card].astype(np.intp, copy=False)
            self.upcoming[needs_card, slot] = self.resource_decks[
                rows[needs_card],
                positions,
            ]
            self.resource_positions[needs_card] += 1

    def apply_reveals(self, indices: NDArray[np.integer]) -> None:
        if np.any(self.current_actions):
            raise RuntimeError("apply_reveals() requires resolve_bids() first")
        if indices.shape != (self.batch_size,):
            raise ValueError(
                f"reveal indices shape must be {(self.batch_size,)}, got {indices.shape}"
            )
        if not np.issubdtype(indices.dtype, np.integer):
            raise ValueError("reveal indices must use an integer dtype")
        pending = self.reveal_modes > 0
        hand_lengths = np.count_nonzero(self.hand_cards, axis=2)
        rows = np.arange(self.batch_size)
        seats = self.pending_reveal_seats.astype(np.intp, copy=False)
        valid_lengths = np.zeros(self.batch_size, dtype=np.int16)
        valid_lengths[pending] = hand_lengths[rows[pending], seats[pending]]
        invalid = pending & ((indices < 0) | (indices >= valid_lengths))
        unexpected = ~pending & (indices != -1)
        if invalid.any() or unexpected.any():
            raise ValueError("reveal index is out of range or no reveal is pending")

        reveal_rows = rows[pending]
        reveal_seats = seats[pending]
        reveal_indices = indices[pending].astype(np.intp, copy=False)
        suits = self.hand_cards[
            reveal_rows,
            reveal_seats,
            reveal_indices,
        ].astype(np.intp)
        np.add.at(
            self.revealed_counts,
            (reveal_rows, reveal_seats, suits - 1),
            1,
        )
        selected_hands = self.hand_cards[reveal_rows, reveal_seats]
        positions = np.arange(self.hand_cards.shape[2])
        sources = positions[None, :] + (
            positions[None, :] >= reveal_indices[:, None]
        )
        sources = np.minimum(sources, self.hand_cards.shape[2] - 1)
        compacted = np.take_along_axis(selected_hands, sources, axis=1)
        compacted[:, -1] = 0
        self.hand_cards[reveal_rows, reveal_seats] = compacted
        self.pending_reveal_seats.fill(-1)
        self.reveal_modes.fill(0)

    def scores(self) -> BatchScores:
        rows = np.arange(self.batch_size)[:, None]
        value_indices = np.minimum(self.initial_info_counts, 5).astype(np.intp)
        values_by_suit = self.value_charts[rows, value_indices]
        items = np.asarray(
            np.sum(
                self.won_counts.astype(np.int16) * values_by_suit[:, None, :],
                axis=2,
                dtype=np.int16,
            ),
            dtype=np.int16,
        )
        payouts = np.asarray(
            [OBJECTIVE_PAYOUTS.get(objective_id, 0) for objective_id in range(1, 31)],
            dtype=np.int16,
        )
        objectives = np.asarray(
            np.sum(
                self.owned_objectives.astype(np.int16) * payouts[None, None, :],
                axis=2,
                dtype=np.int16,
            ),
            dtype=np.int16,
        )
        total = (
            self.cash
            + items
            + objectives
            + self.investment_values
            - self.loan_principal
        ).astype(np.int16, copy=False)
        return BatchScores(
            cash=self.cash.copy(),
            items=items,
            objectives=objectives,
            investments=self.investment_values.copy(),
            loans=self.loan_principal.copy(),
            total=total,
        )

    def rankings(self) -> NDArray[np.int8]:
        return np.argsort(-self.scores().total, axis=1, kind="stable").astype(np.int8)
