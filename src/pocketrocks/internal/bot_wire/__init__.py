"""Vendored PocketRocks bot-wire codec (generated upstream; see README.md here).

Version-neutral on purpose: the codec speaks every version the schema names and
takes the protocol version as an explicit argument. The SDK pins the ONE version
it speaks in ``pocketrocks.protocol`` -- import ``encode_frame``/``decode_frame``
from there, not from here, unless you are testing the codec itself.
"""

from .codec import (
    bot_wire_max_safe_signed_integer,
    decode_frame,
    decode_presence,
    decode_signed_varint,
    encode_frame,
    encode_presence,
    encode_signed_varint,
    is_protocol_version,
    max_safe_integer,
    supported_protocol_versions,
)
from .constants import (
    bot_wire_game_setup_reserved_slots,
    bot_wire_payment_rule_ids,
    bot_wire_protocol_versions,
)
from .reconstruction import reconstruct_decision_context
from .types import (
    AuctionResolvedEvent,
    CommonEvent,
    DecisionRequest,
    DecisionResponse,
    Frame,
    GameSetupEvent,
    HeartbeatRequest,
    HeartbeatResponse,
    InfoRevealedEvent,
    PaymentRule,
    ReconstructedDecisionContext,
    TurnOpenedEvent,
)

__all__ = [
    "AuctionResolvedEvent",
    "CommonEvent",
    "DecisionRequest",
    "DecisionResponse",
    "Frame",
    "GameSetupEvent",
    "HeartbeatRequest",
    "HeartbeatResponse",
    "InfoRevealedEvent",
    "PaymentRule",
    "ReconstructedDecisionContext",
    "TurnOpenedEvent",
    "bot_wire_game_setup_reserved_slots",
    "bot_wire_max_safe_signed_integer",
    "bot_wire_payment_rule_ids",
    "bot_wire_protocol_versions",
    "decode_frame",
    "decode_presence",
    "decode_signed_varint",
    "encode_frame",
    "encode_presence",
    "encode_signed_varint",
    "is_protocol_version",
    "max_safe_integer",
    "reconstruct_decision_context",
    "supported_protocol_versions",
]
