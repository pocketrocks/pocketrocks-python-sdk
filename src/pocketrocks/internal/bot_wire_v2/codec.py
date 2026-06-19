from __future__ import annotations

from typing import Literal, cast
from uuid import UUID

from .constants import (
    bot_wire_decision_kinds,
    bot_wire_event_kinds,
    bot_wire_message_kinds,
    bot_wire_protocol_version,
    bot_wire_response_action_kinds,
)
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
    TurnOpenedEvent,
)

max_safe_integer = 9_007_199_254_740_991


def _encode_varint(value: int) -> bytes:
    if value < 0 or value > max_safe_integer:
        raise ValueError("bot wire integer must be an unsigned safe integer")
    output = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        output.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(output)


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def read(self, length: int) -> bytes:
        end = self.offset + length
        if end > len(self.data):
            raise ValueError("bot wire frame is truncated")
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def varint(self) -> int:
        start = self.offset
        value = 0
        shift = 0
        for _ in range(8):
            byte = self.read(1)[0]
            value |= (byte & 0x7F) << shift
            if value > max_safe_integer:
                raise ValueError("bot wire integer overflow")
            if byte & 0x80 == 0:
                if self.offset - start > 1 and byte == 0:
                    raise ValueError("bot wire varint is not canonical")
                return value
            shift += 7
        raise ValueError("bot wire integer overflow")

    def finish(self) -> None:
        if self.offset != len(self.data):
            raise ValueError("bot wire frame has trailing bytes")


def _encode_event(event: CommonEvent) -> bytes:
    output = bytearray()
    output += _encode_varint(bot_wire_event_kinds[event.kind])
    if isinstance(event, GameSetupEvent):
        output += _encode_varint(event.player_count)
        output += _encode_varint(event.starting_cash)
        for value in event.value_chart:
            output += _encode_varint(value)
        output += _encode_varint(event.initial_tiebreak_seat + 1)
        output += _encode_varint(len(event.objective_ids))
        for value in event.objective_ids:
            output += _encode_varint(value)
    elif isinstance(event, TurnOpenedEvent):
        output += _encode_varint(event.action_id)
        output += _encode_varint(event.resource_ids[0])
        output += _encode_varint(event.resource_ids[1])
    elif isinstance(event, AuctionResolvedEvent):
        output += _encode_varint(len(event.bids_by_seat))
        for value in event.bids_by_seat:
            output += _encode_varint(value)
    elif isinstance(event, InfoRevealedEvent):
        output += _encode_varint(event.suit_id)
    return bytes(output)


def encode_frame(frame: Frame) -> bytes:
    output = bytearray()
    output += _encode_varint(bot_wire_protocol_version)
    output += _encode_varint(bot_wire_message_kinds[frame.kind])
    output += UUID(frame.request_id).bytes
    if isinstance(frame, HeartbeatRequest):
        output += _encode_varint(frame.deadline_at)
    elif isinstance(frame, DecisionRequest):
        output += _encode_varint(frame.deadline_at)
        output += _encode_varint(bot_wire_decision_kinds[frame.decision_kind])
        common = bytearray()
        common += _encode_varint(len(frame.common_events))
        for event in frame.common_events:
            common += _encode_event(event)
        output += _encode_varint(len(common))
        output += common
        output += _encode_varint(frame.bot_seat + 1)
        output += _encode_varint(len(frame.current_hand_suit_ids))
        for suit_id in frame.current_hand_suit_ids:
            output += _encode_varint(suit_id)
    elif isinstance(frame, DecisionResponse):
        output += _encode_varint(bot_wire_response_action_kinds[frame.action_kind])
        if frame.action_kind == "pass":
            if frame.value is not None:
                raise ValueError("pass responses must not include a value")
        else:
            if frame.value is None:
                raise ValueError("decision responses must include a value")
            output += _encode_varint(frame.value)
    return bytes(output)


def _decode_event(reader: _Reader) -> CommonEvent:
    kind = reader.varint()
    if kind == bot_wire_event_kinds["gameSetup"]:
        player_count = reader.varint()
        starting_cash = reader.varint()
        value_chart = cast(
            tuple[int, int, int, int, int, int],
            tuple(reader.varint() for _ in range(6)),
        )
        seat = reader.varint() - 1
        objective_ids = tuple(reader.varint() for _ in range(reader.varint()))
        return GameSetupEvent(
            "gameSetup",
            player_count,
            starting_cash,
            value_chart,
            seat,
            objective_ids,
        )
    if kind == bot_wire_event_kinds["turnOpened"]:
        return TurnOpenedEvent("turnOpened", reader.varint(), (reader.varint(), reader.varint()))
    if kind == bot_wire_event_kinds["auctionResolved"]:
        return AuctionResolvedEvent(
            "auctionResolved",
            tuple(reader.varint() for _ in range(reader.varint())),
        )
    if kind == bot_wire_event_kinds["infoRevealed"]:
        return InfoRevealedEvent("infoRevealed", reader.varint())
    raise ValueError("unknown bot wire event kind")


def decode_frame(data: bytes) -> Frame:
    reader = _Reader(data)
    if reader.varint() != bot_wire_protocol_version:
        raise ValueError("unsupported bot wire protocol version")
    kind = reader.varint()
    request_id = str(UUID(bytes=reader.read(16)))
    frame: Frame
    if kind == bot_wire_message_kinds["heartbeatRequest"]:
        frame = HeartbeatRequest("heartbeatRequest", request_id, reader.varint())
    elif kind == bot_wire_message_kinds["heartbeatResponse"]:
        frame = HeartbeatResponse("heartbeatResponse", request_id)
    elif kind == bot_wire_message_kinds["decisionRequest"]:
        deadline_at = reader.varint()
        decision_value = reader.varint()
        common_reader = _Reader(reader.read(reader.varint()))
        events = tuple(_decode_event(common_reader) for _ in range(common_reader.varint()))
        common_reader.finish()
        decision_kind: Literal["submitBid", "selectInfoToReveal"]
        if decision_value == bot_wire_decision_kinds["submitBid"]:
            decision_kind = "submitBid"
        elif decision_value == bot_wire_decision_kinds["selectInfoToReveal"]:
            decision_kind = "selectInfoToReveal"
        else:
            raise ValueError("unknown decision kind")
        seat = reader.varint() - 1
        hand = tuple(reader.varint() for _ in range(reader.varint()))
        frame = DecisionRequest(
            "decisionRequest",
            request_id,
            deadline_at,
            decision_kind,
            events,
            seat,
            hand,
        )
    elif kind == bot_wire_message_kinds["decisionResponse"]:
        action_value = reader.varint()
        if action_value == bot_wire_response_action_kinds["pass"]:
            frame = DecisionResponse("decisionResponse", request_id, "pass")
        elif action_value == bot_wire_response_action_kinds["submitBid"]:
            frame = DecisionResponse("decisionResponse", request_id, "submitBid", reader.varint())
        elif action_value == bot_wire_response_action_kinds["selectInfoToReveal"]:
            frame = DecisionResponse(
                "decisionResponse",
                request_id,
                "selectInfoToReveal",
                reader.varint(),
            )
        else:
            raise ValueError("unknown response action kind")
    else:
        raise ValueError("unknown bot wire message kind")
    reader.finish()
    return frame
