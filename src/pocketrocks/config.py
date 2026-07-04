from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from dotenv import find_dotenv, load_dotenv

from pocketrocks.constants import (
    default_capacity,
    default_max_in_flight_decisions,
    default_max_queue_size,
    default_min_remaining_deadline_ms_to_start,
    default_protocol_version,
    default_reconnect,
    default_reconnect_base_delay_seconds,
    default_reconnect_max_delay_seconds,
    default_rejected_reconnect_max_delay_seconds,
    default_request_timeout_slack_ms,
    default_server_url,
)

_T = TypeVar("_T")


def _int_from_env(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value is not None else default


def _float_from_env(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value is not None else default


def _bool_from_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


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

        def resolve(key: str, parse: Callable[[], _T]) -> _T:
            override = overrides.get(key)
            return parse() if override is None else override

        return cls(
            api_key=resolve("api_key", lambda: os.getenv("POCKETROCKS_API_KEY") or None),
            bot_id=resolve("bot_id", lambda: os.getenv("POCKETROCKS_BOT_ID") or None),
            server_url=resolve(
                "server_url",
                lambda: os.getenv("POCKETROCKS_SERVER_URL") or default_server_url,
            ),
            capacity=resolve(
                "capacity",
                lambda: _int_from_env("POCKETROCKS_BOT_CAPACITY", default_capacity),
            ),
            protocol_version=resolve(
                "protocol_version",
                lambda: _int_from_env("POCKETROCKS_PROTOCOL_VERSION", default_protocol_version),
            ),
            max_in_flight_decisions=resolve(
                "max_in_flight_decisions",
                lambda: _int_from_env(
                    "POCKETROCKS_MAX_IN_FLIGHT_DECISIONS",
                    default_max_in_flight_decisions,
                ),
            ),
            max_queue_size=resolve(
                "max_queue_size",
                lambda: _int_from_env("POCKETROCKS_MAX_QUEUE_SIZE", default_max_queue_size),
            ),
            min_remaining_deadline_ms_to_start=resolve(
                "min_remaining_deadline_ms_to_start",
                lambda: _int_from_env(
                    "POCKETROCKS_MIN_REMAINING_DEADLINE_MS_TO_START",
                    default_min_remaining_deadline_ms_to_start,
                ),
            ),
            request_timeout_slack_ms=resolve(
                "request_timeout_slack_ms",
                lambda: _int_from_env(
                    "POCKETROCKS_REQUEST_TIMEOUT_SLACK_MS",
                    default_request_timeout_slack_ms,
                ),
            ),
            reconnect=resolve(
                "reconnect",
                lambda: _bool_from_env("POCKETROCKS_RECONNECT", default_reconnect),
            ),
            reconnect_base_delay_seconds=resolve(
                "reconnect_base_delay_seconds",
                lambda: _float_from_env(
                    "POCKETROCKS_RECONNECT_BASE_DELAY_SECONDS",
                    default_reconnect_base_delay_seconds,
                ),
            ),
            reconnect_max_delay_seconds=resolve(
                "reconnect_max_delay_seconds",
                lambda: _float_from_env(
                    "POCKETROCKS_RECONNECT_MAX_DELAY_SECONDS",
                    default_reconnect_max_delay_seconds,
                ),
            ),
            rejected_reconnect_max_delay_seconds=resolve(
                "rejected_reconnect_max_delay_seconds",
                lambda: _float_from_env(
                    "POCKETROCKS_REJECTED_RECONNECT_MAX_DELAY_SECONDS",
                    default_rejected_reconnect_max_delay_seconds,
                ),
            ),
        )
