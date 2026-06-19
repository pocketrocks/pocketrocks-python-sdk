from __future__ import annotations

import os
from dataclasses import dataclass

from pocketrocks.constants import (
    default_capacity,
    default_max_in_flight_decisions,
    default_max_queue_size,
    default_min_remaining_deadline_ms_to_start,
    default_protocol_version,
    default_reconnect,
    default_reconnect_base_delay_seconds,
    default_reconnect_max_delay_seconds,
    default_request_timeout_slack_ms,
    default_server_url,
)


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

    @classmethod
    def from_env(cls) -> BotConfig:
        return cls(
            api_key=os.getenv("POCKETROCKS_API_KEY") or None,
            bot_id=os.getenv("POCKETROCKS_BOT_ID") or None,
            server_url=os.getenv("POCKETROCKS_SERVER_URL") or default_server_url,
            capacity=_int_from_env("POCKETROCKS_BOT_CAPACITY", default_capacity),
            protocol_version=_int_from_env(
                "POCKETROCKS_PROTOCOL_VERSION",
                default_protocol_version,
            ),
            max_in_flight_decisions=_int_from_env(
                "POCKETROCKS_MAX_IN_FLIGHT_DECISIONS",
                default_max_in_flight_decisions,
            ),
            max_queue_size=_int_from_env("POCKETROCKS_MAX_QUEUE_SIZE", default_max_queue_size),
            min_remaining_deadline_ms_to_start=_int_from_env(
                "POCKETROCKS_MIN_REMAINING_DEADLINE_MS_TO_START",
                default_min_remaining_deadline_ms_to_start,
            ),
            request_timeout_slack_ms=_int_from_env(
                "POCKETROCKS_REQUEST_TIMEOUT_SLACK_MS",
                default_request_timeout_slack_ms,
            ),
            reconnect=_bool_from_env("POCKETROCKS_RECONNECT", default_reconnect),
            reconnect_base_delay_seconds=_float_from_env(
                "POCKETROCKS_RECONNECT_BASE_DELAY_SECONDS",
                default_reconnect_base_delay_seconds,
            ),
            reconnect_max_delay_seconds=_float_from_env(
                "POCKETROCKS_RECONNECT_MAX_DELAY_SECONDS",
                default_reconnect_max_delay_seconds,
            ),
        )
