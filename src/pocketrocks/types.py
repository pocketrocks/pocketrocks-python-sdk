from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

from pocketrocks.exceptions import InvalidBotDecision

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
        """Milliseconds left until the server deadline, measured from *now*.

        Uses the current time rather than ``received_at`` so it reflects the
        real remaining budget: a request may sit in the queue before a worker
        starts it, and the runtime enforces its timeout from that later start
        time. Measuring from ``received_at`` would overstate the budget by the
        full queue delay. Clamped at ``0``."""
        return max(0, self.deadline_at - int(time.time() * 1000))

    def validate(self, decision: BotDecision) -> None:
        """Raise :class:`~pocketrocks.exceptions.InvalidBotDecision` if ``decision``
        is not a legal response to this context.

        Legality is a pure function of the context and the decision: the response
        kind must match the request kind, a bid must be non-negative and within
        ``legal_max_amount``, and a reveal index must be within
        ``revealable_count``. ``pass`` is always legal. The runtime calls this on
        every returned decision; a bot can call it (or :meth:`is_legal`) itself to
        self-check before returning.
        """
        if self.decision_kind == "submitBid":
            if decision.action_kind == "selectInfoToReveal":
                raise InvalidBotDecision("submitBid requests cannot receive reveal responses")
            if decision.action_kind == "submitBid":
                if decision.value is None:
                    raise InvalidBotDecision("submitBid responses require a value")
                if self.legal_max_amount is not None and decision.value > self.legal_max_amount:
                    raise InvalidBotDecision("bid exceeds legal maximum")
                if decision.value < 0:
                    raise InvalidBotDecision("bid must be non-negative")
            return
        if decision.action_kind == "submitBid":
            raise InvalidBotDecision("selectInfoToReveal requests cannot receive bid responses")
        if decision.action_kind == "selectInfoToReveal":
            if decision.value is None:
                raise InvalidBotDecision("selectInfoToReveal responses require a card index")
            if decision.value < 0 or decision.value >= self.revealable_count:
                raise InvalidBotDecision("card index is out of range")

    def is_legal(self, decision: BotDecision) -> bool:
        """Whether ``decision`` is a legal response to this context. A boolean
        wrapper over :meth:`validate` for bots weighing options without try/except."""
        try:
            self.validate(decision)
        except InvalidBotDecision:
            return False
        return True

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
