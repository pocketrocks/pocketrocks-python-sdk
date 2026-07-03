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
    assert transport.connected_headers == {"Authorization": "ApiKey test-key"}
    assert [frame.kind for frame in sent_frames] == ["heartbeatResponse", "decisionResponse"]
    assert sent_frames[1].action_kind == "submitBid"
    assert sent_frames[1].value == 20
    assert bot.contexts[0].bot_seat == 0
    assert bot.contexts[0].current_hand_suit_ids == (1, 1, 3)


class ScriptedConnectTransport:
    """Transport whose connect() follows a scripted list of outcomes.

    Each step is either an Exception to raise on connect, or a list of incoming
    message byte payloads to serve from a successful connection (the read loop
    ends with EOF once they are exhausted).
    """

    def __init__(self, steps: list[object]) -> None:
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
        self._incoming = list(step)  # type: ignore[arg-type]

    async def disconnect(self) -> None:
        return None

    async def receive_bytes(self) -> bytes:
        if not self._incoming:
            raise EOFError
        return self._incoming.pop(0)

    async def send_bytes(self, payload: bytes) -> None:
        return None


@pytest.mark.asyncio
async def test_runtime_retries_after_403_then_connects_when_reactivated():
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
async def test_runtime_stops_on_fatal_401_without_infinite_retry():
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


async def _capture_reconnect_sleeps(monkeypatch, error: Exception, *, sample: int) -> list[float]:
    """Run a bot whose connect always fails with ``error`` and record the
    sleep values the runtime requests, without actually waiting."""
    transport = ScriptedConnectTransport([error])
    bot = RecordingBot(
        api_key="test-key",
        bot_id="bot_1234",
        server_url="ws://example.test",
        reconnect=True,
        reconnect_base_delay_seconds=0.5,
        reconnect_max_delay_seconds=8.0,
        rejected_reconnect_max_delay_seconds=60.0,
        transport=transport,
    )
    sleeps: list[float] = []
    runtime_holder: dict[str, object] = {}

    real_run_async = bot.run_async

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) >= sample:
            runtime = runtime_holder["runtime"]
            runtime.stop_requested = True  # type: ignore[attr-defined]

    # Capture the runtime instance the bot creates so we can stop the loop.
    from pocketrocks.runtime import PocketRocksRuntime

    original_init = PocketRocksRuntime.__init__

    def capturing_init(self, **kwargs):  # type: ignore[no-untyped-def]
        original_init(self, **kwargs)
        runtime_holder["runtime"] = self

    monkeypatch.setattr(PocketRocksRuntime, "__init__", capturing_init)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    await asyncio.wait_for(real_run_async(), timeout=2)
    return sleeps


@pytest.mark.asyncio
async def test_deactivated_403_backs_off_to_the_slow_ceiling(monkeypatch):
    from pocketrocks.exceptions import TransportRejected

    sleeps = await _capture_reconnect_sleeps(
        monkeypatch, TransportRejected(403, "inactive"), sample=15
    )

    # A deactivated bot must climb past the transient 8s ceiling toward the
    # 60s rejected ceiling (jitter keeps it within ~15%).
    assert max(sleeps) > 8.0 * 1.15
    assert max(sleeps) <= 60.0 * 1.16


@pytest.mark.asyncio
async def test_transient_error_stays_on_the_fast_ceiling(monkeypatch):
    from pocketrocks.exceptions import TransportError

    sleeps = await _capture_reconnect_sleeps(
        monkeypatch, TransportError("connection refused"), sample=15
    )

    # Transient failures must keep recovering fast: never exceed the 8s ceiling
    # (plus jitter), so an active bot is not stuck offline after a blip.
    assert max(sleeps) <= 8.0 * 1.16


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
