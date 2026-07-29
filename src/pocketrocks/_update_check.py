"""Best-effort staleness warning against the repo's default branch.

The repo is the distribution channel (installs come from ``git+https``), so
the tip of the default branch (``develop``) *is* the latest release. This
never blocks or raises: any failure (offline, timeout, parse) is silent, it
runs at most once per process, and ``POCKETROCKS_SKIP_VERSION_CHECK``
disables it entirely.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import urllib.request

from pocketrocks._version import RULES_VERSION, __version__

_RAW_URL = (
    "https://raw.githubusercontent.com/jaiparera/pocketrocks-python-sdk/"
    "develop/src/pocketrocks/_version.py"
)
_VERSION_RE = re.compile(r'__version__\s*=\s*"([0-9]+)\.([0-9]+)\.([0-9]+)"')
_RULES_RE = re.compile(r"RULES_VERSION\s*=\s*([0-9]+)")

_checked = False
_logger = logging.getLogger("pocketrocks")


_lock = threading.Lock()


def _fetch(url: str, timeout: float) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
        return bytes(response.read())


def kickoff_update_check() -> None:
    """Run the staleness check once, on a daemon thread, without gating the caller.

    Entry points (LocalGame, run_games, the live runtime) call this instead of
    the blocking check so game execution never waits on the network, DNS, or
    the timeout — and after the first run the flag check below makes this a
    no-op, so repeated games spawn no further threads.
    """
    if _checked or os.environ.get("POCKETROCKS_SKIP_VERSION_CHECK"):
        return
    threading.Thread(
        target=maybe_warn_if_stale, name="pocketrocks-update-check", daemon=True
    ).start()


def maybe_warn_if_stale(*, timeout: float = 1.0) -> None:
    global _checked
    with _lock:
        if _checked or os.environ.get("POCKETROCKS_SKIP_VERSION_CHECK"):
            return
        _checked = True
    try:
        text = _fetch(_RAW_URL, timeout).decode("utf-8", errors="replace")
        version_match = _VERSION_RE.search(text)
        rules_match = _RULES_RE.search(text)
        if not version_match or not rules_match:
            return
        remote_version = tuple(int(part) for part in version_match.groups())
        local_version = tuple(int(part) for part in __version__.split("."))
        remote_rules = int(rules_match.group(1))
        if remote_version <= local_version and remote_rules <= RULES_VERSION:
            return
        rules_note = (
            " This includes GAME RULES changes, so local sim results may not match the "
            "live server." if remote_rules > RULES_VERSION else ""
        )
        _logger.warning(
            "A newer PocketRocks SDK is available (%s; you have %s).%s Upgrade with: "
            "pip install --upgrade git+https://github.com/jaiparera/pocketrocks-python-sdk.git",
            ".".join(str(part) for part in remote_version),
            __version__,
            rules_note,
        )
    except Exception:  # noqa: BLE001 — advisory only, never break the caller
        return
