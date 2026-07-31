from __future__ import annotations

import pytest

from pocketrocks.config import BotConfig


def test_explicit_override_ignores_malformed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # A stale/bad .env value for a field must not block construction when the
    # caller supplies that field explicitly.
    monkeypatch.setenv("POCKETROCKS_BOT_CAPACITY", "foo")
    config = BotConfig.from_env(api_key="k", bot_id="b", capacity=3)
    assert config.capacity == 3


def test_malformed_env_still_raises_when_not_overridden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POCKETROCKS_BOT_CAPACITY", "foo")
    with pytest.raises(ValueError):
        BotConfig.from_env(api_key="k", bot_id="b")


def test_env_used_when_no_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POCKETROCKS_BOT_CAPACITY", "5")
    config = BotConfig.from_env(api_key="k", bot_id="b")
    assert config.capacity == 5


def test_debug_defaults_to_false() -> None:
    assert BotConfig.from_env(api_key="k", bot_id="b").debug is False


def test_debug_reads_truthy_env_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for raw in ("1", "true", "yes", "on", "TRUE"):
        monkeypatch.setenv("POCKETROCKS_DEBUG", raw)
        assert BotConfig.from_env(api_key="k", bot_id="b").debug is True, raw


def test_debug_reads_falsy_env_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POCKETROCKS_DEBUG", "0")
    assert BotConfig.from_env(api_key="k", bot_id="b").debug is False


def test_explicit_debug_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POCKETROCKS_DEBUG", "1")
    assert BotConfig.from_env(api_key="k", bot_id="b", debug=False).debug is False
