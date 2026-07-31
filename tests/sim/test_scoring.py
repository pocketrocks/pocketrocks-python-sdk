from __future__ import annotations

from pocketrocks.sim.engine import SimEngine


def test_score_formula() -> None:
    engine = SimEngine(3, "score")  # chart A, initial counts from seed
    p = engine.players[0]
    p.cash = 10
    p.won_suits = [1, 1]
    p.loans = [10]
    p.investments = [(7, 5)]
    p.objective_wire_ids = [1]  # any-pair objective pays 5
    row = engine.score()[0]
    suit1_value = engine.value_chart[min(engine.initial_info_counts[0], 5)]
    assert row.items_value == 2 * suit1_value
    assert row.investments_value == 12
    assert row.loans_value == 10
    assert row.objectives_value == 5
    assert row.total == 10 + row.items_value + 12 - 10 + 5


def test_six_dealt_info_cards_scores_top_chart_value() -> None:
    engine = SimEngine(3, "clamp")
    engine.initial_info_counts = (6, 0, 0, 0, 0)
    engine.players[0].won_suits = [1]
    row = engine.score()[0]
    assert row.items_value == engine.value_chart[5]  # clamped, not 0


def test_ranking_ties_break_by_seat() -> None:
    engine = SimEngine(3, "rank")
    for p in engine.players:
        p.cash = 30
        p.won_suits = []
        p.loans = []
        p.investments = []
        p.objective_wire_ids = []
    assert engine.ranking() == [0, 1, 2]


def test_scalar_scoring_preserves_duplicate_objective_ids() -> None:
    engine = SimEngine(3, "duplicate-objectives")
    engine.players[0].objective_wire_ids[:] = [1, 1]

    row = engine.score()[0]

    assert row.objectives_value == 10
