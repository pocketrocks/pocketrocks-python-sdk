from __future__ import annotations

import random

import numpy as np
import pytest

from pocketrocks.sim import (
    BatchSimEngine,
    PaymentRule,
    Ruleset,
    SimEngine,
    generate_valid_chart,
    generate_valid_charts,
    resolve_chart,
)
from pocketrocks.sim.ruleset import CHART_CELL_CAP, CHART_CELLS, is_valley_chart

# `random.Random` here drives a test fixture, not anything security-sensitive.
# ruff: noqa: S311


class _AlwaysInvalidRng(random.Random):
    """Yields ``(20, -20, 20, -20, ...)`` forever: four turning points, never valid."""

    def __init__(self) -> None:
        super().__init__(0)
        self.calls = 0

    def randint(self, a: int, b: int) -> int:
        self.calls += 1
        return CHART_CELL_CAP if self.calls % 2 else -CHART_CELL_CAP


# --- envelope -------------------------------------------------------------------


@pytest.mark.parametrize(
    "rng", [random.Random(1), np.random.default_rng(1)], ids=["random", "numpy"]
)
def test_every_generated_chart_passes_the_envelope(
    rng: random.Random | np.random.Generator,
) -> None:
    for _ in range(200):
        chart = generate_valid_chart(rng)
        assert len(chart) == CHART_CELLS
        assert all(type(cell) is int for cell in chart)
        assert all(abs(cell) <= CHART_CELL_CAP for cell in chart)
        # resolve_chart is the one validator; a generated chart must be its own resolution.
        assert resolve_chart(chart) == chart


def test_generated_charts_reach_negative_cells_and_valleys() -> None:
    # Seeded, so this is a fixed set of charts rather than a statistical claim.
    charts = generate_valid_charts(random.Random(3), 300)
    assert any(min(chart) < 0 for chart in charts), "no negative cell in 300 charts"
    assert any(is_valley_chart(chart) for chart in charts), "no valley in 300 charts"
    assert any(max(chart) == CHART_CELL_CAP for chart in charts)


# --- determinism ----------------------------------------------------------------


def test_same_seed_same_charts_random() -> None:
    first = generate_valid_charts(random.Random(42), 25)
    second = generate_valid_charts(random.Random(42), 25)
    assert first == second
    assert first != generate_valid_charts(random.Random(43), 25)


def test_same_seed_same_charts_numpy() -> None:
    first = generate_valid_charts(np.random.default_rng(42), 25)
    second = generate_valid_charts(np.random.default_rng(42), 25)
    assert first == second
    assert first != generate_valid_charts(np.random.default_rng(43), 25)


def test_batch_is_the_same_stream_as_repeated_single_draws() -> None:
    rng = random.Random(9)
    batch = generate_valid_charts(random.Random(9), 10)
    assert batch == tuple(generate_valid_chart(rng) for _ in range(10))


# --- bounded tries --------------------------------------------------------------


def test_gives_up_after_max_tries_naming_the_fix() -> None:
    rng = _AlwaysInvalidRng()
    with pytest.raises(RuntimeError, match="max_tries"):
        generate_valid_chart(rng, max_tries=50)
    # Exactly max_tries candidates of CHART_CELLS cells each were drawn, no more.
    assert rng.calls == 50 * CHART_CELLS


def test_batch_gives_up_after_max_tries_per_chart() -> None:
    with pytest.raises(RuntimeError, match="max_tries"):
        generate_valid_charts(_AlwaysInvalidRng(), 3, max_tries=10)


@pytest.mark.parametrize("max_tries", [0, -1])
def test_rejects_non_positive_max_tries(max_tries: int) -> None:
    with pytest.raises(ValueError, match="max_tries"):
        generate_valid_chart(random.Random(0), max_tries=max_tries)


def test_rejects_negative_count() -> None:
    with pytest.raises(ValueError, match="n"):
        generate_valid_charts(random.Random(0), -1)


def test_zero_count_draws_nothing() -> None:
    rng = _AlwaysInvalidRng()
    assert generate_valid_charts(rng, 0) == ()
    assert rng.calls == 0


def test_rejects_unknown_rng_type_naming_the_fix() -> None:
    with pytest.raises(TypeError, match=r"random\.Random"):
        generate_valid_chart(object())  # type: ignore[arg-type]  # the wrong type is the point


@pytest.mark.parametrize("seed", range(10))
def test_acceptance_rate_makes_1000_tries_plenty(seed: int) -> None:
    # The docstring claims ~0.5% acceptance (about 1 in 180 candidates). This
    # pins the loose consequence for fixed seeds only — no statistical assert.
    assert resolve_chart(generate_valid_chart(random.Random(seed), max_tries=1_000))


# --- generated charts drive the engines -----------------------------------------


def _first_negative_cell_chart(seed: int) -> tuple[int, ...]:
    rng = random.Random(seed)
    for _ in range(1_000):
        chart = generate_valid_chart(rng)
        if min(chart) < 0:
            return chart
    raise AssertionError("no negative-cell chart in 1000 draws")


def _play_out(engine: SimEngine) -> None:
    seats = range(len(engine.players))
    while engine.flip_action() is not None:
        outcome = engine.resolve([engine.legal_max_bid(seat) // 2 for seat in seats])
        if outcome.reveal_needed is not None:
            engine.apply_reveal(outcome.winner_seat, 0, auto=outcome.reveal_needed == "auto")


@pytest.mark.parametrize("rule", ["first-price", "second-price"])
def test_negative_cell_chart_plays_to_completion(rule: PaymentRule) -> None:
    chart = _first_negative_cell_chart(seed=11)
    engine = SimEngine(
        3,
        "custom-chart",
        ruleset=Ruleset(player_count=3, value_chart=chart, payment_rule=rule),
    )
    assert engine.value_chart == chart
    _play_out(engine)
    assert engine.game_over
    rows = engine.score()
    assert len(rows) == 3
    assert all(isinstance(row.total, int) for row in rows)
    assert sorted(engine.ranking()) == [0, 1, 2]


def test_mixed_batch_of_fixed_and_generated_charts_runs_to_completion() -> None:
    generated = generate_valid_charts(np.random.default_rng(5), 4)
    selections: tuple[str | tuple[int, ...], ...] = ("A", *generated, "E", (20, 16, 10, 2, 14, 20))
    rules: tuple[PaymentRule, ...] = ("first-price", "second-price") * 3 + ("first-price",)
    rulesets = tuple(
        Ruleset(player_count=3, value_chart=selection, payment_rule=rule)
        for selection, rule in zip(selections, rules, strict=True)
    )
    engine = BatchSimEngine.start(
        seeds=tuple(f"row-{index}" for index in range(len(rulesets))),
        rulesets=rulesets,
    )
    # Each row carries its own resolved cells, never a key or a sentinel.
    for row, ruleset in enumerate(rulesets):
        assert engine.value_charts[row].tolist() == list(ruleset.chart)
    while engine.flip_actions().any():
        legal = engine.legal_max_bids()
        outcome = engine.resolve_bids(legal // 2)
        reveals = np.full(engine.batch_size, -1, dtype=np.int8)
        reveals[outcome.reveal_modes > 0] = 0
        engine.apply_reveals(reveals)
    assert engine.game_over_mask().all()
    assert engine.scores().total.shape == (len(rulesets), 3)
