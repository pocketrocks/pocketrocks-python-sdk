from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from pocketrocks import ActionId, BotDecision, PocketRocksBot, Suit
from pocketrocks.testing import FakeTransport, decode_frames, heartbeat_bytes, scenario
from pocketrocks.types import DecisionContext, RuntimeEvent


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


def test_vendored_bot_wire_matches_golden_fixture():
    from pocketrocks.internal.bot_wire_v2 import reconstruct_decision_context

    fixture_path = Path(__file__).parent / "fixtures" / "bot_wire_v2.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf8"))
    request_bytes = bytes.fromhex(fixture["decisionRequestHex"])

    frame = decode_frames([request_bytes])[0]
    context = reconstruct_decision_context(frame)

    assert request_bytes.hex() == fixture["decisionRequestHex"]
    assert frame.kind == "decisionRequest"
    assert context.cash_by_seat == (16, 20, 20)
    assert context.legal_max_amount == 26


@pytest.mark.asyncio
async def test_runtime_connects_handles_heartbeat_and_submits_decision():
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

    sent_frames = decode_frames(transport.sent_messages)
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

    sent_frames = decode_frames(transport.sent_messages)
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

    sent_frames = decode_frames(transport.sent_messages)

    assert [frame.kind for frame in sent_frames] == ["decisionResponse"]
    assert sent_frames[0].action_kind == "pass"
    assert len(bot.errors) == 1
