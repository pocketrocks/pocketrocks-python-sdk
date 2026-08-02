"""One reporting path for a rejected decision, shared by the live runtime and the sim.

Both surfaces call :func:`report_rejection` with the output of
``pocketrocks.types.classify``. Keeping the log line, the event payload, and the
``on_error`` call in a single place is what makes sim and live observably
identical for the same bad decision — the divergence this module exists to
prevent is the one that shipped for months without anyone noticing.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from pocketrocks.exceptions import InvalidBotDecision
from pocketrocks.types import BotDecision, DecisionContext, RuntimeEvent, decisionFate

# How long a caller shutting down waits for reports still in flight before the
# reporter is cancelled. See ``RejectionReporter`` for why the wait is bounded at
# all; the value matches the update check's ``_JOIN_TIMEOUT_S`` shutdown wait. One
# default for every surface — pass ``drain(timeout_s=...)`` to override it.
DEFAULT_DRAIN_TIMEOUT_S = 1.5


class _RejectionSink(Protocol):
    async def on_runtime_event(self, event: RuntimeEvent) -> None: ...

    async def on_error(self, error: Exception) -> None: ...


@dataclass(frozen=True)
class PendingRejection:
    """One rejection captured for delivery after the caller's critical section.

    Everything :func:`report_rejection` needs, snapshotted at the moment the
    decision was classified, so the report is faithful to that moment however
    much later it is actually delivered.
    """

    bot: _RejectionSink
    context: DecisionContext
    decision: BotDecision
    error: InvalidBotDecision
    applied: decisionFate
    debug: bool
    outgoing: BotDecision


class RejectionReporter:
    """Delivers rejection reports off the caller's critical path, one at a time.

    Both surfaces used to ``await report_rejection`` inline, which put user
    telemetry hooks on their liveness path: a hook that never returns hung the
    sim's turn loop, and in the live runtime it permanently occupied the worker
    that was about to take the next queued request. Ordering the send/apply
    before the report only protected *that* decision, not the ones behind it.

    Callers now ``hand_off`` and move on. One shared worker per reporter rather
    than a task per rejection is deliberate: a bot's hooks are never re-entered
    concurrently and still see rejections in the order they happened, which is
    what makes the sim's and the live runtime's reports comparable at all. The
    cost is head-of-line blocking — a hook that hangs also holds up the reports
    behind it — which is the right trade for best-effort telemetry, since a bot
    whose hook hangs once will hang on every later call too.

    ``drain`` is the shutdown half: reports still in flight get a bounded chance
    to finish, then the worker is cancelled. Waiting unconditionally would put
    the hang back, one layer out; abandoning the task would leak a "Task was
    destroyed but it is pending" warning with no explanation of why. The bound
    mirrors the update check's ``_JOIN_TIMEOUT_S`` shutdown wait. A reporter is
    reusable after draining, so a reconnecting runtime gets a fresh worker.
    """

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        # Created inside the running loop on the first rejection: a reporter is
        # built synchronously by its owner, so it cannot bind a loop up front.
        self._queue: asyncio.Queue[PendingRejection | None] | None = None
        self._worker: asyncio.Task[None] | None = None

    async def hand_off(self, *pending: PendingRejection) -> None:
        """Queue rejections and give the worker exactly one scheduling slot.

        Nothing here waits on a hook, so a hook that blocks forever cannot stall
        the caller. The single ``sleep(0)`` lets a well-behaved hook keep pace
        with the caller instead of everything landing at ``drain`` time, and it
        resumes on the next loop iteration whatever the hook does.
        """
        if not pending:
            return
        queue = self._ensure_worker()
        for item in pending:
            queue.put_nowait(item)
        await asyncio.sleep(0)

    def _ensure_worker(self) -> asyncio.Queue[PendingRejection | None]:
        if self._queue is None:
            self._queue = asyncio.Queue()
            self._worker = asyncio.create_task(
                self._run(self._queue), name="pocketrocks-rejection-reporter"
            )
        return self._queue

    async def _run(self, queue: asyncio.Queue[PendingRejection | None]) -> None:
        while True:
            pending = await queue.get()
            if pending is None:  # sentinel: everything queued before it is reported
                return
            try:
                await report_rejection(
                    pending.bot,
                    self._logger,
                    context=pending.context,
                    decision=pending.decision,
                    error=pending.error,
                    applied=pending.applied,
                    debug=pending.debug,
                    outgoing=pending.outgoing,
                )
            except Exception as error:  # noqa: BLE001 — telemetry never kills the worker
                self._logger.warning("reporting a rejected decision failed: %s", error)

    async def drain(self, *, timeout_s: float | None = None) -> None:
        """Let in-flight reports finish, then cancel the worker.

        ``timeout_s`` defaults to :data:`DEFAULT_DRAIN_TIMEOUT_S`, read at call time
        so a surface can override it per drain without shadowing the shared default.
        """
        timeout_s = DEFAULT_DRAIN_TIMEOUT_S if timeout_s is None else timeout_s
        queue, worker = self._queue, self._worker
        self._queue, self._worker = None, None
        if queue is None or worker is None:
            return
        queue.put_nowait(None)
        try:
            await asyncio.wait({worker}, timeout=timeout_s)
        finally:
            if not worker.done():
                self._logger.warning(
                    "dropping %d unreported decision rejection(s): a reporting hook did "
                    "not return within %s seconds",
                    queue.qsize(),
                    timeout_s,
                )
                worker.cancel()
            # Bounded by the hook contract, not by us: a hook must let cancellation
            # through. One that swallows CancelledError would hang any asyncio
            # teardown of the task anyway (asyncio.run's _cancel_all_tasks included),
            # so bounding this await is impossible and is not attempted.
            with contextlib.suppress(asyncio.CancelledError):
                await worker


async def report_rejection(
    bot: _RejectionSink,
    logger: logging.Logger,
    *,
    context: DecisionContext,
    decision: BotDecision,
    error: InvalidBotDecision,
    applied: decisionFate,
    debug: bool,
    outgoing: BotDecision,
) -> None:
    """Log, emit ``decisionRejected``, and notify the bot that it played illegally.

    ``applied`` is the decision's fate in surface-neutral terms — ``"discarded"``
    when the bot's value never reaches the rules, ``"forwarded"`` when it does and
    the engine clamps it, or ``"corrected"`` when the value could not be encoded at
    all. ``outgoing`` is what ``classify`` returned alongside ``applied`` — for
    every fate except ``"corrected"`` it is ``decision`` itself, so deriving the
    ``corrected_value`` detail from ``applied == "corrected"`` here (rather than
    at each call site) is what keeps the sim and the live runtime from having to
    duplicate that condition. Naming the outcome rather than the mechanism is
    what lets the two surfaces emit byte-identical events for the same input.

    Reporting is best-effort. Both callbacks below are user-defined, and by the
    time this runs the live runtime has already sent (or the sim has already
    committed) the dispatch outcome — a slow or raising hook must not be able to
    retroactively undo that. Each callback is wrapped individually and any
    exception is logged and swallowed rather than propagated, so the reporter
    throwing never escapes into the caller's exception handling.
    """
    details: dict[str, Any] = {
        "request_id": context.request_id,
        "decision_kind": context.decision_kind,
        "action_kind": decision.action_kind,
        "value": decision.value,
        "detail": str(error),
        "applied": applied,
    }
    if applied == "corrected":
        details["corrected_value"] = outgoing.value
    if debug:
        details["context"] = context
    logger.warning(
        "decision %s rejected (%s %s, %s%s): %s",
        context.request_id,
        decision.action_kind,
        decision.value,
        applied,
        f" -> {outgoing.value}" if applied == "corrected" else "",
        error,
    )
    try:
        await bot.on_runtime_event(RuntimeEvent(kind="decisionRejected", details=details))
    except Exception as hook_error:  # noqa: BLE001 — a bot's hook must never propagate
        logger.warning(
            "request %s: on_runtime_event raised while reporting a rejection: %s",
            context.request_id,
            hook_error,
        )
    try:
        await bot.on_error(error)
    except Exception as hook_error:  # noqa: BLE001 — a bot's hook must never propagate
        logger.warning(
            "request %s: on_error raised while reporting a rejection: %s",
            context.request_id,
            hook_error,
        )
