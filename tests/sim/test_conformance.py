from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from pocketrocks._version import RULES_VERSION
from pocketrocks.sim.traces import replay_trace, trace_ruleset

_TRACES = sorted((Path(__file__).parent.parent / "fixtures" / "botsdk" / "traces").glob("*.json"))

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
    assert len(_TRACES) >= 30


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
