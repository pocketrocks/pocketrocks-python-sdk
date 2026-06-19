from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from pocketrocks.config import BotConfig
from pocketrocks.exceptions import InvalidBotDecision, TransportClosed
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
from pocketrocks.transport import WebSocketTransport
from pocketrocks.types import BotDecision, DecisionContext, RuntimeEvent


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
    ) -> None:
        self.bot = bot
        self.config = config
        self.transport = transport or WebSocketTransport()
        self.write_lock = asyncio.Lock()
        self.stop_requested = False

    async def run(self) -> None:
        reconnect_delay_seconds = self.config.reconnect_base_delay_seconds
        while not self.stop_requested:
            workers: list[asyncio.Task[None]] = []
            request_queue: asyncio.Queue[QueuedRequest | None] = asyncio.Queue(
                maxsize=max(0, self.config.max_queue_size)
            )
            try:
                await self.transport.connect(
                    build_connection_url(
                        self.config.server_url,
                        self.config.bot_id or "",
                        self.config.protocol_version,
                        self.config.capacity,
                    ),
                    {"Authorization": f"Bearer {self.config.api_key}"},
                )
                await self.bot.on_connect()
                await self.bot.on_runtime_event(RuntimeEvent(kind="connected"))
                workers = [
                    asyncio.create_task(self._worker(request_queue))
                    for _ in range(max(1, self.config.max_in_flight_decisions))
                ]
                await self._read_loop(request_queue)
            except TransportClosed as error:
                await self.bot.on_error(error)
            finally:
                for _ in workers:
                    await request_queue.put(None)
                if workers:
                    await asyncio.gather(*workers, return_exceptions=True)
                await self.transport.disconnect()
                await self.bot.on_disconnect()
                await self.bot.on_runtime_event(RuntimeEvent(kind="disconnected"))

            if not self.config.reconnect or self.stop_requested:
                return

            await asyncio.sleep(reconnect_delay_seconds)
            reconnect_delay_seconds = min(
                reconnect_delay_seconds * 2,
                self.config.reconnect_max_delay_seconds,
            )

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
            except Exception as error:
                await self.bot.on_runtime_event(
                    RuntimeEvent(kind="malformedFrame", details={"error": str(error)})
                )
                await self.bot.on_error(error)
                continue

            if isinstance(frame, HeartbeatRequest):
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
                self._validate_decision(context, decision)
                await self._send_frame(decision_to_protocol_response(frame.request_id, decision))
                await self.bot.on_runtime_event(
                    RuntimeEvent(kind="requestCompleted", details={"request_id": frame.request_id})
                )
            except asyncio.TimeoutError:
                await self._emit_drop_event(frame, "deadline_expired", frame.deadline_at - now_ms())
            except Exception as error:
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

    def _validate_decision(self, context: DecisionContext, decision: BotDecision) -> None:
        if context.decision_kind == "submitBid":
            if decision.action_kind == "selectInfoToReveal":
                raise InvalidBotDecision("submitBid requests cannot receive reveal responses")
            if decision.action_kind == "submitBid":
                if decision.value is None:
                    raise InvalidBotDecision("submitBid responses require a value")
                if (
                    context.legal_max_amount is not None
                    and decision.value > context.legal_max_amount
                ):
                    raise InvalidBotDecision("bid exceeds legal maximum")
                if decision.value < 0:
                    raise InvalidBotDecision("bid must be non-negative")
            return
        if decision.action_kind == "submitBid":
            raise InvalidBotDecision("selectInfoToReveal requests cannot receive bid responses")
        if decision.action_kind == "selectInfoToReveal":
            if decision.value is None:
                raise InvalidBotDecision("selectInfoToReveal responses require a card index")
            if decision.value < 0 or decision.value >= context.revealable_count:
                raise InvalidBotDecision("card index is out of range")

    async def _send_frame(self, frame: Frame) -> None:
        async with self.write_lock:
            await self.transport.send_bytes(encode_frame(frame))

    async def _emit_drop_event(
        self,
        frame: DecisionRequest,
        reason: str,
        remaining_ms: int,
    ) -> None:
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
