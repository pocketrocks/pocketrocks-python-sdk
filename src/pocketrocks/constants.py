default_server_url = "wss://pocketrocks.xyz"
connect_path = "/api/bots/connect"
default_protocol_version = 2
default_capacity = 1
default_max_in_flight_decisions = 4
default_max_queue_size = 32
default_min_remaining_deadline_ms_to_start = 100
default_request_timeout_slack_ms = 25
default_reconnect = True
default_reconnect_base_delay_seconds = 0.5
# Ceiling for transient failures (network blip, server restart) — recover fast.
default_reconnect_max_delay_seconds = 8.0
# Ceiling for retryable handshake *rejections* (403 = deactivated). A deactivated
# bot may stay off for a long time, so poll far less often to spare the server,
# while early retries still ramp up from the base delay to catch a quick toggle.
default_rejected_reconnect_max_delay_seconds = 60.0
# Multiplicative jitter applied to each reconnect sleep so many bots do not
# reconnect in lockstep (avoids thundering-herd after a server restart).
reconnect_jitter_fraction = 0.15

# Handshake rejection statuses that will never succeed on retry, so the runtime
# stops instead of reconnecting forever. 401 = invalid/expired API key,
# 400 = invalid connection parameters (e.g. protocol version mismatch).
# Notably 403 (bot deactivated) is NOT here: it is expected and retryable, so a
# locally running bot idles and reconnects automatically when reactivated.
fatal_connect_status_codes = frozenset({400, 401})
