from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from pocketrocks._reporting import PendingRejection, RejectionReporter
from pocketrocks.config import BotConfig
from pocketrocks.constants import fatal_connect_status_codes
from pocketrocks.exceptions import (
    TransportClosed,
    TransportError,
    TransportRejected,
)
from pocketrocks.internal.bot_wire_v2 import (
    DecisionRequest,
    Frame,
    HeartbeatRequest,
    HeartbeatResponse,
    decode_frame,
    encode_frame,
)
from pocketrocks.protocol import (
    build_connection_url,
    build_decision_context,
    decision_to_protocol_response,
)
from pocketrocks.reconnect import ReconnectOutcome, ReconnectPolicy
from pocketrocks.transport import WebSocketTransport
from pocketrocks.types import BotDecision, DecisionContext, RuntimeEvent, classify

logger = logging.getLogger("pocketrocks.runtime")

# How long disconnect waits for reports still in flight before cancelling the
# reporter. See ``RejectionReporter`` for why the wait is bounded at all; the value
# matches the update check's ``_JOIN_TIMEOUT_S`` shutdown wait. Kept per-surface
# because a live bot and a training loop could reasonably want different budgets.
_REPORT_DRAIN_TIMEOUT_S = 1.5


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(slots=True)
class QueuedRequest:
    frame: DecisionRequest
    received_at: int


class PocketRocksRuntime:
    def __init__(
        self,
        *,
        bot: Any,
        config: BotConfig,
        transport: Any | None = None,
        policy: ReconnectPolicy | None = None,
    ) -> None:
        self.bot = bot
        self.config = config
        self.transport = transport or WebSocketTransport()
        self.policy = policy or ReconnectPolicy(config)
        self.write_lock = asyncio.Lock()
        self.stop_requested = False
        # Rejections are reported off the workers — a bot's telemetry hook must not
        # be able to occupy the worker that is about to take the next request.
        # Shared with the sim so both surfaces deliver the same reports the same way.
        self._reporter = RejectionReporter(logger)

    async def run(self) -> None:
        logger.info(
            "starting bot %s; connecting to %s",
            self.config.bot_id,
            self.config.server_url,
        )
        while not self.stop_requested:
            workers: list[asyncio.Task[None]] = []
            # Floor at 1: asyncio.Queue(maxsize=0) is *unbounded*, so a
            # configured 0/negative would silently disable the overload drop
            # path below. Clamp to the smallest bounded capacity instead.
            request_queue: asyncio.Queue[QueuedRequest | None] = asyncio.Queue(
                maxsize=max(1, self.config.max_queue_size)
            )
            connected = False
            # Which backoff schedule this attempt's failure warrants. Transient by
            # default; a retryable handshake rejection (403) escalates it below.
            outcome: ReconnectOutcome = "transient"
            try:
                await self.transport.connect(
                    build_connection_url(
                        self.config.server_url,
                        self.config.bot_id or "",
                        self.config.protocol_version,
                        self.config.capacity,
                    ),
                    {"Authorization": f"ApiKey {self.config.api_key}"},
                )
                connected = True
                # A successful connection clears any accumulated backoff so that
                # repeated deactivate/reactivate cycles reconnect promptly.
                self.policy.reset()
                logger.info(
                    "connected to %s as bot %s (capacity %d); waiting for decision requests",
                    self.config.server_url,
                    self.config.bot_id,
                    self.config.capacity,
                )
                await self.bot.on_connect()
                await self.bot.on_runtime_event(RuntimeEvent(kind="connected"))
                workers = [
                    asyncio.create_task(self._worker(request_queue))
                    for _ in range(max(1, self.config.max_in_flight_decisions))
                ]
                await self._read_loop(request_queue)
            except TransportRejected as error:
                # The server refused the handshake. 403 means the bot is
                # deactivated (expected while toggling) — stay alive and retry.
                # Fatal statuses (bad/expired key, invalid params) will never
                # succeed, so stop rather than reconnect forever.
                fatal = error.status_code in fatal_connect_status_codes
                if not fatal:
                    # Rejection (deactivated/rate-limited) is expected to persist,
                    # so poll on the slow ceiling rather than the transient one.
                    outcome = "rejected"
                if fatal:
                    logger.error(
                        "connection rejected (HTTP %d) — not retryable; stopping. "
                        "Check POCKETROCKS_API_KEY and connection parameters.",
                        error.status_code,
                    )
                elif error.status_code == 403:
                    logger.warning(
                        "connection rejected (HTTP 403) — bot is deactivated or not "
                        "owned by this API key; will keep retrying until reactivated",
                    )
                else:
                    logger.warning(
                        "connection rejected (HTTP %d); will retry",
                        error.status_code,
                    )
                await self.bot.on_runtime_event(
                    RuntimeEvent(
                        kind="connectionRejected",
                        details={"status_code": error.status_code},
                    )
                )
                await self.bot.on_error(error)
                if fatal:
                    return
            except TransportError as error:
                # Network failure / server unavailable — retryable.
                logger.warning("connection error: %s; will retry", error)
                await self.bot.on_runtime_event(
                    RuntimeEvent(kind="connectionError", details={"error": str(error)})
                )
                await self.bot.on_error(error)
            except TransportClosed as error:
                logger.info("connection closed by server: %s", error)
                await self.bot.on_error(error)
            finally:
                for _ in workers:
                    await request_queue.put(None)
                if workers:
                    await asyncio.gather(*workers, return_exceptions=True)
                # After the workers, which can queue a report right up to their last
                # item, and before on_disconnect, so a bot hears why a decision was
                # rejected before it hears the connection ended. Bounded, then
                # cancelled: shutdown must no more hang on a telemetry hook than a
                # worker must. A reconnect gets a fresh reporter.
                await self._reporter.drain(timeout_s=_REPORT_DRAIN_TIMEOUT_S)
                await self.transport.disconnect()
                if connected:
                    logger.info("disconnected from %s", self.config.server_url)
                    await self.bot.on_disconnect()
                    await self.bot.on_runtime_event(RuntimeEvent(kind="disconnected"))

            if not self.config.reconnect or self.stop_requested:
                logger.info("reconnect disabled; bot runtime stopped")
                return

            sleep_seconds = self.policy.next_delay(outcome)
            logger.info("reconnecting in %.1fs", sleep_seconds)
            await asyncio.sleep(sleep_seconds)

    async def stop(self) -> None:
        self.stop_requested = True
        await self.transport.disconnect()

    async def _read_loop(self, request_queue: asyncio.Queue[QueuedRequest | None]) -> None:
        while not self.stop_requested:
            try:
                payload = await self.transport.receive_bytes()
            except EOFError:
                return
            frame_received_at = now_ms()
            try:
                frame = decode_frame(payload)
            # Deliberately broad: any decode failure must be reported to the bot and
            # the read loop kept alive rather than propagated and killing the runtime.
            except Exception as error:  # noqa: BLE001
                logger.warning("dropping malformed frame: %s", error)
                await self.bot.on_runtime_event(
                    RuntimeEvent(kind="malformedFrame", details={"error": str(error)})
                )
                await self.bot.on_error(error)
                continue

            if isinstance(frame, HeartbeatRequest):
                logger.debug("heartbeat %s", frame.request_id)
                await self.bot.on_runtime_event(
                    RuntimeEvent(kind="heartbeatReceived", details={"request_id": frame.request_id})
                )
                await self._send_frame(
                    HeartbeatResponse(kind="heartbeatResponse", request_id=frame.request_id)
                )
                await self.bot.on_runtime_event(
                    RuntimeEvent(kind="heartbeatSent", details={"request_id": frame.request_id})
                )
                continue

            if isinstance(frame, DecisionRequest):
                await self._enqueue_request(request_queue, frame, frame_received_at)

    async def _enqueue_request(
        self,
        request_queue: asyncio.Queue[QueuedRequest | None],
        frame: DecisionRequest,
        received_at: int,
    ) -> None:
        remaining_ms = frame.deadline_at - received_at
        if remaining_ms < self.config.min_remaining_deadline_ms_to_start:
            await self._emit_drop_event(frame, "deadline_expired", remaining_ms)
            return
        try:
            request_queue.put_nowait(QueuedRequest(frame=frame, received_at=received_at))
        except asyncio.QueueFull:
            await self._emit_drop_event(frame, "queue_full", remaining_ms)
            return
        await self.bot.on_runtime_event(
            RuntimeEvent(
                kind="requestQueued",
                details={"request_id": frame.request_id, "remaining_deadline_ms": remaining_ms},
            )
        )

    async def _worker(self, request_queue: asyncio.Queue[QueuedRequest | None]) -> None:
        while True:
            item = await request_queue.get()
            if item is None:
                return
            queued_request = item
            frame = queued_request.frame
            start_ms = now_ms()
            remaining_ms = frame.deadline_at - start_ms
            if remaining_ms < self.config.min_remaining_deadline_ms_to_start:
                await self._emit_drop_event(frame, "deadline_expired", remaining_ms)
                continue
            try:
                context = build_decision_context(frame, received_at=queued_request.received_at)
                decision = await self._resolve_decision(frame, context, remaining_ms)
                applied, rejection, outgoing = classify(context, decision)
                # Send before reporting: report_rejection awaits user-defined
                # callbacks, and a slow or raising hook must never consume the
                # decision deadline or suppress the response. "discarded" is the
                # only fate with nothing sendable.
                if applied != "discarded":
                    await self._send_frame(
                        decision_to_protocol_response(frame.request_id, outgoing)
                    )
                if rejection is not None:
                    # Hand off, never await: report_rejection awaits user-defined
                    # hooks, and a hook that blocks would own this worker until it
                    # returned — starving max_in_flight_decisions and hanging the
                    # gather() in run()'s finally. Sending first (above) protects
                    # only this response; not awaiting protects the ones behind it.
                    await self._reporter.hand_off(
                        PendingRejection(
                            bot=self.bot,
                            context=context,
                            decision=decision,
                            error=rejection,
                            applied=applied,
                            debug=self.config.debug,
                            outgoing=outgoing,
                        )
                    )
                if applied == "discarded":
                    continue
                logger.debug(
                    "request %s (%s) -> %s %s",
                    frame.request_id,
                    frame.decision_kind,
                    outgoing.action_kind,
                    outgoing.value if outgoing.value is not None else "",
                )
                await self.bot.on_runtime_event(
                    RuntimeEvent(kind="requestCompleted", details={"request_id": frame.request_id})
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "request %s timed out before the bot returned a decision", frame.request_id
                )
                await self._emit_drop_event(frame, "deadline_expired", frame.deadline_at - now_ms())
            # Deliberately broad: this wraps a call into arbitrary bot code
            # (choose_decision), which can raise anything. One bad decision must not
            # kill the worker; report it and keep processing the queue.
            except Exception as error:  # noqa: BLE001
                logger.warning("request %s failed: %s", frame.request_id, error)
                await self.bot.on_runtime_event(
                    RuntimeEvent(
                        kind="requestFailed",
                        details={"request_id": frame.request_id, "error": str(error)},
                    )
                )
                await self.bot.on_error(error)

    async def _resolve_decision(
        self,
        frame: DecisionRequest,
        context: DecisionContext,
        remaining_ms: int,
    ) -> BotDecision:
        timeout_ms = max(1, remaining_ms - self.config.request_timeout_slack_ms)
        if self._uses_raw_callback():
            callback = self.bot.choose_raw_decision(frame, context)
        else:
            callback = self.bot.choose_decision(context)
        return await asyncio.wait_for(callback, timeout=timeout_ms / 1000)

    def _uses_raw_callback(self) -> bool:
        return bool(self.bot.uses_raw_decision())

    async def _send_frame(self, frame: Frame) -> None:
        async with self.write_lock:
            await self.transport.send_bytes(encode_frame(frame))

    async def _emit_drop_event(
        self,
        frame: DecisionRequest,
        reason: str,
        remaining_ms: int,
    ) -> None:
        logger.warning(
            "dropped request %s (%s); remaining deadline %dms",
            frame.request_id,
            reason,
            remaining_ms,
        )
        await self.bot.on_runtime_event(
            RuntimeEvent(
                kind="requestDropped",
                details={
                    "request_id": frame.request_id,
                    "reason": reason,
                    "remaining_deadline_ms": remaining_ms,
                },
            )
        )
