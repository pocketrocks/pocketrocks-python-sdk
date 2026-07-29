from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pocketrocks.sim.rng import shuffled

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "botsdk"


def _shuffle_cases() -> list[dict[str, Any]]:
    data = json.loads((_FIXTURES / "shuffles.json").read_text())
    return list(data["cases"])


@pytest.mark.parametrize("case", _shuffle_cases(), ids=lambda c: f"{c['seed']}-{c['size']}")
def test_matches_ts_shuffle(case: dict[str, Any]) -> None:
    size = int(case["size"])
    assert shuffled(list(range(size)), str(case["seed"])) == case["permutation"]


def test_same_seed_same_result() -> None:
    assert shuffled(list(range(30)), "abc") == shuffled(list(range(30)), "abc")


def test_input_not_mutated() -> None:
    items = list(range(10))
    shuffled(items, "abc")
    assert items == list(range(10))
