"""One reporting path for a rejected decision, shared by the live runtime and the sim.

Both surfaces call :func:`report_rejection` with the output of
``pocketrocks.types.classify``. Keeping the log line, the event payload, and the
``on_error`` call in a single place is what makes sim and live observably
identical for the same bad decision — the divergence this module exists to
prevent is the one that shipped for months without anyone noticing.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from pocketrocks.exceptions import InvalidBotDecision
from pocketrocks.types import BotDecision, DecisionContext, RuntimeEvent, decisionFate


class _RejectionSink(Protocol):
    async def on_runtime_event(self, event: RuntimeEvent) -> None: ...

    async def on_error(self, error: Exception) -> None: ...


async def report_rejection(
    bot: _RejectionSink,
    logger: logging.Logger,
    *,
    context: DecisionContext,
    decision: BotDecision,
    error: InvalidBotDecision,
    applied: decisionFate,
    debug: bool,
    outgoing: BotDecision,
) -> None:
    """Log, emit ``decisionRejected``, and notify the bot that it played illegally.

    ``applied`` is the decision's fate in surface-neutral terms — ``"discarded"``
    when the bot's value never reaches the rules, ``"forwarded"`` when it does and
    the engine clamps it, or ``"corrected"`` when the value could not be encoded at
    all. ``outgoing`` is what ``classify`` returned alongside ``applied`` — for
    every fate except ``"corrected"`` it is ``decision`` itself, so deriving the
    ``corrected_value`` detail from ``applied == "corrected"`` here (rather than
    at each call site) is what keeps the sim and the live runtime from having to
    duplicate that condition. Naming the outcome rather than the mechanism is
    what lets the two surfaces emit byte-identical events for the same input.
    """
    details: dict[str, Any] = {
        "request_id": context.request_id,
        "decision_kind": context.decision_kind,
        "action_kind": decision.action_kind,
        "value": decision.value,
        "detail": str(error),
        "applied": applied,
    }
    if applied == "corrected":
        details["corrected_value"] = outgoing.value
    if debug:
        details["context"] = context
    logger.warning(
        "decision %s rejected (%s %s, %s%s): %s",
        context.request_id,
        decision.action_kind,
        decision.value,
        applied,
        f" -> {outgoing.value}" if applied == "corrected" else "",
        error,
    )
    await bot.on_runtime_event(RuntimeEvent(kind="decisionRejected", details=details))
    await bot.on_error(error)
