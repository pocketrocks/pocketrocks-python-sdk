"""Monte Carlo evaluation: many seeded games, seat rotation, worker processes.

Providers may be instances, classes, or zero-arg factories. Classes/factories
are constructed fresh per game *inside the worker*, so a factory that memoizes
an expensive load (e.g. RL model weights) in a module-level global pays the
load once per worker process — the intended pattern for evaluating a frozen
policy. Bare instances are only allowed with ``workers=1``: with multiple
workers the instance would be pickled into each worker and any state it
accumulates would be lost, so that combination is a hard error, never a
silently wrong result. Collect trajectories from ``record_decisions=True``
results, not from bot instance state.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import cast

from pocketrocks._update_check import maybe_warn_if_stale
from pocketrocks.bot import PocketRocksBot

from .game import GameResult, LocalGame, bot_label

BotProvider = PocketRocksBot | type[PocketRocksBot] | Callable[[], PocketRocksBot]

_KEEP_RESULTS_MAX = 100


def _instantiate(provider: BotProvider) -> PocketRocksBot:
    if isinstance(provider, PocketRocksBot):
        return provider
    return provider()


def _provider_label(provider: BotProvider) -> str:
    if isinstance(provider, PocketRocksBot):
        return bot_label(provider)
    if isinstance(provider, type):
        return provider.__name__
    return bot_label(provider())


@dataclass(frozen=True)
class BotStats:
    label: str
    games: int
    wins: int
    win_rate: float
    mean_score: float
    wins_by_seat: tuple[int, ...]
    games_by_seat: tuple[int, ...]


@dataclass(frozen=True)
class BenchmarkSummary:
    n_games: int
    bots: tuple[BotStats, ...]
    results: tuple[GameResult, ...]

    def __str__(self) -> str:
        lines = [f"{'bot':<24} {'win%':>6} {'mean':>8}  wins by seat"]
        for stats in self.bots:
            seats = "/".join(str(w) for w in stats.wins_by_seat)
            lines.append(
                f"{stats.label:<24} {100 * stats.win_rate:>5.1f}% {stats.mean_score:>8.2f}  {seats}"
            )
        return "\n".join(lines)


def _play_one_game(
    providers: Sequence[BotProvider],
    seed: str,
    rotation: int,
    value_chart: str,
    record_decisions: bool,
    decision_budget_ms: int,
) -> GameResult:
    n = len(providers)
    # Provider p sits at seat (p + rotation) % n.
    bots_by_seat = [_instantiate(providers[(seat - rotation) % n]) for seat in range(n)]
    return LocalGame(
        bots_by_seat,
        seed=seed,
        value_chart=value_chart,
        record_decisions=record_decisions,
        decision_budget_ms=decision_budget_ms,
    ).play()


def run_games(
    providers: Sequence[BotProvider],
    n_games: int,
    *,
    seeds: Sequence[str | int] | None = None,
    rotate_seats: bool = True,
    workers: int = 1,
    value_chart: str = "A",
    record_decisions: bool = False,
    decision_budget_ms: int = 60_000,
) -> BenchmarkSummary:
    maybe_warn_if_stale()
    n = len(providers)
    if not 3 <= n <= 5:
        raise ValueError("PocketRocks supports 3-5 players")
    if workers > 1:
        for provider in providers:
            if isinstance(provider, PocketRocksBot):
                raise ValueError(
                    "Bot instances require workers=1: with multiple workers the instance "
                    "is pickled into each worker process and any state it accumulates is "
                    "lost. Pass the class or a zero-arg factory instead, and collect "
                    "trajectories via record_decisions=True."
                )
    seed_list = (
        [str(s) for s in seeds] if seeds is not None else [f"game-{i}" for i in range(n_games)]
    )
    if len(seed_list) != n_games:
        raise ValueError("seeds length must equal n_games")
    rotations = [(i % n if rotate_seats else 0) for i in range(n_games)]

    # Aggregate incrementally instead of collecting every GameResult into a
    # list: with many games and small results retained (kept=()), holding
    # every result until the end would peak memory at O(n_games) regardless
    # of what the summary ultimately returns. ``keep`` decides up front
    # whether results are retained at all.
    keep = record_decisions or n_games <= _KEEP_RESULTS_MAX
    kept_results: list[GameResult | None] = [None] * n_games if keep else []

    wins = [0] * n
    score_sums = [0.0] * n
    wins_by_seat = [[0] * n for _ in range(n)]
    games_by_seat = [[0] * n for _ in range(n)]
    game0_seats: tuple[str, ...] | None = None

    def _aggregate(game_index: int, result: GameResult) -> None:
        nonlocal game0_seats
        if game_index == 0:
            # Derive labels from the bots that actually played (game 0's
            # seated instances) instead of instantiating each provider a
            # second time: a stateful factory would report a stale/wrong
            # label here, and the documented memoize-in-worker factory
            # pattern would otherwise pay an extra un-memoized load in the
            # parent process just to read a name.
            game0_seats = result.seats
        rotation = rotations[game_index]
        for provider_index in range(n):
            seat = (provider_index + rotation) % n
            games_by_seat[provider_index][seat] += 1
            score_sums[provider_index] += result.scores[seat].total
            if result.winner_seat == seat:
                wins[provider_index] += 1
                wins_by_seat[provider_index][seat] += 1
        if keep:
            kept_results[game_index] = result

    if workers <= 1:
        for i in range(n_games):
            result = _play_one_game(
                providers, seed_list[i], rotations[i], value_chart,
                record_decisions, decision_budget_ms
            )
            _aggregate(i, result)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            future_to_index = {
                pool.submit(
                    _play_one_game, list(providers), seed_list[i], rotations[i],
                    value_chart, record_decisions, decision_budget_ms
                ): i
                for i in range(n_games)
            }
            for future in as_completed(list(future_to_index)):
                # pop() drops our strong reference to the completed Future:
                # a Future retains its result internally, so keeping all of
                # them in the dict would hold every GameResult until the end
                # anyway, defeating the streaming aggregation.
                i = future_to_index.pop(future)
                _aggregate(i, future.result())

    if game0_seats is not None:
        labels = [game0_seats[(p + rotations[0]) % n] for p in range(n)]
    else:
        labels = [_provider_label(provider) for provider in providers]

    stats = tuple(
        BotStats(
            label=labels[p],
            games=n_games,
            wins=wins[p],
            win_rate=wins[p] / n_games if n_games else 0.0,
            mean_score=score_sums[p] / n_games if n_games else 0.0,
            wins_by_seat=tuple(wins_by_seat[p]),
            games_by_seat=tuple(games_by_seat[p]),
        )
        for p in range(n)
    )
    # Once fully populated (keep=True implies every index 0..n_games-1 was
    # assigned a real GameResult by _aggregate above), the None placeholders
    # are gone -- cast narrows the type back for BenchmarkSummary.results.
    kept = cast("tuple[GameResult, ...]", tuple(kept_results)) if keep else ()
    return BenchmarkSummary(n_games=n_games, bots=stats, results=kept)
