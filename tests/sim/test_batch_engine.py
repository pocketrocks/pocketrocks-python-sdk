from __future__ import annotations

import numpy as np
import pytest

from pocketrocks.sim.batch_engine import BatchSimEngine
from pocketrocks.sim.constants import ACTION_WIRE_IDS, VALUE_CHARTS
from pocketrocks.sim.engine import SimEngine
from pocketrocks.sim.ruleset import PaymentRule, Ruleset

# A negative-cell hump sitting exactly on the sum floor, and a negative-tailed hump.
_NEGATIVE_CHARTS: tuple[tuple[int, ...], ...] = ((-20, 0, 20, 20, 10, 8), (-4, 8, 16, 18, 8, -4))


@pytest.mark.parametrize("player_count", [3, 4, 5])
@pytest.mark.parametrize("value_chart", ["A", "B", "C", "D", "E"])
@pytest.mark.parametrize("objectives_enabled", [False, True])
def test_batch_setup_matches_scalar_engine(
    player_count: int,
    value_chart: str,
    objectives_enabled: bool,
) -> None:
    seeds = (
        f"batch-setup-{player_count}-{value_chart}-{objectives_enabled}-0",
        f"batch-setup-{player_count}-{value_chart}-{objectives_enabled}-1",
    )
    batch = BatchSimEngine.start(
        player_count=player_count,
        seeds=seeds,
        value_charts=(value_chart, value_chart),
        objectives_enabled=(objectives_enabled, objectives_enabled),
    )

    assert batch.batch_size == 2
    assert batch.player_count == player_count
    for game_index, seed in enumerate(seeds):
        scalar = SimEngine(
            player_count,
            seed,
            value_chart=value_chart,
            objectives_enabled=objectives_enabled,
        )
        hand_size = len(scalar.players[0].hand_suits)
        assert batch.item_decks[game_index].tolist() == list(scalar.debug_item_deck_order)
        assert batch.action_decks[game_index].tolist() == [
            ACTION_WIRE_IDS[action] for action in scalar.debug_action_deck_order
        ]
        assert batch.hand_cards[game_index, :, :hand_size].tolist() == [
            player.hand_suits for player in scalar.players
        ]
        assert not batch.hand_cards[game_index, :, hand_size:].any()
        assert batch.initial_info_counts[game_index].tolist() == list(scalar.initial_info_counts)
        assert batch.cash[game_index].tolist() == [player.cash for player in scalar.players]
        assert int(batch.tiebreak_seats[game_index]) == scalar.tiebreak_seat
        assert batch.objective_ids[game_index][batch.objective_ids[game_index] > 0].tolist() == [
            objective_id for objective_id, _seat in scalar.active_objectives
        ]
        assert batch.upcoming[game_index].tolist() == scalar.upcoming
        assert batch.won_counts[game_index].tolist() == [[0, 0, 0, 0, 0] for _ in scalar.players]
        assert batch.revealed_counts[game_index].tolist() == [
            [0, 0, 0, 0, 0] for _ in scalar.players
        ]


def test_batch_setup_validates_homogeneous_inputs() -> None:
    with pytest.raises(ValueError, match="at least one seed"):
        BatchSimEngine.start(player_count=3, seeds=())
    with pytest.raises(ValueError, match="value_charts"):
        BatchSimEngine.start(
            player_count=3,
            seeds=("one", "two"),
            value_charts=("A",),
        )
    with pytest.raises(ValueError, match="objectives_enabled"):
        BatchSimEngine.start(
            player_count=3,
            seeds=("one", "two"),
            objectives_enabled=(True,),
        )
    with pytest.raises(ValueError, match="3-5"):
        BatchSimEngine.start(player_count=2, seeds=("one",))
    with pytest.raises(ValueError, match="payment_rules"):
        BatchSimEngine.start(
            player_count=3,
            seeds=("one", "two"),
            payment_rules=("second-price",),
        )
    with pytest.raises(ValueError, match="player_count is required"):
        BatchSimEngine.start(seeds=("one",))


def test_batch_setup_validates_rules_and_charts_naming_the_constraint() -> None:
    with pytest.raises(ValueError, match="payment rule"):
        BatchSimEngine.start(
            player_count=3,
            seeds=("one",),
            payment_rules=("third-price",),  # type: ignore[arg-type]  # the point of the test
        )
    with pytest.raises(ValueError, match="sum floor"):
        BatchSimEngine.start(player_count=3, seeds=("one",), value_charts=((0, 2, 4, 6, 8, 10),))
    with pytest.raises(ValueError, match="A-E"):
        BatchSimEngine.start(player_count=3, seeds=("one",), value_charts=("F",))


def test_batch_start_accepts_rulesets_or_per_row_sequences_but_not_both() -> None:
    rulesets = (
        Ruleset(player_count=4, value_chart="B", payment_rule="second-price"),
        Ruleset(player_count=4, value_chart=_NEGATIVE_CHARTS[0], objectives_enabled=False),
    )
    from_rulesets = BatchSimEngine.start(seeds=("one", "two"), rulesets=rulesets)
    from_rows = BatchSimEngine.start(
        player_count=4,
        seeds=("one", "two"),
        value_charts=("b", _NEGATIVE_CHARTS[0]),
        payment_rules=("second-price", "first-price"),
        objectives_enabled=(True, False),
    )
    assert from_rulesets.rulesets == from_rows.rulesets == rulesets
    assert from_rulesets.player_count == 4
    assert from_rulesets.payment_rules == ("second-price", "first-price")
    assert from_rulesets.value_charts.tolist() == [
        list(VALUE_CHARTS["B"]),
        list(_NEGATIVE_CHARTS[0]),
    ]
    assert from_rulesets.objectives_enabled.tolist() == [True, False]
    np.testing.assert_array_equal(from_rulesets.hand_cards, from_rows.hand_cards)

    with pytest.raises(ValueError, match="not both"):
        BatchSimEngine.start(seeds=("one", "two"), rulesets=rulesets, value_charts=("A", "A"))
    with pytest.raises(ValueError, match="rulesets length"):
        BatchSimEngine.start(seeds=("one",), rulesets=rulesets)
    with pytest.raises(ValueError, match="one player count"):
        BatchSimEngine.start(
            seeds=("one", "two"),
            rulesets=(Ruleset(player_count=3), Ruleset(player_count=4)),
        )
    with pytest.raises(ValueError, match="player_count"):
        BatchSimEngine.start(player_count=3, seeds=("one", "two"), rulesets=rulesets)


def test_batch_setup_uses_compact_numeric_arrays() -> None:
    batch = BatchSimEngine.start(player_count=5, seeds=("one", "two"))

    assert batch.cash.dtype == np.int16
    assert batch.hand_cards.dtype == np.uint8
    assert batch.won_counts.dtype == np.uint8
    assert batch.revealed_counts.dtype == np.uint8
    assert batch.objective_ids.dtype == np.int8


def _assert_game_state_matches(
    batch: BatchSimEngine,
    game_index: int,
    scalar: SimEngine,
) -> None:
    assert batch.cash[game_index].tolist() == [player.cash for player in scalar.players]
    assert batch.tiebreak_seats[game_index] == scalar.tiebreak_seat
    assert batch.upcoming[game_index][batch.upcoming[game_index] > 0].tolist() == scalar.upcoming
    assert batch.won_counts[game_index].tolist() == [
        [player.won_suits.count(suit_id) for suit_id in range(1, 6)] for player in scalar.players
    ]
    assert batch.revealed_counts[game_index].tolist() == [
        [player.revealed_suits.count(suit_id) for suit_id in range(1, 6)]
        for player in scalar.players
    ]
    assert [
        tuple(int(card) for card in batch.hand_cards[game_index, seat] if card > 0)
        for seat in range(batch.player_count)
    ] == [tuple(player.hand_suits) for player in scalar.players]
    assert [
        (
            int(batch.objective_ids[game_index, objective_index]),
            (
                None
                if batch.objective_claimants[game_index, objective_index] < 0
                else int(batch.objective_claimants[game_index, objective_index])
            ),
        )
        for objective_index in range(batch.objective_ids.shape[1])
        if batch.objective_ids[game_index, objective_index] > 0
    ] == scalar.active_objectives


@pytest.mark.parametrize("player_count", [3, 4, 5])
def test_batch_transitions_match_scalar_complete_games(player_count: int) -> None:
    seeds = tuple(f"batch-game-{player_count}-{index}" for index in range(7))
    # Fixed keys and inline negative-cell charts side by side, under both rules.
    charts: tuple[str | tuple[int, ...], ...] = (*VALUE_CHARTS, *_NEGATIVE_CHARTS)
    rules: tuple[PaymentRule, ...] = tuple(
        "second-price" if index % 2 else "first-price" for index in range(len(seeds))
    )
    objective_flags = tuple(index % 3 != 1 for index in range(len(seeds)))
    batch = BatchSimEngine.start(
        player_count=player_count,
        seeds=seeds,
        value_charts=charts,
        payment_rules=rules,
        objectives_enabled=objective_flags,
    )
    scalars = [
        SimEngine(
            player_count,
            seed,
            value_chart=charts[index],
            payment_rule=rules[index],
            objectives_enabled=objective_flags[index],
        )
        for index, seed in enumerate(seeds)
    ]
    assert any(rule == "second-price" for rule in batch.payment_rules)

    for turn_index in range(30):
        action_ids = batch.flip_actions()
        for game_index, scalar in enumerate(scalars):
            action = scalar.flip_action()
            expected_id = 0 if action is None else ACTION_WIRE_IDS[action]
            assert int(action_ids[game_index]) == expected_id

        legal_max = batch.legal_max_bids()
        bids = np.zeros((len(seeds), player_count), dtype=np.int16)
        for game_index, scalar in enumerate(scalars):
            if scalar.current_action is None:
                continue
            for seat in range(player_count):
                assert int(legal_max[game_index, seat]) == scalar.legal_max_bid(seat)
                bids[game_index, seat] = ((turn_index + 1) * (game_index + 2) * (seat + 3)) % (
                    scalar.legal_max_bid(seat) + 8
                )

        batch_outcome = batch.resolve_bids(bids)
        reveal_indices = np.full(len(seeds), -1, dtype=np.int8)
        for game_index, scalar in enumerate(scalars):
            if scalar.current_action is None:
                assert batch_outcome.reveal_modes[game_index] == 0
                continue
            outcome = scalar.resolve(bids[game_index].tolist())
            assert int(batch_outcome.winner_seats[game_index]) == outcome.winner_seat
            assert int(batch_outcome.paid[game_index]) == outcome.paid
            assert batch_outcome.effective_bids[game_index].tolist() == list(outcome.effective_bids)
            expected_mode = {"auto": 1, "choice": 2, None: 0}[outcome.reveal_needed]
            assert int(batch_outcome.reveal_modes[game_index]) == expected_mode
            if outcome.reveal_needed == "auto":
                reveal_indices[game_index] = 0
                scalar.apply_reveal(outcome.winner_seat, 0, auto=True)
            elif outcome.reveal_needed == "choice":
                index = (turn_index + game_index) % len(
                    scalar.players[outcome.winner_seat].hand_suits
                )
                reveal_indices[game_index] = index
                scalar.apply_reveal(outcome.winner_seat, index, auto=False)

        batch.apply_reveals(reveal_indices)
        for game_index, scalar in enumerate(scalars):
            _assert_game_state_matches(batch, game_index, scalar)

        if all(scalar.game_over for scalar in scalars):
            break

    scores = batch.scores()
    rankings = batch.rankings()
    for game_index, scalar in enumerate(scalars):
        scalar_rows = scalar.score()
        assert scores.cash[game_index].tolist() == [row.cash for row in scalar_rows]
        assert scores.items[game_index].tolist() == [row.items_value for row in scalar_rows]
        assert scores.objectives[game_index].tolist() == [
            row.objectives_value for row in scalar_rows
        ]
        assert scores.investments[game_index].tolist() == [
            row.investments_value for row in scalar_rows
        ]
        assert scores.loans[game_index].tolist() == [row.loans_value for row in scalar_rows]
        assert scores.total[game_index].tolist() == [row.total for row in scalar_rows]
        assert rankings[game_index].tolist() == scalar.ranking()


def test_invalid_batch_bids_do_not_mutate_state() -> None:
    batch = BatchSimEngine.start(player_count=3, seeds=("one", "two"))
    batch.flip_actions()
    cash_before = batch.cash.copy()
    turn_before = batch.turn_indices.copy()

    with pytest.raises(ValueError, match="shape"):
        batch.resolve_bids(np.zeros((2, 2), dtype=np.int16))
    with pytest.raises(ValueError, match="integer"):
        batch.resolve_bids(np.zeros((2, 3), dtype=np.float64))

    np.testing.assert_array_equal(batch.cash, cash_before)
    np.testing.assert_array_equal(batch.turn_indices, turn_before)


def test_batch_rejects_out_of_phase_bid_calls() -> None:
    batch = BatchSimEngine.start(player_count=3, seeds=("one", "two"))
    bids = np.zeros((2, 3), dtype=np.int16)

    with pytest.raises(RuntimeError, match="flipped action"):
        batch.resolve_bids(bids)
    batch.flip_actions()
    with pytest.raises(RuntimeError, match="already flipped"):
        batch.flip_actions()


def test_batch_rejects_reveals_before_flipped_actions_are_resolved() -> None:
    batch = BatchSimEngine.start(player_count=3, seeds=("one", "two"))
    batch.flip_actions()

    with pytest.raises(RuntimeError, match="resolve"):
        batch.apply_reveals(np.full(2, -1, dtype=np.int8))


def test_scalar_engine_is_a_size_one_batch_facade() -> None:
    engine = SimEngine(3, "scalar-facade")

    assert isinstance(engine._batch, BatchSimEngine)
    assert engine._batch.batch_size == 1
    assert engine._batch.player_count == 3
    assert engine._batch.rulesets == (engine.ruleset,)


def test_scores_are_exact_at_the_envelope_extremes_and_match_scalar() -> None:
    # Every one of the 30 cards scored at -20 or at +20: the widest item value the
    # envelope allows (+/-600). int16 holds it, and the bounds check must not fire.
    chart = (-20, -20, 20, 20, 20, 20)
    batch = BatchSimEngine.start(player_count=3, seeds=("low", "high"), value_charts=(chart, chart))
    batch.initial_info_counts[0] = 0  # every suit indexes cell 0 -> -20
    batch.initial_info_counts[1] = 5  # every suit indexes cell 5 -> +20
    batch.won_counts[:, 0, :] = 6  # seat 0 holds all 30 cards in both rows

    scores = batch.scores()
    assert scores.items.dtype == np.int16
    assert scores.items[0].tolist() == [-600, 0, 0]
    assert scores.items[1].tolist() == [600, 0, 0]
    assert scores.total[0, 0] == 30 - 600
    assert scores.total[1, 0] == 30 + 600
    assert batch.rankings()[0].tolist() == [1, 2, 0]  # the negative seat ranks last

    for row, counts in ((0, (0, 0, 0, 0, 0)), (1, (5, 5, 5, 5, 5))):
        scalar = SimEngine(3, "irrelevant", value_chart=chart)
        scalar.initial_info_counts = counts
        scalar.players[0].won_suits = [suit for suit in range(1, 6) for _ in range(6)]
        rows = scalar.score()
        assert [r.items_value for r in rows] == scores.items[row].tolist()
        assert [r.total for r in rows] == scores.total[row].tolist()


def test_scores_bounds_check_trips_on_a_chart_outside_the_envelope() -> None:
    batch = BatchSimEngine.start(player_count=3, seeds=("corrupt",))
    batch.won_counts[0, 0, :] = 6
    batch.initial_info_counts[0] = 5
    batch.value_charts[0, 5] = 21  # only reachable by mutating state behind resolve_chart

    with pytest.raises(AssertionError, match="envelope bound"):
        batch.scores()
