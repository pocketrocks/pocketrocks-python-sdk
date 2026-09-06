"""Wire protocol framing: the one bot-wire version this SDK speaks, and the
translation between wire frames and the public ``DecisionContext``/``BotDecision``.

The vendored codec (``pocketrocks.internal.bot_wire``) speaks every version the
schema names and takes the version as an explicit argument. The SDK pins ONE:
:data:`PROTOCOL_VERSION`. It is offered at the handshake, stamped on every frame
the runtime writes, and enforced on every frame it reads -- the server serves
exactly one version at a time, so a frame in another version is malformed, not
negotiable. ``config.protocol_version`` must equal it (see ``BotConfig``).
"""

from __future__ import annotations

from dataclasses import fields
from typing import Final
from urllib.parse import urlencode

from pocketrocks.constants import connect_path
from pocketrocks.internal import bot_wire
from pocketrocks.internal.bot_wire import (
    DecisionRequest,
    DecisionResponse,
    Frame,
    bot_wire_protocol_versions,
    reconstruct_decision_context,
)
from pocketrocks.types import BotDecision, DecisionContext

#: The bot-wire protocol version this SDK speaks. Derived from the vendored
#: codec's schema constant, never spelled as a number, so the handshake and the
#: codec cannot name different versions.
PROTOCOL_VERSION: Final[int] = bot_wire_protocol_versions["v3"]


def encode_frame(frame: Frame) -> bytes:
    """Encode ``frame`` in :data:`PROTOCOL_VERSION`."""
    return bot_wire.encode_frame(frame, protocol_version=PROTOCOL_VERSION)


def decode_frame(data: bytes) -> Frame:
    """Decode a frame, rejecting any version but :data:`PROTOCOL_VERSION`.

    Raises ``ValueError`` (``"unexpected bot wire protocol version"``) for a frame
    in another supported version, exactly as for any other malformed byte.
    """
    return bot_wire.decode_frame(data, protocol_version=PROTOCOL_VERSION)


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
