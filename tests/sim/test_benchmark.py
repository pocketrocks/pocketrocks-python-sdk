from __future__ import annotations

import pytest

from pocketrocks import BotDecision, DecisionContext, PocketRocksBot
from pocketrocks.sim import run_games


class MaxBot(PocketRocksBot):
    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        if context.decision_kind == "submitBid":
            return BotDecision.submit_bid(context.legal_max_amount or 0)
        return BotDecision.select_info_to_reveal(0)


class PassBot(PocketRocksBot):
    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        return BotDecision.pass_turn()


def _pass_factory() -> PassBot:
    return PassBot()


_counting_calls: list[int] = []


def _counting_factory() -> PassBot:
    _counting_calls.append(1)
    return PassBot()


def test_seat_rotation_and_aggregation() -> None:
    summary = run_games([MaxBot, PassBot, PassBot], 6, rotate_seats=True)
    assert summary.n_games == 6
    max_stats = summary.bots[0]
    assert max_stats.games == 6
    # With rotation over 6 games and 3 seats, each provider sat each seat twice.
    assert max_stats.games_by_seat == (2, 2, 2)
    assert sum(stats.wins for stats in summary.bots) == 6


def test_reproducible_with_same_seeds() -> None:
    a = run_games([MaxBot, PassBot, PassBot], 3, seeds=["x", "y", "z"])
    b = run_games([MaxBot, PassBot, PassBot], 3, seeds=["x", "y", "z"])
    assert [s.mean_score for s in a.bots] == [s.mean_score for s in b.bots]


def test_factory_provider_works() -> None:
    summary = run_games([MaxBot, _pass_factory, PassBot], 2)
    assert summary.bots[1].label == "PassBot"


def test_instance_provider_rejected_with_workers() -> None:
    with pytest.raises(ValueError, match="workers=1"):
        run_games([MaxBot(), PassBot, PassBot], 2, workers=2)


def test_instance_provider_allowed_single_worker() -> None:
    bot = MaxBot()
    summary = run_games([bot, PassBot, PassBot], 2, workers=1)
    assert summary.bots[0].games == 2


def test_parallel_smoke() -> None:
    summary = run_games([MaxBot, PassBot, PassBot], 4, workers=2)
    assert summary.n_games == 4
    assert sum(stats.wins for stats in summary.bots) == 4


def test_factory_called_once_per_game_not_for_labeling() -> None:
    _counting_calls.clear()
    summary = run_games([MaxBot, _counting_factory, PassBot], 3, workers=1)
    assert len(_counting_calls) == 3
    assert summary.bots[1].label == "PassBot"


def test_seeds_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="seeds length"):
        run_games([MaxBot, PassBot, PassBot], 3, seeds=["only-one"])


def test_large_run_streams_without_retaining_results() -> None:
    # n_games=101 exceeds _KEEP_RESULTS_MAX (100), so results must be
    # dropped rather than accumulated -- this is what keeps peak memory
    # bounded for large benchmark runs.
    summary = run_games([PassBot, PassBot, PassBot], 101, workers=1)
    assert summary.results == ()
    assert summary.n_games == 101
    assert sum(stats.wins for stats in summary.bots) == 101
    assert all(stats.games == 101 for stats in summary.bots)


def test_parallel_window_submits_replacements() -> None:
    # 6 games with workers=2 → in-flight window of 4, so at least two games
    # are submitted as replacements after earlier results are consumed.
    # Verifies the bounded-window path aggregates every game exactly once.
    summary = run_games([MaxBot, PassBot, PassBot], 6, workers=2)
    assert summary.n_games == 6
    assert sum(stats.wins for stats in summary.bots) == 6
    assert all(stats.games_by_seat == (2, 2, 2) for stats in summary.bots)
    assert len(summary.results) == 6  # kept (n_games <= 100), in game order
    assert all(result is not None for result in summary.results)
