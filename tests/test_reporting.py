from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

from pocketrocks import BotDecision, Suit
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
