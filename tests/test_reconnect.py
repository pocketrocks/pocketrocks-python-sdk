from __future__ import annotations

import asyncio

import pytest

from pocketrocks import BotDecision, DecisionContext, PocketRocksBot
from pocketrocks.config import BotConfig
from pocketrocks.exceptions import TransportError, TransportRejected
from pocketrocks.reconnect import ReconnectPolicy


def _config(**overrides: object) -> BotConfig:
    base: dict[str, object] = {
        "api_key": "k",
        "bot_id": "b",
        "reconnect_base_delay_seconds": 0.5,
        "reconnect_max_delay_seconds": 8.0,
        "rejected_reconnect_max_delay_seconds": 60.0,
    }
    base.update(overrides)
    return BotConfig.from_env(**base)


def _identity(delay: float) -> float:
    return delay


def test_transient_schedule_doubles_and_clamps_to_the_fast_ceiling() -> None:
    policy = ReconnectPolicy(_config(), jitter=_identity)
    delays = [policy.next_delay("transient") for _ in range(6)]
    # 0.5 -> 1 -> 2 -> 4 -> 8, then pinned at the 8s ceiling.
    assert delays == [0.5, 1.0, 2.0, 4.0, 8.0, 8.0]


def test_rejected_schedule_climbs_past_the_fast_ceiling_to_the_slow_one() -> None:
    policy = ReconnectPolicy(_config(), jitter=_identity)
    delays = [policy.next_delay("rejected") for _ in range(9)]
    # A deactivated bot climbs past 8s toward the 60s rejected ceiling.
    assert delays == [0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]


def test_transient_blip_does_not_inherit_a_carried_over_slow_ceiling() -> None:
    policy = ReconnectPolicy(_config(), jitter=_identity)
    for _ in range(6):
        policy.next_delay("rejected")  # climb well past 8s
    # One transient failure must clamp straight back down to the fast ceiling.
    assert policy.next_delay("transient") == 8.0


def test_reset_returns_to_the_base_delay() -> None:
    policy = ReconnectPolicy(_config(), jitter=_identity)
    for _ in range(4):
        policy.next_delay("transient")
    policy.reset()
    assert policy.next_delay("transient") == 0.5


def test_jitter_is_applied_to_the_returned_delay() -> None:
    policy = ReconnectPolicy(_config(), jitter=lambda delay: delay * 10)
    assert policy.next_delay("transient") == 5.0  # 0.5 base * 10


# --- Outcome mapping: run() feeds the right outcome per failure type ----------


class _MinimalBot(PocketRocksBot):
    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        return BotDecision.pass_turn()


class _RecordingPolicy:
    """Duck-typed stand-in for ReconnectPolicy that records the outcomes run()
    asks for and never actually delays."""

    def __init__(self) -> None:
        self.outcomes: list[str] = []
        self.resets = 0

    def reset(self) -> None:
        self.resets += 1

    def next_delay(self, outcome: str) -> float:
        self.outcomes.append(outcome)
        return 0.0


class _FailingConnectTransport:
    """connect() raises a scripted error per attempt (last repeats)."""

    def __init__(self, errors: list[Exception]) -> None:
        self._errors = errors
        self.attempt = 0

    async def connect(self, url: str, headers: dict[str, str]) -> None:
        error = self._errors[min(self.attempt, len(self._errors) - 1)]
        self.attempt += 1
        raise error

    async def disconnect(self) -> None:
        return None

    async def receive_bytes(self) -> bytes:
        raise EOFError

    async def send_bytes(self, payload: bytes) -> None:
        return None


@pytest.mark.asyncio
async def test_run_feeds_rejected_for_403_and_transient_for_network_error() -> None:
    from pocketrocks.runtime import PocketRocksRuntime

    bot = _MinimalBot(
        api_key="k",
        bot_id="b",
        server_url="ws://example.test",
        reconnect=True,
    )
    transport = _FailingConnectTransport(
        [TransportRejected(403, "inactive"), TransportError("connection refused")]
    )
    policy = _RecordingPolicy()
    runtime = PocketRocksRuntime(
        bot=bot,
        config=bot.config,
        transport=transport,
        policy=policy,  # type: ignore[arg-type]  # _RecordingPolicy is a deliberate duck-typed double, not a ReconnectPolicy subclass
    )

    task = asyncio.create_task(runtime.run())
    for _ in range(200):
        if len(policy.outcomes) >= 2:
            break
        await asyncio.sleep(0)
    runtime.stop_requested = True
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # First attempt was a retryable 403 -> rejected schedule; second a network
    # blip -> transient schedule.
    assert policy.outcomes[0] == "rejected"
    assert policy.outcomes[1] == "transient"
