from __future__ import annotations

from pocketrocks.sim import LocalGame, run_games
from pocketrocks.sim.sample_bots import AlwaysPassBot, GreedyValueBot, RandomBot, ValueTraderBot


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
