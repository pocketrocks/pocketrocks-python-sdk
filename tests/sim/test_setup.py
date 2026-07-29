from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from pocketrocks.internal.bot_wire_v2 import GameSetupEvent
from pocketrocks.sim.constants import (
    ACTION_DECK,
    ITEM_DECK_SUITS,
    VALUE_CHARTS,
    objective_pattern_met,
)
from pocketrocks.sim.engine import SimEngine

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "botsdk"


def _trace(name: str) -> dict[str, Any]:
    return json.loads((_FIXTURES / "traces" / f"{name}.json").read_text())


def test_action_deck_composition() -> None:
    assert len(ACTION_DECK) == 30
    assert Counter(ACTION_DECK) == {
        "Auction1": 12, "Auction2": 8, "Loan10": 3, "Loan20": 2, "Invest5": 3, "Invest10": 2,
    }
    # Order matters for shuffle parity: type-grouped, matching createActionDeck().
    assert ACTION_DECK[:12] == ("Auction1",) * 12
    assert ACTION_DECK[12:20] == ("Auction2",) * 8


def test_item_deck_order() -> None:
    assert ITEM_DECK_SUITS == tuple(s for s in (1, 2, 3, 4, 5) for _ in range(6))


def test_value_charts() -> None:
    assert VALUE_CHARTS["A"] == (0, 4, 8, 12, 16, 20)
    assert VALUE_CHARTS["B"] == (20, 16, 12, 8, 4, 0)
    assert VALUE_CHARTS["C"] == (0, 2, 5, 9, 14, 20)
    assert VALUE_CHARTS["D"] == (20, 18, 15, 11, 6, 0)
    assert VALUE_CHARTS["E"] == (0, 4, 10, 18, 6, 0)


def test_objective_patterns() -> None:
    assert objective_pattern_met(1, [2, 0, 0, 0, 0])          # any pair
    assert not objective_pattern_met(1, [1, 1, 1, 1, 1])
    assert objective_pattern_met(5, [2, 2, 0, 0, 0])          # two pairs
    assert objective_pattern_met(6, [2, 0, 0, 0, 0])          # pair of suit 1
    assert not objective_pattern_met(6, [0, 2, 0, 0, 0])
    assert objective_pattern_met(21, [1, 1, 1, 0, 0])         # set 1-2-3


def test_setup_matches_ts_trace() -> None:
    trace = _trace("trace-000")
    setup = trace["setup"]
    engine = SimEngine(int(trace["playerCount"]), str(trace["seed"]),
                       value_chart=str(trace["valueChartKey"]))
    assert engine.debug_item_deck_order == tuple(setup["itemDeckOrder"])
    assert engine.debug_action_deck_order == tuple(setup["actionDeckOrder"])
    assert [p.hand_suits for p in engine.players] == setup["handsBySeat"]
    assert list(engine.initial_info_counts) == setup["initialInfoCounts"]
    assert engine.tiebreak_seat == setup["tiebreakSeat"]
    assert [oid for oid, _ in engine.active_objectives] == setup["objectiveWireIds"]
    assert [p.cash for p in engine.players] == [setup["startingCash"]] * int(trace["playerCount"])


def test_setup_event_is_first() -> None:
    engine = SimEngine(3, "seed-x")
    event = engine.events[0]
    assert isinstance(event, GameSetupEvent)
    assert event.player_count == 3
    assert event.starting_cash == 30
    assert event.value_chart == (0, 4, 8, 12, 16, 20)
    assert event.initial_tiebreak_seat == engine.tiebreak_seat
    assert len(event.objective_ids) == 4


def test_upcoming_starts_with_two() -> None:
    engine = SimEngine(5, "seed-y")
    assert len(engine.upcoming) == 2
    assert len(engine.pile) == 30 - 5 * 3 - 2
