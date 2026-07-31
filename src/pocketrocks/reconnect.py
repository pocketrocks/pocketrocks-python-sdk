from __future__ import annotations

import random
from collections.abc import Callable
from typing import Literal

from pocketrocks.config import BotConfig
from pocketrocks.constants import reconnect_jitter_fraction

#: Which reconnect schedule applies. ``transient`` = network blip / server
#: restart (recover fast, low ceiling). ``rejected`` = retryable handshake
#: rejection, i.e. 403 deactivated (back off to a much higher ceiling so a
#: deactivated bot barely taxes the server while it waits to be reactivated).
ReconnectOutcome = Literal["transient", "rejected"]


def _with_jitter(delay_seconds: float) -> float:
    """Apply +/- ``reconnect_jitter_fraction`` jitter so bots do not reconnect
    in lockstep. Centered on ``delay_seconds`` to preserve the average cadence."""
    spread = delay_seconds * reconnect_jitter_fraction
    return delay_seconds + random.uniform(-spread, spread)  # noqa: S311 -- timing jitter, not security-sensitive


class ReconnectPolicy:
    """The single owner of the reconnect backoff schedule.

    Exponential backoff from ``reconnect_base_delay_seconds``, doubling each
    attempt, clamped to a per-outcome ceiling (see :data:`ReconnectOutcome`).
    :meth:`next_delay` applies jitter and returns the seconds to sleep before the
    next attempt; :meth:`reset` returns to the base delay after a successful
    connection so repeated deactivate/reactivate cycles reconnect promptly.

    ``jitter`` is injectable so tests can pass an identity function and assert the
    exact schedule; production uses randomized jitter.
    """

    def __init__(
        self,
        config: BotConfig,
        *,
        jitter: Callable[[float], float] = _with_jitter,
    ) -> None:
        self._base = config.reconnect_base_delay_seconds
        self._transient_ceiling = config.reconnect_max_delay_seconds
        self._rejected_ceiling = config.rejected_reconnect_max_delay_seconds
        self._jitter = jitter
        self._delay = self._base

    def reset(self) -> None:
        """Return to the base delay (call after a successful connection)."""
        self._delay = self._base

    def next_delay(self, outcome: ReconnectOutcome) -> float:
        """Seconds to sleep before the next attempt, then advance the schedule.

        Clamps the current delay to ``outcome``'s ceiling *before* sleeping, so a
        transient blip after prior rejections does not inherit the slow ceiling and
        leave the bot offline for the long interval.
        """
        ceiling = self._rejected_ceiling if outcome == "rejected" else self._transient_ceiling
        self._delay = min(self._delay, ceiling)
        sleep_seconds = self._jitter(self._delay)
        self._delay = min(self._delay * 2, ceiling)
        return sleep_seconds
