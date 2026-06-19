class PocketRocksError(Exception):
    pass


class TransportError(PocketRocksError):
    pass


class TransportClosed(PocketRocksError):
    pass


class ProtocolError(PocketRocksError):
    pass


class InvalidBotDecision(PocketRocksError):
    pass
