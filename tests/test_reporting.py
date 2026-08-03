from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

import pytest

from pocketrocks import BotDecision, Suit
from pocketrocks import _reporting as reporting
from pocketrocks._reporting import PendingRejection, RejectionReporter
from pocketrocks.exceptions import InvalidBotDecision
from pocketrocks.testing import scenario
from pocketrocks.types import RuntimeEvent


def _pending(bot: object, request_id: str) -> PendingRejection:
    context = (
        scenario(players=2, starting_cash=10)
        .deciding(seat=0, hand=[Suit.BRICK], kind="submitBid")
        .to_context()
    )
    bid = BotDecision.submit_bid(11)
    return PendingRejection(
        bot=bot,  # type: ignore[arg-type]
        context=replace(context, request_id=request_id),
        decision=bid,
        error=InvalidBotDecision("bid exceeds legal maximum"),
        applied="forwarded",
        debug=False,
        outgoing=bid,
    )


class _Bot:
    def __init__(self, *, cancel_on_event: bool = False) -> None:
        self._cancel = cancel_on_event
        self.seen: list[str] = []
        self.errors: list[Exception] = []

    async def on_runtime_event(self, event: RuntimeEvent) -> None:
        if self._cancel:
            # As if the hook awaited a task cancelled elsewhere: CancelledError is
            # a BaseException, so it slips past every `except Exception` guard.
            raise asyncio.CancelledError
        self.seen.append(str(event.details["request_id"]))

    async def on_error(self, error: Exception) -> None:
        self.errors.append(error)


async def test_a_hook_local_cancellation_does_not_kill_the_reporter() -> None:
    # If a hook's CancelledError terminated the shared worker, `_queue` would stay
    # non-None and every later rejection would enqueue into an orphaned queue and
    # be silently lost. The worker must survive it like any other hook failure.
    reporter = RejectionReporter(logging.getLogger("test"))
    hanging = _Bot(cancel_on_event=True)
    healthy = _Bot()

    await reporter.hand_off(_pending(hanging, "first"))
    await reporter.hand_off(_pending(healthy, "second"))
    await reporter.drain()

    assert healthy.seen == ["second"]


async def test_drain_still_cancels_a_hook_that_never_returns() -> None:
    # The fix must not defeat drain: a genuinely hanging hook is still bounded and
    # cancelled, so a caller shutting down is never held hostage.
    started = asyncio.Event()

    class Hanger:
        async def on_runtime_event(self, event: RuntimeEvent) -> None:
            started.set()
            await asyncio.Event().wait()  # never returns

        async def on_error(self, error: Exception) -> None:
            return None

    reporter = RejectionReporter(logging.getLogger("test"))
    await reporter.hand_off(_pending(Hanger(), "stuck"))
    await started.wait()

    await asyncio.wait_for(reporter.drain(timeout_s=0.05), timeout=2.0)


async def test_a_stuck_hook_does_not_grow_the_backlog_without_bound(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # With a hook that never returns, the worker is wedged on report 0 and every
    # later rejection is buffered. The queue must stay bounded rather than pin an
    # unbounded pile of DecisionContexts and eventually exhaust the process.
    monkeypatch.setattr(reporting, "MAX_QUEUED_REPORTS", 4)
    started = asyncio.Event()

    class Hanger:
        async def on_runtime_event(self, event: RuntimeEvent) -> None:
            started.set()
            await asyncio.Event().wait()  # never returns

        async def on_error(self, error: Exception) -> None:
            return None

    reporter = RejectionReporter(logging.getLogger("test"))
    hanger = Hanger()

    await reporter.hand_off(_pending(hanger, "0"))  # worker takes this and blocks
    await started.wait()

    with caplog.at_level(logging.WARNING):
        for i in range(1, 50):  # flood well past the cap
            await reporter.hand_off(_pending(hanger, str(i)))

    assert reporter._queue is not None
    assert reporter._queue.qsize() <= 4
    assert any("backlog hit its cap" in r.message for r in caplog.records)

    await asyncio.wait_for(reporter.drain(timeout_s=0.05), timeout=2.0)


async def test_drain_delivers_a_full_backlog_once_a_healthy_hook_unblocks(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A burst fills the queue, but the hook is healthy — just momentarily blocked.
    # drain must place its sentinel once the worker frees a slot, deliver the whole
    # backlog, and return promptly. It must NOT drop the sentinel and then wait out
    # the full timeout with a misleading stuck-hook warning.
    monkeypatch.setattr(reporting, "MAX_QUEUED_REPORTS", 4)
    gate = asyncio.Event()
    seen: list[str] = []

    class Gated:
        async def on_runtime_event(self, event: RuntimeEvent) -> None:
            await gate.wait()  # blocked only until the test releases it
            seen.append(str(event.details["request_id"]))

        async def on_error(self, error: Exception) -> None:
            return None

    reporter = RejectionReporter(logging.getLogger("test"))
    bot = Gated()

    # Worker takes "0" and blocks on the gate; "1".."4" fill the queue, "5" is
    # dropped over the cap. Queue is now full at drain time.
    for i in range(6):
        await reporter.hand_off(_pending(bot, str(i)))
    assert reporter._queue is not None
    assert reporter._queue.qsize() == 4

    gate.set()  # healthy again — the whole backlog can now flow
    with caplog.at_level(logging.WARNING):
        await asyncio.wait_for(reporter.drain(timeout_s=0.5), timeout=2.0)

    assert seen == ["0", "1", "2", "3", "4"]  # every buffered report delivered
    assert not any("did not return within" in r.message for r in caplog.records)
