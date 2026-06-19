from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from pocketrocks import BotDecision, PocketRocksBot
from pocketrocks.types import DecisionContext, RuntimeEvent


class FakeTransport:
    def __init__(self, incoming_messages: list[bytes]) -> None:
        self.incoming_messages = list(incoming_messages)
        self.sent_messages: list[bytes] = []
        self.connected_url: str | None = None
        self.connected_headers: dict[str, str] | None = None
        self.disconnected = False

    async def connect(self, url: str, headers: dict[str, str]) -> None:
        self.connected_url = url
        self.connected_headers = headers

    async def disconnect(self) -> None:
        self.disconnected = True

    async def receive_bytes(self) -> bytes:
        if not self.incoming_messages:
            raise EOFError
        return self.incoming_messages.pop(0)

    async def send_bytes(self, payload: bytes) -> None:
        self.sent_messages.append(payload)


class RecordingBot(PocketRocksBot):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.contexts: list[DecisionContext] = []
        self.runtime_events: list[RuntimeEvent] = []
        self.errors: list[Exception] = []

    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        self.contexts.append(context)
        if context.decision_kind == "submitBid":
            return BotDecision.submit_bid(context.legal_max_amount or 0)
        return BotDecision.select_info_to_reveal(0)

    async def on_runtime_event(self, event: RuntimeEvent) -> None:
        self.runtime_events.append(event)

    async def on_error(self, error: Exception) -> None:
        self.errors.append(error)


def _now_ms(offset_ms: int = 0) -> int:
    return int(time.time() * 1000) + offset_ms


def _fixture_request_bytes(
    *,
    request_id: str,
    deadline_at: int,
    decision_kind: str = "submitBid",
) -> bytes:
    from pocketrocks.internal.bot_wire_v2 import (
        DecisionRequest,
        GameSetupEvent,
        TurnOpenedEvent,
        encode_frame,
    )

    return encode_frame(
        DecisionRequest(
            kind="decisionRequest",
            request_id=request_id,
            deadline_at=deadline_at,
            decision_kind=decision_kind,
            common_events=(
                GameSetupEvent(
                    kind="gameSetup",
                    player_count=3,
                    starting_cash=20,
                    value_chart=(0, 4, 8, 12, 16, 20),
                    initial_tiebreak_seat=1,
                    objective_ids=(1, 2, 3, 4),
                ),
                TurnOpenedEvent(
                    kind="turnOpened",
                    action_id=1,
                    resource_ids=(1, 2),
                ),
            ),
            bot_seat=0,
            current_hand_suit_ids=(1, 1, 3),
        )
    )


def _heartbeat_request_bytes(request_id: str) -> bytes:
    from pocketrocks.internal.bot_wire_v2 import HeartbeatRequest, encode_frame

    return encode_frame(
        HeartbeatRequest(
            kind="heartbeatRequest",
            request_id=request_id,
            deadline_at=_now_ms(5_000),
        )
    )


def _decode_sent_messages(payloads: list[bytes]) -> list[object]:
    from pocketrocks.internal.bot_wire_v2 import decode_frame

    return [decode_frame(payload) for payload in payloads]


def test_vendored_bot_wire_matches_golden_fixture():
    from pocketrocks.internal.bot_wire_v2 import reconstruct_decision_context

    fixture_path = Path(__file__).parent / "fixtures" / "bot_wire_v2.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf8"))
    request_bytes = bytes.fromhex(fixture["decisionRequestHex"])

    frame = _decode_sent_messages([request_bytes])[0]
    context = reconstruct_decision_context(frame)

    assert request_bytes.hex() == fixture["decisionRequestHex"]
    assert frame.kind == "decisionRequest"
    assert context.cash_by_seat == (16, 20, 20)
    assert context.legal_max_amount == 26


@pytest.mark.asyncio
async def test_runtime_connects_handles_heartbeat_and_submits_decision():
    transport = FakeTransport(
        [
            _heartbeat_request_bytes("11111111-1111-1111-1111-111111111111"),
            _fixture_request_bytes(
                request_id="22222222-2222-2222-2222-222222222222",
                deadline_at=_now_ms(5_000),
            ),
        ]
    )
    bot = RecordingBot(
        api_key="test-key",
        bot_id="bot_1234",
        server_url="ws://example.test",
        reconnect=False,
        transport=transport,
    )

    await bot.run_async()

    sent_frames = _decode_sent_messages(transport.sent_messages)
    assert transport.connected_url == (
        "ws://example.test/api/bots/connect?botId=bot_1234&protocolVersion=2&capacity=1"
    )
    assert transport.connected_headers == {"Authorization": "Bearer test-key"}
    assert [frame.kind for frame in sent_frames] == ["heartbeatResponse", "decisionResponse"]
    assert sent_frames[1].action_kind == "submitBid"
    assert sent_frames[1].value == 20
    assert bot.contexts[0].bot_seat == 0
    assert bot.contexts[0].current_hand_suit_ids == (1, 1, 3)


@pytest.mark.asyncio
async def test_runtime_prefers_raw_callback_when_overridden():
    class RawBot(RecordingBot):
        async def choose_decision(self, context: DecisionContext) -> BotDecision:
            raise AssertionError("high-level callback should not be used")

        async def choose_raw_decision(self, frame, context: DecisionContext) -> BotDecision:
            self.contexts.append(context)
            assert frame.kind == "decisionRequest"
            return BotDecision.pass_turn()

    transport = FakeTransport(
        [
            _fixture_request_bytes(
                request_id="33333333-3333-3333-3333-333333333333",
                deadline_at=_now_ms(5_000),
            )
        ]
    )
    bot = RawBot(
        api_key="test-key",
        bot_id="bot_1234",
        server_url="ws://example.test",
        reconnect=False,
        transport=transport,
    )

    await bot.run_async()

    sent_frames = _decode_sent_messages(transport.sent_messages)
    assert [frame.kind for frame in sent_frames] == ["decisionResponse"]
    assert sent_frames[0].action_kind == "pass"


@pytest.mark.asyncio
async def test_runtime_drops_overdue_requests_and_reports_overload():
    class SlowBot(RecordingBot):
        async def choose_decision(self, context: DecisionContext) -> BotDecision:
            await asyncio.sleep(0.05)
            return await super().choose_decision(context)

    transport = FakeTransport(
        [
            _fixture_request_bytes(
                request_id="44444444-4444-4444-4444-444444444444",
                deadline_at=_now_ms(-100),
            ),
            _fixture_request_bytes(
                request_id="55555555-5555-5555-5555-555555555555",
                deadline_at=_now_ms(250),
            ),
            _fixture_request_bytes(
                request_id="66666666-6666-6666-6666-666666666666",
                deadline_at=_now_ms(250),
            ),
        ]
    )
    bot = SlowBot(
        api_key="test-key",
        bot_id="bot_1234",
        server_url="ws://example.test",
        reconnect=False,
        transport=transport,
        max_in_flight_decisions=1,
        max_queue_size=1,
        min_remaining_deadline_ms_to_start=10,
    )

    await bot.run_async()

    sent_frames = _decode_sent_messages(transport.sent_messages)
    dropped_events = [event for event in bot.runtime_events if event.kind == "requestDropped"]

    assert [frame.kind for frame in sent_frames] == ["decisionResponse"]
    assert len(dropped_events) == 2
    assert {event.details["reason"] for event in dropped_events} == {
        "deadline_expired",
        "queue_full",
    }


@pytest.mark.asyncio
async def test_runtime_contains_callback_errors_and_keeps_processing():
    class FlakyBot(RecordingBot):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.calls = 0

        async def choose_decision(self, context: DecisionContext) -> BotDecision:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("boom")
            return BotDecision.pass_turn()

    transport = FakeTransport(
        [
            _fixture_request_bytes(
                request_id="77777777-7777-7777-7777-777777777777",
                deadline_at=_now_ms(5_000),
            ),
            _fixture_request_bytes(
                request_id="88888888-8888-8888-8888-888888888888",
                deadline_at=_now_ms(5_000),
            ),
        ]
    )
    bot = FlakyBot(
        api_key="test-key",
        bot_id="bot_1234",
        server_url="ws://example.test",
        reconnect=False,
        transport=transport,
    )

    await bot.run_async()

    sent_frames = _decode_sent_messages(transport.sent_messages)

    assert [frame.kind for frame in sent_frames] == ["decisionResponse"]
    assert sent_frames[0].action_kind == "pass"
    assert len(bot.errors) == 1
