from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from dotenv import find_dotenv, load_dotenv


def _str_or_none(env: str) -> Callable[[], str | None]:
    return lambda: os.getenv(env) or None


def _str(env: str, default: str) -> Callable[[], str]:
    return lambda: os.getenv(env) or default


def _int(env: str, default: int) -> Callable[[], int]:
    def parse() -> int:
        value = os.getenv(env)
        return int(value) if value is not None else default

    return parse


def _float(env: str, default: float) -> Callable[[], float]:
    def parse() -> float:
        value = os.getenv(env)
        return float(value) if value is not None else default

    return parse


def _bool(env: str, default: bool) -> Callable[[], bool]:
    def parse() -> bool:
        value = os.getenv(env)
        if value is None:
            return default
        return value.lower() in {"1", "true", "yes", "on"}

    return parse


@dataclass(frozen=True)
class _Setting:
    """One config knob: which ``BotConfig`` field it fills, and how to read it from
    the environment (env var, parser, and default all captured in ``parse``)."""

    attr: str
    parse: Callable[[], Any]


# The single source of truth for every knob. Each row owns its env var, parser,
# and default; ``from_env`` iterates this list, and ``BotConfig``'s typed fields
# plus ``PocketRocksBot.__init__``'s kwargs mirror the same names (kept explicit
# for autocomplete and type-checking). Adding a setting = one row here + the field
# + the constructor kwarg.
_SETTINGS: tuple[_Setting, ...] = (
    _Setting("api_key", _str_or_none("POCKETROCKS_API_KEY")),
    _Setting("bot_id", _str_or_none("POCKETROCKS_BOT_ID")),
    _Setting("server_url", _str("POCKETROCKS_SERVER_URL", "wss://pocketrocks.xyz")),
    _Setting("capacity", _int("POCKETROCKS_BOT_CAPACITY", 1)),
    _Setting("protocol_version", _int("POCKETROCKS_PROTOCOL_VERSION", 2)),
    _Setting("max_in_flight_decisions", _int("POCKETROCKS_MAX_IN_FLIGHT_DECISIONS", 4)),
    _Setting("max_queue_size", _int("POCKETROCKS_MAX_QUEUE_SIZE", 32)),
    _Setting(
        "min_remaining_deadline_ms_to_start",
        _int("POCKETROCKS_MIN_REMAINING_DEADLINE_MS_TO_START", 100),
    ),
    _Setting("request_timeout_slack_ms", _int("POCKETROCKS_REQUEST_TIMEOUT_SLACK_MS", 25)),
    _Setting("reconnect", _bool("POCKETROCKS_RECONNECT", True)),
    _Setting(
        "reconnect_base_delay_seconds",
        _float("POCKETROCKS_RECONNECT_BASE_DELAY_SECONDS", 0.5),
    ),
    # Ceiling for transient failures (network blip, server restart) — recover fast.
    _Setting(
        "reconnect_max_delay_seconds",
        _float("POCKETROCKS_RECONNECT_MAX_DELAY_SECONDS", 8.0),
    ),
    # Ceiling for retryable handshake *rejections* (403 = deactivated). A deactivated
    # bot may stay off for a long time, so poll far less often to spare the server,
    # while early retries still ramp up from the base delay to catch a quick toggle.
    _Setting(
        "rejected_reconnect_max_delay_seconds",
        _float("POCKETROCKS_REJECTED_RECONNECT_MAX_DELAY_SECONDS", 60.0),
    ),
)


@dataclass(slots=True, frozen=True)
class BotConfig:
    api_key: str | None
    bot_id: str | None
    server_url: str
    capacity: int
    protocol_version: int
    max_in_flight_decisions: int
    max_queue_size: int
    min_remaining_deadline_ms_to_start: int
    request_timeout_slack_ms: int
    reconnect: bool
    reconnect_base_delay_seconds: float
    reconnect_max_delay_seconds: float
    rejected_reconnect_max_delay_seconds: float

    @classmethod
    def from_env(cls, **overrides: Any) -> BotConfig:
        """Build a config from ``POCKETROCKS_*`` env vars (and a ``.env`` file).

        Any keyword in ``overrides`` that is not ``None`` takes precedence and
        short-circuits reading/parsing the corresponding env var. This lets an
        explicit argument override a malformed ``.env`` entry (e.g. a stale
        ``POCKETROCKS_BOT_CAPACITY=foo``) instead of crashing on parse before the
        override can apply.
        """
        # Load a .env file from the current working directory (or any parent),
        # without overriding variables already set in the real environment.
        load_dotenv(find_dotenv(usecwd=True), override=False)

        values: dict[str, Any] = {}
        for setting in _SETTINGS:
            override = overrides.get(setting.attr)
            values[setting.attr] = setting.parse() if override is None else override
        return cls(**values)
