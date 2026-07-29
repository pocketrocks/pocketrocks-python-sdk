from __future__ import annotations

import logging

import pytest

import pocketrocks._update_check as update_check

REMOTE_NEWER = b'__version__ = "9.9.9"\nRULES_VERSION = 99\n'
REMOTE_SAME = (
    f'__version__ = "{update_check.__version__}"\nRULES_VERSION = {update_check.RULES_VERSION}\n'
).encode()


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_check, "_checked", False)
    monkeypatch.delenv("POCKETROCKS_SKIP_VERSION_CHECK", raising=False)


def _fake_fetch(payload: bytes | Exception):
    def fetch(url: str, timeout: float) -> bytes:
        if isinstance(payload, Exception):
            raise payload
        return payload
    return fetch


def test_warns_when_behind(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(update_check, "_fetch", _fake_fetch(REMOTE_NEWER))
    with caplog.at_level(logging.WARNING, logger="pocketrocks"):
        update_check.maybe_warn_if_stale()
    assert any("9.9.9" in r.message and "rules" in r.message.lower() for r in caplog.records)


def test_silent_when_current(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(update_check, "_fetch", _fake_fetch(REMOTE_SAME))
    with caplog.at_level(logging.WARNING, logger="pocketrocks"):
        update_check.maybe_warn_if_stale()
    assert not caplog.records


def test_silent_on_network_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(update_check, "_fetch", _fake_fetch(OSError("offline")))
    with caplog.at_level(logging.WARNING, logger="pocketrocks"):
        update_check.maybe_warn_if_stale()
    assert not caplog.records


def test_runs_once_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        update_check, "_fetch", lambda url, timeout: calls.append(url) or REMOTE_SAME
    )
    update_check.maybe_warn_if_stale()
    update_check.maybe_warn_if_stale()
    assert len(calls) == 1


def test_env_opt_out(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setenv("POCKETROCKS_SKIP_VERSION_CHECK", "1")
    monkeypatch.setattr(
        update_check, "_fetch", lambda url, timeout: calls.append(url) or REMOTE_NEWER
    )
    update_check.maybe_warn_if_stale()
    assert not calls
