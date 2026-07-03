from __future__ import annotations

from typing import Any

import websockets
from websockets.exceptions import InvalidStatus

from pocketrocks.exceptions import TransportClosed, TransportError, TransportRejected


class WebSocketTransport:
    def __init__(self) -> None:
        self.connection: Any = None

    async def connect(self, url: str, headers: dict[str, str]) -> None:
        try:
            self.connection = await websockets.connect(
                url,
                additional_headers=headers,
            )
        except InvalidStatus as error:
            raise TransportRejected(error.response.status_code, str(error)) from error
        except Exception as error:  # pragma: no cover - exercised via integration
            raise TransportError(str(error)) from error

    async def disconnect(self) -> None:
        if self.connection is None:
            return
        await self.connection.close()
        self.connection = None

    async def receive_bytes(self) -> bytes:
        if self.connection is None:
            raise TransportClosed("transport is not connected")
        try:
            message = await self.connection.recv()
        except Exception as error:  # pragma: no cover - exercised via integration
            raise TransportClosed(str(error)) from error
        if isinstance(message, bytes):
            return message
        raise TransportError("expected binary websocket message")

    async def send_bytes(self, payload: bytes) -> None:
        if self.connection is None:
            raise TransportClosed("transport is not connected")
        try:
            await self.connection.send(payload)
        except Exception as error:  # pragma: no cover - exercised via integration
            raise TransportClosed(str(error)) from error
