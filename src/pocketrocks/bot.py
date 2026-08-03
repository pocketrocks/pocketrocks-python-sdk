from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any

from pocketrocks._logging import install_default_logging
from pocketrocks._update_check import kickoff_update_check
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
        rejected_reconnect_max_delay_seconds: float | None = None,
        debug: bool | None = None,
        transport: Any | None = None,
    ) -> None:
        # Explicit constructor args win over env; from_env only reads/parses an
        # env var when its override is None, so a bad .env value for a field the
        # caller overrides never blocks construction.
        self.config = BotConfig.from_env(
            api_key=api_key,
            bot_id=bot_id,
            server_url=server_url,
            capacity=capacity,
            protocol_version=protocol_version,
            max_in_flight_decisions=max_in_flight_decisions,
            max_queue_size=max_queue_size,
            min_remaining_deadline_ms_to_start=min_remaining_deadline_ms_to_start,
            request_timeout_slack_ms=request_timeout_slack_ms,
            reconnect=reconnect,
            reconnect_base_delay_seconds=reconnect_base_delay_seconds,
            reconnect_max_delay_seconds=reconnect_max_delay_seconds,
            rejected_reconnect_max_delay_seconds=rejected_reconnect_max_delay_seconds,
            debug=debug,
        )
        self.transport = transport

    def run(self) -> None:
        install_default_logging()
        asyncio.run(self.run_async())

    async def run_async(self) -> None:
        if self.config.api_key is None:
            raise ValueError("api_key is required")
        if self.config.bot_id is None:
            raise ValueError("bot_id is required")
        # Fire-and-forget: the advisory check must never gate startup or
        # stall an application-owned event loop.
        kickoff_update_check()
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
