from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

from pocketrocks.exceptions import InvalidBotDecision
from pocketrocks.internal.bot_wire import max_safe_integer

# How much the auction winner pays: their own bid, or the runner-up's (Vickrey).
# The winner is the highest bidder under either. Defined once, here, on the public
# module every bot already imports; ``pocketrocks.sim.ruleset`` re-exports it.
PaymentRule = Literal["first-price", "second-price"]
decisionKind = Literal["submitBid", "selectInfoToReveal"]
decisionActionKind = Literal["pass", "submitBid", "selectInfoToReveal"]
decisionFate = Literal["ok", "discarded", "corrected", "forwarded"]
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
    "decisionRejected",
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
    # The rule this game's auctions are priced under; ``cash_by_seat`` already
    # reflects it. Mirrors ``ReconstructedDecisionContext.payment_rule`` (the
    # wire copies fields by name, so the two must be added together). Defaults to
    # the rule the game has always had, so a context built without stating one
    # means what it always meant.
    payment_rule: PaymentRule = "first-price"
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
        ``revealable_count``. A ``pass`` is legal for either request kind, but
        only when it carries no value (``value is None``) — the wire has no field
        for a value on a pass. A bot can call this (or :meth:`is_legal`) to
        self-check before returning.

        The runtime does **not** call this directly — it calls :func:`classify`,
        which sorts the same rules into the ones the server repairs and the ones
        it cannot. This method reports both, and is unchanged for callers.
        """
        _check_encodable(self, decision)
        _check_clampable(self, decision)

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


def _check_encodable(context: DecisionContext, decision: BotDecision) -> None:
    """Tier A — the server has no repair path, so a frame is worth nothing.

    Either the runtime cannot build a well-formed frame at all (missing or
    non-integer value), or the server would silently no-op on it: a mismatched
    response kind has no handler, and ``revealInfoCard`` looks a card up by id
    and does nothing when it is absent rather than clamping the index.
    """
    # A pass is legal for either request kind, but the wire has no field for a
    # value on it — ``encode_frame`` raises on a valued pass. Checking it here,
    # before the request-kind branches, keeps the two surfaces consistent: the
    # live runtime would otherwise reach the codec and emit ``requestFailed``,
    # while the sim would silently drop the stray value and treat it as a plain
    # pass. There is nothing to repair, so it belongs in the unrepairable tier.
    if decision.action_kind == "pass" and decision.value is not None:
        raise InvalidBotDecision("pass responses must not carry a value")
    if context.decision_kind == "submitBid":
        if decision.action_kind == "selectInfoToReveal":
            raise InvalidBotDecision("submitBid requests cannot receive reveal responses")
        if decision.action_kind == "submitBid":
            if decision.value is None:
                raise InvalidBotDecision("submitBid responses require a value")
            if not isinstance(decision.value, int):
                # A float satisfies every range comparison below but cannot be
                # encoded as a wire varint at all — there is no value to clamp
                # or forward, so this belongs in the unrepairable tier, not
                # the clampable one.
                raise InvalidBotDecision("bid must be an integer")
        return
    if decision.action_kind == "submitBid":
        raise InvalidBotDecision("selectInfoToReveal requests cannot receive bid responses")
    if decision.action_kind == "selectInfoToReveal":
        if decision.value is None:
            raise InvalidBotDecision("selectInfoToReveal responses require a card index")
        if not isinstance(decision.value, int):
            raise InvalidBotDecision("card index must be an integer")
        if decision.value < 0 or decision.value >= context.revealable_count:
            raise InvalidBotDecision("card index is out of range")


def _check_clampable(context: DecisionContext, decision: BotDecision) -> None:
    """Tier B — the server clamps these itself, so forwarding beats swallowing.

    ``rules/turns.ts::recordBid`` applies ``max(0, min(amount, legal_max))`` in
    both the normal and loan branches, and ``SimEngine.resolve`` mirrors it.
    A bot that trips these still gets to participate; one whose decision is
    swallowed does not.
    """
    if context.decision_kind != "submitBid" or decision.action_kind != "submitBid":
        return
    if not isinstance(decision.value, int):
        return  # Tier A owns missing / non-integer values.
    if context.legal_max_amount is not None and decision.value > context.legal_max_amount:
        raise InvalidBotDecision("bid exceeds legal maximum")
    if decision.value < 0:
        raise InvalidBotDecision("bid must be non-negative")


def _wire_correction(decision: BotDecision) -> tuple[BotDecision, str] | None:
    """The wire-representable form of ``decision`` and why, or None if it is fine as-is.

    The bot wire carries unsigned varints only (``_encode_varint`` rejects
    ``value < 0`` and ``value > max_safe_integer``), so a bid outside that range
    cannot be sent at all — "let the server clamp it" is not available. Clamping
    to the wire's own bounds is the minimum change that makes the value
    expressible; it deliberately does NOT consult ``legal_max_amount``, because
    the game clamp belongs to the server (and to ``SimEngine.resolve``).

    The returned reason names the *encodability* failure rather than reusing a
    game-rule message. For the upper bound those two differ: the substitute is
    still far above any real ``legal_max_amount`` and will be clamped again
    server-side, so reporting "bid exceeds legal maximum" would tell a bot author
    the wrong thing about why the value was replaced and what it was replaced with.
    """
    if decision.action_kind != "submitBid" or not isinstance(decision.value, int):
        return None
    if decision.value < 0:
        return (
            BotDecision.submit_bid(0),
            "bid must be non-negative; the bot wire encodes unsigned integers only",
        )
    if decision.value > max_safe_integer:
        return (
            BotDecision.submit_bid(max_safe_integer),
            "bid is not encodable on the bot wire: it exceeds the largest wire "
            f"integer ({max_safe_integer}); the substitute is still subject to the "
            "server's own clamp",
        )
    return None


def classify(
    context: DecisionContext, decision: BotDecision
) -> tuple[decisionFate, InvalidBotDecision | None, BotDecision]:
    """Sort ``decision`` into its tier, returning its fate, the reason, and what to use.

    - ``"ok"`` — legal; use the decision as returned.
    - ``"discarded"`` — the server has no repair path; the bot's value must not reach
      the rules.
    - ``"corrected"`` — the value cannot be encoded at all; use the coerced value and
      report both.
    - ``"forwarded"`` — the server repairs it; send it unchanged and let the engine clamp.

    The live runtime and the sim both branch on this one function, which is what
    keeps the two surfaces from drifting.
    """
    try:
        _check_encodable(context, decision)
    except InvalidBotDecision as error:
        return "discarded", error, decision
    # Encodability is a property of the wire, not of the game rules, so it is
    # checked on its own and BEFORE the clampable rules. Deciding "corrected"
    # inside the _check_clampable failure branch would make it contingent on a
    # game rule happening to fire first: a context whose legal_max_amount is None
    # would let an unencodable value through as "ok", and it would then raise in
    # the codec and be swallowed — the exact bug this tier exists to prevent.
    correction = _wire_correction(decision)
    if correction is not None:
        substitute, reason = correction
        return "corrected", InvalidBotDecision(reason), substitute
    try:
        _check_clampable(context, decision)
    except InvalidBotDecision as error:
        return "forwarded", error, decision
    return "ok", None, decision
