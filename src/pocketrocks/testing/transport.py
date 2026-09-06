from __future__ import annotations

from pocketrocks.internal.bot_wire import Frame, HeartbeatRequest
from pocketrocks.protocol import decode_frame, encode_frame

_DEFAULT_HEARTBEAT_DEADLINE_MS = 5_000


class FakeTransport:
    """In-memory adapter at the transport seam, for driving a bot end-to-end.

    Duck-types the same four-method interface as
    :class:`~pocketrocks.transport.WebSocketTransport`: it serves a scripted list
    of incoming byte frames and records everything the runtime sends. Inject it
    via ``PocketRocksBot(transport=...)``. When the incoming frames are exhausted,
    :meth:`receive_bytes` raises ``EOFError`` — the same signal the runtime's read
    loop uses to shut down cleanly, so ``run_async()`` returns on its own once the
    script is drained (pair with ``reconnect=False``).
    """

    def __init__(self, incoming_messages: list[bytes] | None = None) -> None:
        self.incoming_messages: list[bytes] = list(incoming_messages or [])
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


def heartbeat_bytes(
    request_id: str, *, remaining_ms: int = _DEFAULT_HEARTBEAT_DEADLINE_MS
) -> bytes:
    """Encode a heartbeat request frame for feeding to :class:`FakeTransport`."""
    from pocketrocks.runtime import now_ms

    return encode_frame(
        HeartbeatRequest(
            kind="heartbeatRequest",
            request_id=request_id,
            deadline_at=now_ms() + remaining_ms,
        )
    )


def decode_frames(payloads: list[bytes]) -> list[Frame]:
    """Decode the frames a bot sent (e.g. ``transport.sent_messages``) for asserting.

    Saves tests from reaching into ``pocketrocks.internal`` to inspect responses.
    """
    return [decode_frame(payload) for payload in payloads]
