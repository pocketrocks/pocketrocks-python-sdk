from __future__ import annotations

from collections import Counter

from pocketrocks.sim.constants import (
    ACTION_DECK,
    ITEM_DECK_SUITS,
    VALUE_CHARTS,
    objective_pattern_met,
)


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
