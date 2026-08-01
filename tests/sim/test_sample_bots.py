from __future__ import annotations

import pytest

from pocketrocks import ActionId, DecisionContext, Suit
from pocketrocks.sim import LocalGame, run_games
from pocketrocks.sim.sample_bots import AlwaysPassBot, GreedyValueBot, RandomBot, ValueTraderBot
from pocketrocks.testing import scenario


def test_sample_bots_complete_a_game() -> None:
    result = LocalGame(
        [RandomBot(seed=1), AlwaysPassBot(), GreedyValueBot(), ValueTraderBot()], seed=5
    ).play()
    assert len(result.scores) == 4


def test_sample_bots_work_as_class_providers() -> None:
    summary = run_games([GreedyValueBot, ValueTraderBot, AlwaysPassBot], 4, workers=1)
    assert summary.n_games == 4


def test_random_bot_deterministic_per_seed() -> None:
    a = LocalGame([RandomBot(seed=9), AlwaysPassBot(), AlwaysPassBot()], seed=2).play()
    b = LocalGame([RandomBot(seed=9), AlwaysPassBot(), AlwaysPassBot()], seed=2).play()
    assert a.history == b.history


@pytest.mark.parametrize(
    ("value_chart", "expected_bid"),
    [
        ((0, 4, 8, 12, 16, 20), 4),
        ((20, 16, 12, 8, 4, 0), 10),
        ((0, 2, 5, 9, 14, 20), 2),
        ((20, 18, 15, 11, 6, 0), 10),
        ((0, 4, 10, 18, 6, 0), 4),
    ],
)
async def test_value_trader_prices_known_suits_from_active_value_chart(
    value_chart: tuple[int, int, int, int, int, int], expected_bid: int
) -> None:
    context: DecisionContext = (
        scenario(players=3, starting_cash=30, value_chart=value_chart)
        .turn(ActionId.AUCTION1, resources=(Suit.BRICK, 0))
        .deciding(seat=0, hand=[Suit.BRICK, Suit.ORE])
        .to_context()
    )

    assert (await ValueTraderBot().choose_decision(context)).value == expected_bid


async def test_value_trader_bids_on_unknown_suits_when_chart_values_zero_count() -> None:
    context = (
        scenario(
            players=3,
            starting_cash=30,
            value_chart=(20, 16, 12, 8, 4, 0),
        )
        .turn(ActionId.AUCTION1, resources=(Suit.BRICK, 0))
        .deciding(seat=0, hand=[Suit.ORE, Suit.SHEEP])
        .to_context()
    )

    assert (await ValueTraderBot().choose_decision(context)).value == 10
