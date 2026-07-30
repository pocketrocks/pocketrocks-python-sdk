"""Local simulation toolkit: train and evaluate bots offline against the
canonical rules, using the exact same bot class you deploy live."""

from . import sample_bots
from .batch_engine import BatchScores, BatchSimEngine, BatchTurnOutcome
from .benchmark import BenchmarkSummary, BotProvider, BotStats, run_games
from .engine import SimEngine, TurnOutcome
from .game import DecisionRecord, GameResult, LocalGame, bot_label
from .state import RevealRecord, ScoreRow, TurnRecord

__all__ = [
    "BenchmarkSummary",
    "BatchSimEngine",
    "BatchScores",
    "BatchTurnOutcome",
    "BotProvider",
    "BotStats",
    "DecisionRecord",
    "GameResult",
    "LocalGame",
    "RevealRecord",
    "ScoreRow",
    "SimEngine",
    "TurnOutcome",
    "TurnRecord",
    "bot_label",
    "run_games",
    "sample_bots",
]
