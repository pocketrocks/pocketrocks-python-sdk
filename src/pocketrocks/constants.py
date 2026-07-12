connect_path = "/api/bots/connect"

# Multiplicative jitter applied to each reconnect sleep so many bots do not
# reconnect in lockstep (avoids thundering-herd after a server restart).
reconnect_jitter_fraction = 0.15

# Handshake rejection statuses that will never succeed on retry, so the runtime
# stops instead of reconnecting forever. 401 = invalid/expired API key,
# 400 = invalid connection parameters (e.g. protocol version mismatch).
# Notably 403 (bot deactivated) is NOT here: it is expected and retryable, so a
# locally running bot idles and reconnects automatically when reactivated.
fatal_connect_status_codes = frozenset({400, 401})
