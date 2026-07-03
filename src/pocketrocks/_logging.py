from __future__ import annotations

import logging
import os

library_logger_name = "pocketrocks"


def _level_from_env() -> int | None:
    name = os.getenv("POCKETROCKS_LOG_LEVEL")
    if not name:
        return None
    candidate = getattr(logging, name.strip().upper(), None)
    return candidate if isinstance(candidate, int) else None


def install_default_logging(default_level: int = logging.INFO) -> None:
    """Give a bare ``Bot().run()`` script readable connection logs out of the box.

    Honors ``POCKETROCKS_LOG_LEVEL`` (e.g. ``DEBUG``) for the ``pocketrocks``
    logger. A simple stderr handler is attached only when the host application
    has not configured logging itself (no root handlers and no non-null handler
    on the library logger), so embedding the SDK in a larger app never results
    in duplicated or hijacked logging. Safe to call repeatedly.
    """
    library_logger = logging.getLogger(library_logger_name)
    env_level = _level_from_env()
    if env_level is not None:
        library_logger.setLevel(env_level)

    root_logger = logging.getLogger()
    host_configured = bool(root_logger.handlers) or any(
        not isinstance(handler, logging.NullHandler) for handler in library_logger.handlers
    )
    if host_configured:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    library_logger.addHandler(handler)
    if env_level is None:
        library_logger.setLevel(default_level)
    library_logger.propagate = False
