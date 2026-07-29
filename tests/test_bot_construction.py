from __future__ import annotations

import asyncio
import pathlib

import pytest

from pocketrocks import BotDecision, DecisionContext, PocketRocksBot
from pocketrocks._version import RULES_VERSION, __version__


class _Bot(PocketRocksBot):
    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        return BotDecision.pass_turn()


def test_constructs_without_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    # Isolate from any real .env file so find_dotenv(usecwd=True) finds nothing.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("POCKETROCKS_API_KEY", raising=False)
    monkeypatch.delenv("POCKETROCKS_BOT_ID", raising=False)
    bot = _Bot()  # must not raise: local sim needs credential-free construction
    assert bot.config.api_key is None


def test_run_async_still_requires_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    # Isolate from any real .env file so find_dotenv(usecwd=True) finds nothing.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("POCKETROCKS_API_KEY", raising=False)
    monkeypatch.delenv("POCKETROCKS_BOT_ID", raising=False)
    with pytest.raises(ValueError, match="api_key"):
        asyncio.run(_Bot().run_async())


def test_version_constants() -> None:
    assert isinstance(__version__, str) and __version__.count(".") == 2
    assert isinstance(RULES_VERSION, int)
