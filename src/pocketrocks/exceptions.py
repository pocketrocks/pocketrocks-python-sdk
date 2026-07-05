class PocketRocksError(Exception):
    pass


class TransportError(PocketRocksError):
    pass


class TransportRejected(TransportError):
    """Raised when the server rejects the connection handshake with an HTTP status.

    Subclasses :class:`TransportError` so generic transport handling still
    applies, while exposing ``status_code`` so the runtime can decide whether
    the rejection is retryable (e.g. 403 while the bot is deactivated) or
    fatal (e.g. 401 for an invalid API key).
    """

    def __init__(self, status_code: int, message: str | None = None) -> None:
        super().__init__(message or f"connection rejected with status {status_code}")
        self.status_code = status_code


class TransportClosed(PocketRocksError):
    pass


class ProtocolError(PocketRocksError):
    pass


class InvalidBotDecision(PocketRocksError):
    pass
