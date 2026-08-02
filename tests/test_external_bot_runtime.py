from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest

from pocketrocks import ActionId, BotDecision, PocketRocksBot, Suit
from pocketrocks.internal.bot_wire_v2 import DecisionRequest, DecisionResponse
from pocketrocks.testing import FakeTransport, decode_frames, heartbeat_bytes, scenario
from pocketrocks.types import DecisionContext, RuntimeEvent, decisionKind


class RecordingBot(PocketRocksBot):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
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
    decision_kind: decisionKind = "submitBid",
) -> bytes:
    # Fixture defaults (3 players, one open Auction1, bot at seat 0) via the
    # shipped test kit — the same narration bot authors use.
    return (
        scenario(players=3, starting_cash=20, initial_tiebreak_seat=1)
        .turn(ActionId.AUCTION1, resources=(Suit.BRICK, Suit.WOOD))
        .deciding(
            seat=0,
            hand=[Suit.BRICK, Suit.BRICK, Suit.ORE],
            kind=decision_kind,
            request_id=request_id,
        )
        .to_bytes(deadline_at=deadline_at)
    )


def test_vendored_bot_wire_matches_golden_fixture() -> None:
    from pocketrocks.internal.bot_wire_v2 import reconstruct_decision_context

    fixture_path = Path(__file__).parent / "fixtures" / "bot_wire_v2.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf8"))
    request_bytes = bytes.fromhex(fixture["decisionRequestHex"])

    frame = decode_frames([request_bytes])[0]
    assert isinstance(frame, DecisionRequest)
    context = reconstruct_decision_context(frame)

    assert request_bytes.hex() == fixture["decisionRequestHex"]
    assert frame.kind == "decisionRequest"
    assert context.cash_by_seat == (16, 20, 20)
    assert context.legal_max_amount == 26


@pytest.mark.asyncio
async def test_runtime_connects_handles_heartbeat_and_submits_decision() -> None:
    transport = FakeTransport(
        [
            heartbeat_bytes("11111111-1111-1111-1111-111111111111"),
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

    sent_frames = decode_frames(transport.sent_messages)
    assert transport.connected_url == (
        "ws://example.test/api/bots/connect?botId=bot_1234&protocolVersion=2&capacity=1"
    )
    assert transport.connected_headers == {"Authorization": "ApiKey test-key"}
    assert [frame.kind for frame in sent_frames] == ["heartbeatResponse", "decisionResponse"]
    decision_response = sent_frames[1]
    assert isinstance(decision_response, DecisionResponse)
    assert decision_response.action_kind == "submitBid"
    assert decision_response.value == 20
    assert bot.contexts[0].bot_seat == 0
    assert bot.contexts[0].current_hand_suit_ids == (1, 1, 3)


class ScriptedConnectTransport:
    """Transport whose connect() follows a scripted list of outcomes.

    Each step is either an Exception to raise on connect, or a list of incoming
    message byte payloads to serve from a successful connection (the read loop
    ends with EOF once they are exhausted).
    """

    def __init__(self, steps: list[Exception | list[bytes]]) -> None:
        self.steps = list(steps)
        self.connect_count = 0
        self.connected_headers: dict[str, str] | None = None
        self._incoming: list[bytes] = []

    async def connect(self, url: str, headers: dict[str, str]) -> None:
        self.connected_headers = headers
        step = self.steps[min(self.connect_count, len(self.steps) - 1)]
        self.connect_count += 1
        if isinstance(step, Exception):
            raise step
        self._incoming = list(step)

    async def disconnect(self) -> None:
        return None

    async def receive_bytes(self) -> bytes:
        if not self._incoming:
            raise EOFError
        return self._incoming.pop(0)

    async def send_bytes(self, payload: bytes) -> None:
        return None


@pytest.mark.asyncio
async def test_runtime_retries_after_403_then_connects_when_reactivated() -> None:
    from pocketrocks.exceptions import TransportRejected

    # Deactivated (403) on the first attempt, then reactivated: a successful
    # connection with no pending work that promptly closes. The process must
    # stay alive across the rejection and reconnect on its own.
    transport = ScriptedConnectTransport([TransportRejected(403, "inactive"), []])
    bot = RecordingBot(
        api_key="test-key",
        bot_id="bot_1234",
        server_url="ws://example.test",
        reconnect=True,
        reconnect_base_delay_seconds=0.001,
        reconnect_max_delay_seconds=0.002,
        transport=transport,
    )

    # run() would loop forever after the successful reconnect closes (it just
    # keeps reconnecting), so stop it once we have observed a real connection.
    runtime_task = asyncio.create_task(bot.run_async())
    for _ in range(200):
        if any(event.kind == "connected" for event in bot.runtime_events):
            break
        await asyncio.sleep(0.005)
    runtime_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await runtime_task

    kinds = [event.kind for event in bot.runtime_events]
    assert "connectionRejected" in kinds
    rejected = next(e for e in bot.runtime_events if e.kind == "connectionRejected")
    assert rejected.details == {"status_code": 403}
    assert "connected" in kinds  # reconnected after reactivation
    assert any(isinstance(error, TransportRejected) for error in bot.errors)


@pytest.mark.asyncio
async def test_runtime_stops_on_fatal_401_without_infinite_retry() -> None:
    from pocketrocks.exceptions import TransportRejected

    transport = ScriptedConnectTransport([TransportRejected(401, "bad key")])
    bot = RecordingBot(
        api_key="bad-key",
        bot_id="bot_1234",
        server_url="ws://example.test",
        reconnect=True,
        reconnect_base_delay_seconds=0.001,
        reconnect_max_delay_seconds=0.002,
        transport=transport,
    )

    # A fatal status must terminate run() rather than reconnecting forever.
    await asyncio.wait_for(bot.run_async(), timeout=2)

    assert transport.connect_count == 1
    kinds = [event.kind for event in bot.runtime_events]
    assert kinds.count("connectionRejected") == 1
    assert "connected" not in kinds


@pytest.mark.asyncio
async def test_runtime_prefers_raw_callback_when_overridden() -> None:
    class RawBot(RecordingBot):
        async def choose_decision(self, context: DecisionContext) -> BotDecision:
            raise AssertionError("high-level callback should not be used")

        async def choose_raw_decision(self, frame: object, context: DecisionContext) -> BotDecision:
            self.contexts.append(context)
            assert isinstance(frame, DecisionRequest)
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

    sent_frames = decode_frames(transport.sent_messages)
    assert [frame.kind for frame in sent_frames] == ["decisionResponse"]
    decision_response = sent_frames[0]
    assert isinstance(decision_response, DecisionResponse)
    assert decision_response.action_kind == "pass"


@pytest.mark.asyncio
async def test_runtime_drops_overdue_requests_and_reports_overload() -> None:
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

    sent_frames = decode_frames(transport.sent_messages)
    dropped_events = [event for event in bot.runtime_events if event.kind == "requestDropped"]

    assert [frame.kind for frame in sent_frames] == ["decisionResponse"]
    assert len(dropped_events) == 2
    assert {event.details["reason"] for event in dropped_events} == {
        "deadline_expired",
        "queue_full",
    }


@pytest.mark.asyncio
async def test_runtime_contains_callback_errors_and_keeps_processing() -> None:
    class FlakyBot(RecordingBot):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
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

    sent_frames = decode_frames(transport.sent_messages)

    assert [frame.kind for frame in sent_frames] == ["decisionResponse"]
    decision_response = sent_frames[0]
    assert isinstance(decision_response, DecisionResponse)
    assert decision_response.action_kind == "pass"
    assert len(bot.errors) == 1


class FixedDecisionBot(RecordingBot):
    """Returns one scripted decision regardless of context."""

    def __init__(self, decision: BotDecision, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._decision = decision

    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        self.contexts.append(context)
        return self._decision


async def _run_with_decision(decision: BotDecision, *, debug: bool = False):
    transport = FakeTransport(
        [
            _fixture_request_bytes(
                request_id="33333333-3333-3333-3333-333333333333",
                deadline_at=_now_ms(5_000),
            )
        ]
    )
    bot = FixedDecisionBot(
        decision,
        api_key="test-key",
        bot_id="bot_1234",
        server_url="ws://example.test",
        reconnect=False,
        debug=debug,
        transport=transport,
    )
    await bot.run_async()
    return bot, decode_frames(transport.sent_messages)


def _rejections(bot: RecordingBot) -> list[RuntimeEvent]:
    return [e for e in bot.runtime_events if e.kind == "decisionRejected"]


async def test_overbid_is_forwarded_to_the_server_which_clamps_it():
    # legal_max is 20 in the fixture; the server clamps, so swallowing would be worse.
    bot, sent = await _run_with_decision(BotDecision.submit_bid(999))

    decision_frames = [f for f in sent if f.kind == "decisionResponse"]
    assert len(decision_frames) == 1
    assert decision_frames[0].value == 999  # raw value, unclamped by the SDK

    events = _rejections(bot)
    assert len(events) == 1
    assert events[0].details["applied"] == "forwarded"
    assert events[0].details["action_kind"] == "submitBid"
    assert events[0].details["value"] == 999
    assert "legal maximum" in events[0].details["detail"]
    assert len(bot.errors) == 1
    # Forwarded still sends a frame, so the request completes like any other.
    assert [e.kind for e in bot.runtime_events].count("requestCompleted") == 1


async def test_negative_bid_is_corrected_to_zero_and_sent():
    # The wire cannot carry a negative varint, so -5 is coerced to 0 and sent.
    # 0 is the same bid the server would have computed, and sending it also sets
    # submitted=true so the auction resolves without waiting out the bid window.
    bot, sent = await _run_with_decision(BotDecision.submit_bid(-5))

    assert [f.value for f in sent if f.kind == "decisionResponse"] == [0]
    details = _rejections(bot)[0].details
    assert details["applied"] == "corrected"
    assert details["value"] == -5           # what the bot returned
    assert details["corrected_value"] == 0  # what actually went on the wire


async def test_mismatched_response_kind_is_discarded():
    bot, sent = await _run_with_decision(BotDecision.select_info_to_reveal(0))

    assert [f for f in sent if f.kind == "decisionResponse"] == []
    events = _rejections(bot)
    assert len(events) == 1
    assert events[0].details["applied"] == "discarded"
    assert len(bot.errors) == 1
    assert [e.kind for e in bot.runtime_events].count("requestCompleted") == 0


async def test_rejection_does_not_emit_request_failed():
    # requestFailed must regain its real meaning: something threw.
    bot, _sent = await _run_with_decision(BotDecision.select_info_to_reveal(0))
    assert [e.kind for e in bot.runtime_events].count("requestFailed") == 0


async def test_legal_decision_emits_no_rejection():
    bot, sent = await _run_with_decision(BotDecision.submit_bid(20))

    assert [f.value for f in sent if f.kind == "decisionResponse"] == [20]
    assert _rejections(bot) == []
    assert [e.kind for e in bot.runtime_events].count("requestCompleted") == 1


async def test_debug_off_omits_context_and_debug_on_includes_it():
    off, _ = await _run_with_decision(BotDecision.submit_bid(999), debug=False)
    assert "context" not in _rejections(off)[0].details

    on, _ = await _run_with_decision(BotDecision.submit_bid(999), debug=True)
    assert isinstance(_rejections(on)[0].details["context"], DecisionContext)


async def test_on_error_raising_still_sends_forwarded_frame_and_completes():
    # report_rejection runs after the frame is sent and must be best-effort: a
    # bot's on_error blowing up must not turn a successfully-dispatched forwarded
    # decision into a requestFailed / swallowed response.
    class ErrorRaisingBot(FixedDecisionBot):
        async def on_error(self, error: Exception) -> None:
            await super().on_error(error)
            raise RuntimeError("on_error blew up")

    transport = FakeTransport(
        [
            _fixture_request_bytes(
                request_id="55555555-5555-5555-5555-555555555555",
                deadline_at=_now_ms(5_000),
            )
        ]
    )
    bot = ErrorRaisingBot(
        BotDecision.submit_bid(999),
        api_key="test-key",
        bot_id="bot_1234",
        server_url="ws://example.test",
        reconnect=False,
        transport=transport,
    )
    await bot.run_async()

    decision_frames = [
        f for f in decode_frames(transport.sent_messages) if f.kind == "decisionResponse"
    ]
    assert len(decision_frames) == 1
    assert decision_frames[0].value == 999

    kinds = [e.kind for e in bot.runtime_events]
    assert kinds.count("requestCompleted") == 1
    assert kinds.count("requestFailed") == 0
    assert len(bot.errors) == 1  # on_error was in fact called, before it raised


async def test_on_runtime_event_raising_still_calls_on_error_and_sends_frame():
    # A raising on_runtime_event must not prevent on_error from running, and must
    # not prevent the frame that was already sent from counting as completed.
    class EventRaisingBot(FixedDecisionBot):
        async def on_runtime_event(self, event: RuntimeEvent) -> None:
            await super().on_runtime_event(event)
            if event.kind == "decisionRejected":
                raise RuntimeError("on_runtime_event blew up")

    transport = FakeTransport(
        [
            _fixture_request_bytes(
                request_id="66666666-6666-6666-6666-666666666666",
                deadline_at=_now_ms(5_000),
            )
        ]
    )
    bot = EventRaisingBot(
        BotDecision.submit_bid(999),
        api_key="test-key",
        bot_id="bot_1234",
        server_url="ws://example.test",
        reconnect=False,
        transport=transport,
    )
    await bot.run_async()

    decision_frames = [
        f for f in decode_frames(transport.sent_messages) if f.kind == "decisionResponse"
    ]
    assert len(decision_frames) == 1
    assert decision_frames[0].value == 999

    assert len(bot.errors) == 1  # on_error still ran despite the earlier hook raising
    kinds = [e.kind for e in bot.runtime_events]
    assert kinds.count("requestCompleted") == 1
    assert kinds.count("requestFailed") == 0


async def test_a_raised_exception_still_reports_request_failed_and_sends_nothing():
    class ExplodingBot(RecordingBot):
        async def choose_decision(self, context: DecisionContext) -> BotDecision:
            raise RuntimeError("bot blew up")

    transport = FakeTransport(
        [
            _fixture_request_bytes(
                request_id="44444444-4444-4444-4444-444444444444",
                deadline_at=_now_ms(5_000),
            )
        ]
    )
    bot = ExplodingBot(
        api_key="test-key",
        bot_id="bot_1234",
        server_url="ws://example.test",
        reconnect=False,
        transport=transport,
    )
    await bot.run_async()

    kinds = [e.kind for e in bot.runtime_events]
    assert kinds.count("requestFailed") == 1
    assert kinds.count("decisionRejected") == 0
    assert [f for f in decode_frames(transport.sent_messages) if f.kind == "decisionResponse"] == []
