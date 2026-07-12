from __future__ import annotations

from dataclasses import fields
from urllib.parse import urlencode

from pocketrocks.constants import connect_path
from pocketrocks.internal.bot_wire_v2 import (
    DecisionRequest,
    DecisionResponse,
    reconstruct_decision_context,
)
from pocketrocks.types import BotDecision, DecisionContext


def build_connection_url(server_url: str, bot_id: str, protocol_version: int, capacity: int) -> str:
    base_url = server_url.rstrip("/")
    query = urlencode(
        {
            "botId": bot_id,
            "protocolVersion": protocol_version,
            "capacity": capacity,
        }
    )
    return f"{base_url}{connect_path}?{query}"


def build_decision_context(request: DecisionRequest, *, received_at: int) -> DecisionContext:
    """Shape a reconstructed game state into the public ``DecisionContext``.

    Every field ``ReconstructedDecisionContext`` (the generated core) carries is
    also a field of ``DecisionContext`` with the same name and value, so those are
    copied by name-matching — defined once, not restated. If upstream regenerates
    and adds a field the public type lacks, the spread raises loudly instead of
    drifting silently. The six request- and derivation-scoped fields that have no
    counterpart on the core are set explicitly.
    """
    reconstructed = reconstruct_decision_context(request)
    shared = {field.name: getattr(reconstructed, field.name) for field in fields(reconstructed)}
    return DecisionContext(
        request_id=request.request_id,
        deadline_at=request.deadline_at,
        received_at=received_at,
        decision_kind=request.decision_kind,
        revealable_count=len(reconstructed.current_hand_suit_ids),
        metadata={},
        **shared,
    )


def decision_to_protocol_response(request_id: str, decision: BotDecision) -> DecisionResponse:
    return DecisionResponse(
        kind="decisionResponse",
        request_id=request_id,
        action_kind=decision.action_kind,
        value=decision.value,
    )
