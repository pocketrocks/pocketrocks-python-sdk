from __future__ import annotations

import json
from pathlib import Path

import pytest

from pocketrocks._version import RULES_VERSION
from pocketrocks.sim.traces import replay_trace

_TRACES = sorted((Path(__file__).parent.parent / "fixtures" / "botsdk" / "traces").glob("*.json"))


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())


def test_fixtures_exist() -> None:
    assert len(_TRACES) >= 30


@pytest.mark.parametrize("path", _TRACES, ids=lambda p: p.stem)
def test_trace_conformance(path: Path) -> None:
    trace = _load(path)
    assert trace["rulesVersion"] == RULES_VERSION, (
        "Fixture rules version does not match this engine's RULES_VERSION. "
        "Regenerate fixtures (main repo: yarn workspace @pocketrocks/server "
        "fixtures:bot-sdk) and port the rules change before shipping."
    )
    replay_trace(trace)
