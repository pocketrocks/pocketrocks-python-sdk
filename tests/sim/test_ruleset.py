from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest

from pocketrocks.sim import PaymentRule, Ruleset, compute_paid, resolve_chart
from pocketrocks.sim.constants import VALUE_CHARTS
from pocketrocks.sim.ruleset import (
    CHART_CELL_CAP,
    MAX_TURNS,
    SUM_FLOOR,
    VALLEY_MIN_CELL,
    VALLEY_SUM_FLOOR,
    compute_paid_batch,
)

_ENVELOPE = cast(
    "dict[str, Any]",
    json.loads((Path(__file__).parent.parent / "fixtures" / "chart_envelope.json").read_text()),
)


# --- envelope fixture -----------------------------------------------------------


def test_envelope_constants_match_fixture() -> None:
    constants = _ENVELOPE["constants"]
    assert constants["cell_cap"] == CHART_CELL_CAP
    assert constants["sum_floor"] == SUM_FLOOR
    assert constants["valley_sum_floor"] == VALLEY_SUM_FLOOR
    assert constants["valley_min_cell"] == VALLEY_MIN_CELL
    assert constants["max_turns"] == MAX_TURNS


@pytest.mark.parametrize("values", _ENVELOPE["accept"], ids=lambda v: ",".join(map(str, v)))
def test_envelope_accepts(values: list[int]) -> None:
    assert resolve_chart(values) == tuple(values)


@pytest.mark.parametrize(
    ("values", "reason"),
    [(case["values"], case["reason"]) for case in _ENVELOPE["reject"]],
    ids=[",".join(map(str, case["values"])) for case in _ENVELOPE["reject"]],
)
def test_envelope_rejects_naming_the_constraint(values: list[float], reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        # The fixture deliberately carries non-integer cells; the runtime check is the point.
        resolve_chart(cast("list[int]", values))


def test_fixed_chart_e_is_the_global_minimum_sum() -> None:
    # E sums to 38 and is the reason the floor moved from 40 to 38: every fixed
    # chart must itself pass the envelope, and E must sit exactly on the floor.
    assert sum(VALUE_CHARTS["E"]) == SUM_FLOOR
    assert resolve_chart((0, 4, 10, 18, 6, 0)) == VALUE_CHARTS["E"]
    with pytest.raises(ValueError, match="sum floor"):
        resolve_chart((0, 4, 10, 17, 6, 0))


@pytest.mark.parametrize("key", list(VALUE_CHARTS))
def test_every_fixed_chart_passes_the_envelope(key: str) -> None:
    assert resolve_chart(VALUE_CHARTS[key]) == VALUE_CHARTS[key]


# --- resolve_chart ---------------------------------------------------------------


def test_resolve_chart_by_key_is_case_insensitive() -> None:
    assert resolve_chart("A") == VALUE_CHARTS["A"]
    assert resolve_chart("e") == VALUE_CHARTS["E"]


def test_resolve_chart_rejects_unknown_key_naming_the_fix() -> None:
    with pytest.raises(ValueError, match="A-E") as excinfo:
        resolve_chart("F")
    assert "6 integers" in str(excinfo.value)


def test_resolve_chart_rejects_bool_cells() -> None:
    with pytest.raises(ValueError, match="integer"):
        resolve_chart((True, 4, 8, 12, 16, 20))


def test_resolve_chart_accepts_numpy_integer_cells() -> None:
    cells = np.asarray([0, 4, 8, 12, 16, 20], dtype=np.int16)
    resolved = resolve_chart(cells)
    assert resolved == (0, 4, 8, 12, 16, 20)
    assert all(type(cell) is int for cell in resolved)


# --- compute_paid ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule", "bids", "expected"),
    [
        ("first-price", (30, 10, 0), 30),
        ("second-price", (30, 10, 0), 10),
        ("first-price", (7, 0, 0), 7),
        ("second-price", (7, 0, 0), 0),  # a single positive bid pays 0
        ("first-price", (0, 0, 0), 0),
        ("second-price", (0, 0, 0), 0),
        ("first-price", (5, 5, 5), 5),
        ("second-price", (5, 5, 5), 5),  # tie: runner-up equals the top bid
        ("second-price", (0, 12, 12, 3, 1), 12),
        ("second-price", (4, 9, 2, 1, 0), 4),
    ],
)
def test_compute_paid(rule: PaymentRule, bids: tuple[int, ...], expected: int) -> None:
    assert compute_paid(rule, bids) == expected


def test_compute_paid_does_not_pick_the_winner() -> None:
    # Winner selection (tiebreak order) is the engine's job; the price is a pure
    # function of the multiset of bids, so permuting the seats changes nothing.
    assert compute_paid("second-price", (10, 30, 0)) == compute_paid("second-price", (30, 0, 10))


def test_compute_paid_rejects_unknown_rule() -> None:
    with pytest.raises(ValueError, match="payment rule"):
        compute_paid("third-price", (1, 2, 3))  # type: ignore[arg-type]  # the point of the test


def test_compute_paid_batch_agrees_with_scalar() -> None:
    rng = np.random.default_rng(7)
    bids = rng.integers(0, 40, size=(64, 5), dtype=np.int16)
    bids[::4] = 0  # some all-zero rows
    bids[1::4, 1:] = 0  # some single-positive-bid rows
    second_price = np.arange(64) % 3 == 0
    paid = compute_paid_batch(second_price, bids)
    assert paid.dtype == np.int16
    for row in range(64):
        rule: PaymentRule = "second-price" if second_price[row] else "first-price"
        assert int(paid[row]) == compute_paid(rule, bids[row].tolist())


# --- Ruleset ---------------------------------------------------------------------


def test_ruleset_defaults_are_the_shipped_rules() -> None:
    ruleset = Ruleset(player_count=3)
    assert ruleset.value_chart == "A"
    assert ruleset.payment_rule == "first-price"
    assert ruleset.objectives_enabled is True
    assert ruleset.chart == VALUE_CHARTS["A"]


def test_ruleset_normalises_key_case_and_list_cells() -> None:
    assert Ruleset(player_count=3, value_chart="b").value_chart == "B"
    # A list is not the annotated type, but a user will pass one; it must normalise.
    inline = Ruleset(player_count=4, value_chart=[-4, 8, 16, 18, 8, -4])  # type: ignore[arg-type]  # see above
    assert inline.value_chart == (-4, 8, 16, 18, 8, -4)
    assert inline.chart == (-4, 8, 16, 18, 8, -4)


def test_ruleset_is_frozen_and_hashable() -> None:
    inline = Ruleset(player_count=3, value_chart=(0, 4, 8, 12, 16, 20), payment_rule="second-price")
    keyed = Ruleset(player_count=3, value_chart="A", payment_rule="second-price")
    with pytest.raises(AttributeError):
        inline.payment_rule = "first-price"  # type: ignore[misc]  # frozen is the point
    # Same cells, but a key and an inline selection are different selections.
    assert len({inline, keyed}) == 2


@pytest.mark.parametrize("player_count", [2, 6])
def test_ruleset_rejects_player_count_outside_3_to_5(player_count: int) -> None:
    with pytest.raises(ValueError, match="3-5"):
        Ruleset(player_count=player_count)


def test_ruleset_rejects_bad_chart_and_bad_rule() -> None:
    with pytest.raises(ValueError, match="sum floor"):
        Ruleset(player_count=3, value_chart=(0, 2, 4, 6, 8, 10))
    with pytest.raises(ValueError, match="payment rule"):
        Ruleset(player_count=3, payment_rule="vickrey")  # type: ignore[arg-type]  # the point


def test_ruleset_chart_label_distinguishes_inline_charts() -> None:
    assert Ruleset(player_count=3, value_chart="C").chart_label == "C"
    inline = Ruleset(player_count=3, value_chart=(-4, 8, 16, 18, 8, -4))
    assert inline.chart_label == "custom(-4,8,16,18,8,-4)"
