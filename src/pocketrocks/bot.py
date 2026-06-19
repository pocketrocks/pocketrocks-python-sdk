from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any

from pocketrocks.config import BotConfig
from pocketrocks.runtime import PocketRocksRuntime
from pocketrocks.types import BotDecision, DecisionContext, RuntimeEvent


class PocketRocksBot(ABC):
    def __init__(
        self,
        api_key: str | None = None,
        bot_id: str | None = None,
        server_url: str | None = None,
        capacity: int | None = None,
        protocol_version: int | None = None,
        max_in_flight_decisions: int | None = None,
        max_queue_size: int | None = None,
        min_remaining_deadline_ms_to_start: int | None = None,
        request_timeout_slack_ms: int | None = None,
        reconnect: bool | None = None,
        reconnect_base_delay_seconds: float | None = None,
        reconnect_max_delay_seconds: float | None = None,
        transport: Any | None = None,
    ) -> None:
        env_config = BotConfig.from_env()
        self.config = BotConfig(
            api_key=api_key or env_config.api_key,
            bot_id=bot_id or env_config.bot_id,
            server_url=server_url or env_config.server_url,
            capacity=capacity or env_config.capacity,
            protocol_version=protocol_version or env_config.protocol_version,
            max_in_flight_decisions=max_in_flight_decisions or env_config.max_in_flight_decisions,
            max_queue_size=(
                max_queue_size if max_queue_size is not None else env_config.max_queue_size
            ),
            min_remaining_deadline_ms_to_start=(
                min_remaining_deadline_ms_to_start
                if min_remaining_deadline_ms_to_start is not None
                else env_config.min_remaining_deadline_ms_to_start
            ),
            request_timeout_slack_ms=(
                request_timeout_slack_ms
                if request_timeout_slack_ms is not None
                else env_config.request_timeout_slack_ms
            ),
            reconnect=env_config.reconnect if reconnect is None else reconnect,
            reconnect_base_delay_seconds=(
                reconnect_base_delay_seconds
                if reconnect_base_delay_seconds is not None
                else env_config.reconnect_base_delay_seconds
            ),
            reconnect_max_delay_seconds=(
                reconnect_max_delay_seconds
                if reconnect_max_delay_seconds is not None
                else env_config.reconnect_max_delay_seconds
            ),
        )
        if self.config.api_key is None:
            raise ValueError("api_key is required")
        if self.config.bot_id is None:
            raise ValueError("bot_id is required")
        self.transport = transport

    def run(self) -> None:
        asyncio.run(self.run_async())

    async def run_async(self) -> None:
        runtime = PocketRocksRuntime(bot=self, config=self.config, transport=self.transport)
        await runtime.run()

    @abstractmethod
    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        raise NotImplementedError

    async def choose_raw_decision(self, frame: object, context: DecisionContext) -> BotDecision:
        return await self.choose_decision(context)

    def uses_raw_decision(self) -> bool:
        return type(self).choose_raw_decision is not PocketRocksBot.choose_raw_decision

    async def on_connect(self) -> None:
        return None

    async def on_disconnect(self) -> None:
        return None

    async def on_runtime_event(self, event: RuntimeEvent) -> None:
        return None

    async def on_error(self, error: Exception) -> None:
        return None
