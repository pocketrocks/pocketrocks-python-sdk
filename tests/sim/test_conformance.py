from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from pocketrocks._version import RULES_VERSION
from pocketrocks.sim.constants import VALUE_CHARTS
from pocketrocks.sim.ruleset import PAYMENT_RULES
from pocketrocks.sim.traces import replay_trace, trace_ruleset

# Vendored from the main repo's exporter; provenance and corpus layout in
# tests/fixtures/botsdk/README.md.
_TRACES = sorted((Path(__file__).parent.parent / "fixtures" / "botsdk" / "traces").glob("*.json"))
_PLAYER_COUNTS = (3, 4, 5)

# The rules version at which each slice of the ruleset space was last changed.
# A trace is a valid oracle for its slice from that version onward: rules
# version 2 added the payment rule and inline (custom) charts without changing
# how a first-price fixed-chart game plays, so the version-1 traces still pin
# that slice exactly. Anything second-price or custom-chart must have been
# recorded by an exporter that knew those fields, i.e. at version 2 or later.
# Bumping RULES_VERSION for a change that alters first-price fixed-chart play
# must raise the first entry too, which fails every existing trace until it is
# regenerated (see CONTRIBUTING.md, "Releasing a rules change").
_MIN_RULES_VERSION_FIRST_PRICE_FIXED_CHART = 1
_MIN_RULES_VERSION_RULESET_VARIANTS = 2


def _load(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text()))


def required_rules_version(trace: dict[str, Any]) -> int:
    ruleset = trace_ruleset(trace)
    if ruleset.payment_rule == "first-price" and isinstance(ruleset.value_chart, str):
        return _MIN_RULES_VERSION_FIRST_PRICE_FIXED_CHART
    return _MIN_RULES_VERSION_RULESET_VARIANTS


def assert_rules_version_compatible(trace: dict[str, Any]) -> None:
    recorded = int(trace["rulesVersion"])
    assert recorded <= RULES_VERSION, (
        f"Fixture rules version {recorded} is newer than this engine's RULES_VERSION "
        f"{RULES_VERSION}: port the rules change (see CONTRIBUTING.md) before shipping."
    )
    assert recorded >= required_rules_version(trace), (
        f"Fixture rules version {recorded} predates the rules that define its ruleset "
        f"({trace_ruleset(trace)}). Regenerate fixtures (main repo: yarn workspace "
        "@pocketrocks/server fixtures:bot-sdk); never edit a fixture by hand."
    )


def test_fixtures_exist() -> None:
    assert len(_TRACES) >= 61


def test_corpus_covers_every_rule_chart_and_player_count() -> None:
    # Mirrors the exporter's own coverage guard: the PAIR of (rule, chart, count)
    # must be present, not just every chart somewhere, so a re-vendored corpus
    # that quietly dropped a cell fails here instead of unpinning that slice.
    traces = [_load(path) for path in _TRACES]
    cells = {
        (trace["paymentRule"], trace["valueChartKey"], int(trace["playerCount"]))
        for trace in traces
    }
    for rule in PAYMENT_RULES:
        for key in VALUE_CHARTS:
            for count in _PLAYER_COUNTS:
                assert (rule, key, count) in cells, (
                    f"no {rule} trace on fixed chart {key} at {count} players"
                )
        custom = [
            trace
            for trace in traces
            if trace["paymentRule"] == rule and trace["valueChartKey"] == "custom"
        ]
        assert custom, f"no {rule} trace on a custom chart"
        # Negative cells are why custom decks need their own traces (scoring
        # must handle a negative total); the exporter refuses a seed base that
        # draws none, and so does this side.
        assert any(any(cell < 0 for cell in trace["valueChart"]) for trace in custom), (
            f"no {rule} trace on a custom chart with a negative cell"
        )
    # An engine that selects, claims or scores objectives when they are off must
    # fail conformance, which needs traces recorded with them off.
    assert any(not trace["objectivesEnabled"] for trace in traces)


def test_every_ruleset_slice_has_a_minimum_version_no_newer_than_the_engine() -> None:
    assert (
        _MIN_RULES_VERSION_FIRST_PRICE_FIXED_CHART
        <= _MIN_RULES_VERSION_RULESET_VARIANTS
        <= RULES_VERSION
    )


def _synthetic_trace(**overrides: Any) -> dict[str, Any]:
    trace: dict[str, Any] = {
        "rulesVersion": 1,
        "playerCount": 3,
        "valueChartKey": "A",
        "valueChart": [0, 4, 8, 12, 16, 20],
    }
    trace.update(overrides)
    return trace


def test_version_gate_accepts_first_price_fixed_chart_traces_from_version_one() -> None:
    assert_rules_version_compatible(_synthetic_trace())
    assert_rules_version_compatible(_synthetic_trace(rulesVersion=RULES_VERSION))


def test_version_gate_rejects_traces_newer_than_the_engine() -> None:
    with pytest.raises(AssertionError, match="newer than this engine"):
        assert_rules_version_compatible(_synthetic_trace(rulesVersion=RULES_VERSION + 1))


@pytest.mark.parametrize(
    "overrides",
    [
        {"paymentRule": "second-price"},
        {"valueChartKey": "custom", "valueChart": [-20, 0, 20, 20, 10, 8]},
    ],
    ids=["second-price", "custom-chart"],
)
def test_version_gate_requires_version_two_for_ruleset_variants(overrides: dict[str, Any]) -> None:
    with pytest.raises(AssertionError, match="predates"):
        assert_rules_version_compatible(_synthetic_trace(**overrides))
    assert_rules_version_compatible(_synthetic_trace(rulesVersion=2, **overrides))


def test_trace_ruleset_reads_rule_and_inline_chart() -> None:
    assert trace_ruleset(_synthetic_trace()).payment_rule == "first-price"
    variant = trace_ruleset(
        _synthetic_trace(
            paymentRule="second-price",
            valueChartKey="custom",
            valueChart=[-20, 0, 20, 20, 10, 8],
        )
    )
    assert variant.payment_rule == "second-price"
    assert variant.value_chart == (-20, 0, 20, 20, 10, 8)


@pytest.mark.parametrize("path", _TRACES, ids=lambda p: p.stem)
def test_trace_conformance(path: Path) -> None:
    trace = _load(path)
    assert_rules_version_compatible(trace)
    replay_trace(trace)
