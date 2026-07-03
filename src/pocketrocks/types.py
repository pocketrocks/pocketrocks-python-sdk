from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

decisionKind = Literal["submitBid", "selectInfoToReveal"]
decisionActionKind = Literal["pass", "submitBid", "selectInfoToReveal"]
runtimeEventKind = Literal[
    "connected",
    "disconnected",
    "connectionRejected",
    "connectionError",
    "heartbeatReceived",
    "heartbeatSent",
    "requestQueued",
    "requestDropped",
    "requestCompleted",
    "requestFailed",
    "malformedFrame",
]


def _sum_columns(matrix: tuple[tuple[int, ...], ...]) -> tuple[int, ...]:
    """Sum a per-seat matrix down to per-suit totals (one entry per column)."""
    if not matrix:
        return ()
    return tuple(sum(column) for column in zip(*matrix, strict=False))


@dataclass(slots=True, frozen=True)
class BotDecision:
    action_kind: decisionActionKind
    value: int | None = None

    @classmethod
    def pass_turn(cls) -> BotDecision:
        return cls(action_kind="pass")

    @classmethod
    def submit_bid(cls, amount: int) -> BotDecision:
        return cls(action_kind="submitBid", value=amount)

    @classmethod
    def select_info_to_reveal(cls, card_index: int) -> BotDecision:
        return cls(action_kind="selectInfoToReveal", value=card_index)


@dataclass(slots=True, frozen=True)
class DecisionContext:
    request_id: str
    deadline_at: int
    received_at: int
    decision_kind: decisionKind
    player_count: int
    starting_cash: int
    value_chart: tuple[int, ...]
    objective_ids: tuple[int, ...]
    current_action_id: int | None
    current_resource_ids: tuple[int, int]
    cash_by_seat: tuple[int, ...]
    tiebreak_seat: int
    won_resource_counts_by_seat: tuple[tuple[int, ...], ...]
    revealed_info_counts_by_seat: tuple[tuple[int, ...], ...]
    owned_objective_ids_by_seat: tuple[tuple[int, ...], ...]
    bot_seat: int
    current_hand_suit_ids: tuple[int, ...]
    legal_max_amount: int | None
    revealable_count: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def remaining_deadline_ms(self) -> int:
        return max(0, self.deadline_at - self.received_at)

    @property
    def revealed_info_counts_by_suit(self) -> tuple[int, ...]:
        """Total revealed info per suit across all seats.

        Column sums of :attr:`revealed_info_counts_by_seat`; index ``i`` is the
        count for ``pocketrocks.reference.Suit(i + 1)``.
        """
        return _sum_columns(self.revealed_info_counts_by_seat)

    @property
    def won_resource_counts_by_suit(self) -> tuple[int, ...]:
        """Total resources won per suit across all seats.

        Column sums of :attr:`won_resource_counts_by_seat`; index ``i`` is the
        count for ``pocketrocks.reference.Suit(i + 1)``.
        """
        return _sum_columns(self.won_resource_counts_by_seat)


@dataclass(slots=True, frozen=True)
class RuntimeEvent:
    kind: runtimeEventKind
    details: dict[str, Any] = field(default_factory=dict)
