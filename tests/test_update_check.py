from __future__ import annotations

import threading
import warnings

import pytest

import pocketrocks._update_check as update_check
from pocketrocks._update_check import StaleSDKWarning

REMOTE_NEWER = b'__version__ = "9.9.9"\nRULES_VERSION = 99\n'
REMOTE_SAME = (
    f'__version__ = "{update_check.__version__}"\nRULES_VERSION = {update_check.RULES_VERSION}\n'
).encode()


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_check, "_checked", False)
    monkeypatch.setattr(update_check, "_kicked", False)
    monkeypatch.delenv("POCKETROCKS_SKIP_VERSION_CHECK", raising=False)


def _fake_fetch(payload: bytes | Exception):
    def fetch(url: str, timeout: float) -> bytes:
        if isinstance(payload, Exception):
            raise payload
        return payload
    return fetch


def _stale_warnings(record: list[warnings.WarningMessage]) -> list[warnings.WarningMessage]:
    return [w for w in record if issubclass(w.category, StaleSDKWarning)]


def test_warns_when_behind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_check, "_fetch", _fake_fetch(REMOTE_NEWER))
    # warnings, not logging: the package logger carries a NullHandler, so a log
    # record would be invisible in zero-config scripts — the exact audience of
    # this safeguard.
    with pytest.warns(StaleSDKWarning) as record:
        update_check.maybe_warn_if_stale()
    message = str(record[0].message)
    assert "9.9.9" in message
    assert "rules" in message.lower()


def test_silent_when_current(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_check, "_fetch", _fake_fetch(REMOTE_SAME))
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        update_check.maybe_warn_if_stale()
    assert not _stale_warnings(record)


def test_silent_on_network_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_check, "_fetch", _fake_fetch(OSError("offline")))
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        update_check.maybe_warn_if_stale()
    assert not _stale_warnings(record)


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


def test_kickoff_spawns_no_thread_when_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setenv("POCKETROCKS_SKIP_VERSION_CHECK", "1")
    monkeypatch.setattr(update_check, "_fetch", lambda url, timeout: calls.append(url) or b"")
    update_check.kickoff_update_check()
    assert not calls


def test_kickoff_runs_check_in_background(monkeypatch: pytest.MonkeyPatch) -> None:
    fetched = threading.Event()

    def fake_fetch(url: str, timeout: float) -> bytes:
        fetched.set()
        return REMOTE_SAME

    monkeypatch.setattr(update_check, "_fetch", fake_fetch)
    update_check.kickoff_update_check()
    assert fetched.wait(timeout=5), "background check never ran"


def test_kickoff_noop_after_check_ran(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_check, "_fetch", lambda url, timeout: REMOTE_SAME)
    update_check.maybe_warn_if_stale()  # sets _checked
    started: list[str] = []
    real_thread = threading.Thread

    def spy_thread(*args: object, **kwargs: object) -> threading.Thread:
        started.append("spawned")
        return real_thread(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(update_check.threading, "Thread", spy_thread)
    update_check.kickoff_update_check()
    assert not started  # no thread churn once the once-per-process check ran


def test_kickoff_reserves_before_spawning(monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated/concurrent kickoffs spawn exactly one worker: the reservation
    is taken under the lock BEFORE the thread starts, so callers racing in
    while the fetch is still parked cannot each create a thread."""
    release = threading.Event()

    def parked_fetch(url: str, timeout: float) -> bytes:
        release.wait(timeout=5)
        return REMOTE_SAME

    monkeypatch.setattr(update_check, "_fetch", parked_fetch)
    started: list[str] = []
    real_thread = threading.Thread

    def spy_thread(*args: object, **kwargs: object) -> threading.Thread:
        started.append("spawned")
        return real_thread(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(update_check.threading, "Thread", spy_thread)
    update_check.kickoff_update_check()
    update_check.kickoff_update_check()  # worker still parked; must not respawn
    release.set()
    assert started == ["spawned"]


def test_atexit_join_is_bounded_and_lets_check_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()
    done = threading.Event()

    def slow_fetch(url: str, timeout: float) -> bytes:
        release.wait(timeout=5)
        done.set()
        return REMOTE_SAME

    registered: list[object] = []
    monkeypatch.setattr(update_check, "_fetch", slow_fetch)
    monkeypatch.setattr(update_check.atexit, "register", lambda fn: registered.append(fn))
    update_check.kickoff_update_check()
    assert registered == [update_check._join_worker]
    release.set()
    update_check._join_worker()  # the shutdown hook: bounded, lets the fetch land
    assert done.is_set()
