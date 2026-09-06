"""Custom value chart generator: rejection sampling under the constraint envelope.

Mirrors ``generateValidChart`` in ``packages/shared/src/chartGenerator.ts``:
draw six integer cells uniformly from ``[-CHART_CELL_CAP, CHART_CELL_CAP]`` and
keep the first candidate the envelope accepts. Because every candidate is
uniform over the sampling box, the accepted charts are uniform over the valid
set — the same distribution the server deals in custom-chart rooms.

The accept test is ``resolve_chart`` itself, so there is exactly one validator
and a generated chart is, by construction, its own resolution. What is *not*
shared with the server is the RNG stream (ADR 2026-09-04, decision 5): the
sim's charts are shape-equivalent to live ones, never the same sequence, and
replay never regenerates because the server persists resolved cells.

Roughly 0.5% of candidates pass (about 1 in 180 under ``SUM_FLOOR = 38``;
measured, not derived), so a draw costs a couple of hundred candidates —
about 1.5 ms per chart in pure Python, ~1.5 s for a 1,024-row batch.
``max_tries`` bounds that loop so a degenerate RNG raises instead of spinning.
"""

from __future__ import annotations

import random

import numpy as np

from .ruleset import CHART_CELL_CAP, CHART_CELLS, resolve_chart

#: Any seeded RNG the sim already uses: ``random.Random`` (the sample bots) or
#: ``numpy.random.Generator`` (batch training code). No global RNG is ever read.
ChartRng = random.Random | np.random.Generator

#: Default candidate budget per chart. At ~0.5% acceptance the odds of a fair
#: RNG exhausting it are negligible; hitting it means the RNG is broken.
DEFAULT_MAX_TRIES = 10_000

_RNG_FIX = "pass a seeded random.Random(seed) or numpy.random.default_rng(seed) as rng"


def _draw_candidate(rng: ChartRng) -> tuple[int, ...]:
    """Six cells uniform in the envelope's cell box. Derived from the cap, not
    transcribed, so a lab retune of ``CHART_CELL_CAP`` moves the sampler too."""
    if isinstance(rng, np.random.Generator):
        cells = rng.integers(-CHART_CELL_CAP, CHART_CELL_CAP, size=CHART_CELLS, endpoint=True)
        return tuple(int(cell) for cell in cells)
    if isinstance(rng, random.Random):
        return tuple(rng.randint(-CHART_CELL_CAP, CHART_CELL_CAP) for _ in range(CHART_CELLS))
    raise TypeError(f"unsupported rng {type(rng).__name__}; {_RNG_FIX}")


def generate_valid_chart(rng: ChartRng, *, max_tries: int = DEFAULT_MAX_TRIES) -> tuple[int, ...]:
    """Generate one custom value chart inside the constraint envelope.

    :param rng: a seeded ``random.Random`` or ``numpy.random.Generator``. The
        same seeded RNG yields the same charts; the stream is advanced by every
        candidate drawn, accepted or not.
    :param max_tries: candidates to try before giving up. Acceptance is ~0.5%,
        so the default of 10,000 is only reached by a broken RNG.
    :returns: 6 plain ``int`` cells, already validated — ``resolve_chart(chart)``
        returns it unchanged, and ``Ruleset(value_chart=chart)`` accepts it.
    :raises RuntimeError: when ``max_tries`` candidates were all rejected.
    """
    if max_tries < 1:
        raise ValueError(f"max_tries must be at least 1, got {max_tries}")
    for _ in range(max_tries):
        candidate = _draw_candidate(rng)
        try:
            return resolve_chart(candidate)
        except ValueError:
            # Rejected by the envelope (turns or a sum floor): draw the next candidate.
            continue
    raise RuntimeError(
        f"no valid value chart in {max_tries} candidates; the envelope accepts about 1 in 180 "
        f"uniform draws, so check the rng yields varied integers in "
        f"[-{CHART_CELL_CAP}, {CHART_CELL_CAP}] or raise max_tries"
    )


def generate_valid_charts(
    rng: ChartRng,
    n: int,
    *,
    max_tries: int = DEFAULT_MAX_TRIES,
) -> tuple[tuple[int, ...], ...]:
    """``n`` charts from one RNG stream, for per-row batch rules.

    Identical to calling ``generate_valid_chart`` ``n`` times on the same
    ``rng``; ``max_tries`` applies per chart. Pair each with a ``Ruleset`` and
    hand the tuple to ``BatchSimEngine.start(rulesets=...)``.
    """
    if n < 0:
        raise ValueError(f"n must be non-negative, got {n}")
    return tuple(generate_valid_chart(rng, max_tries=max_tries) for _ in range(n))
