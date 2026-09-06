from __future__ import annotations

import pytest

from pocketrocks import ActionId, DecisionContext, Suit
from pocketrocks.sim import LocalGame, PaymentRule, Ruleset, run_games
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


def _value_trader_spot(payment_rule: PaymentRule) -> DecisionContext:
    # Estimate 20, cash 30. First-price caps the bid at a third of cash (10);
    # second-price bids the estimate (20).
    return (
        scenario(
            players=3,
            starting_cash=30,
            value_chart=(20, 16, 12, 8, 4, 0),
            payment_rule=payment_rule,
        )
        .turn(ActionId.AUCTION1, resources=(Suit.BRICK, 0))
        .deciding(seat=0, hand=[Suit.ORE, Suit.SHEEP])
        .to_context()
    )


def _greedy_spot(payment_rule: PaymentRule) -> DecisionContext:
    # Cash 7 and an estimate of 7 (one Brick in hand on a 0,7,... chart): the
    # first-price shade rounds the bid down to 6; second-price bids the full 7.
    return (
        scenario(
            players=3, starting_cash=7, value_chart=(0, 7, 13, 20, 10, 0), payment_rule=payment_rule
        )
        .turn(ActionId.AUCTION1, resources=(Suit.BRICK, 0))
        .deciding(seat=0, hand=[Suit.BRICK])
        .to_context()
    )


async def test_value_bots_read_the_payment_rule_from_the_context() -> None:
    # Identical inputs; only ``context.payment_rule`` differs. No constructor knob.
    first, second = _value_trader_spot("first-price"), _value_trader_spot("second-price")
    assert first.payment_rule == "first-price"
    assert second.payment_rule == "second-price"
    assert (await ValueTraderBot().choose_decision(first)).value == 10
    assert (await ValueTraderBot().choose_decision(second)).value == 20

    first, second = _greedy_spot("first-price"), _greedy_spot("second-price")
    assert (await GreedyValueBot().choose_decision(first)).value == 6
    assert (await GreedyValueBot().choose_decision(second)).value == 7


async def test_value_bots_constructor_rule_overrides_the_context() -> None:
    # The knob is an override for experiments: it wins over the game's rule in
    # both directions.
    first, second = _value_trader_spot("first-price"), _value_trader_spot("second-price")
    assert (await ValueTraderBot(payment_rule="second-price").choose_decision(first)).value == 20
    assert (await ValueTraderBot(payment_rule="first-price").choose_decision(second)).value == 10

    first, second = _greedy_spot("first-price"), _greedy_spot("second-price")
    assert (await GreedyValueBot(payment_rule="second-price").choose_decision(first)).value == 7
    assert (await GreedyValueBot(payment_rule="first-price").choose_decision(second)).value == 6


def test_sample_bots_complete_a_second_price_custom_chart_game() -> None:
    # No knobs: the bots learn the rule from the sim's context, end to end.
    ruleset = Ruleset(
        player_count=4, value_chart=(-4, 8, 16, 18, 8, -4), payment_rule="second-price"
    )
    result = LocalGame(
        [RandomBot(seed=1), AlwaysPassBot(), GreedyValueBot(), ValueTraderBot()],
        seed=5,
        ruleset=ruleset,
    ).play()
    assert len(result.scores) == 4


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
