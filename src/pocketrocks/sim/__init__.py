"""Local simulation toolkit: train and evaluate bots offline against the
canonical rules, using the exact same bot class you deploy live."""

from . import sample_bots
from .batch_engine import BatchScores, BatchSimEngine, BatchTurnOutcome
from .benchmark import BenchmarkSummary, BotProvider, BotStats, run_games
from .chart_generator import generate_valid_chart, generate_valid_charts
from .engine import SimEngine, TurnOutcome
from .game import DecisionRecord, GameResult, LocalGame, bot_label
from .ruleset import PaymentRule, Ruleset, compute_paid, resolve_chart
from .state import RevealRecord, ScoreRow, TurnRecord

__all__ = [
    "BatchScores",
    "BatchSimEngine",
    "BatchTurnOutcome",
    "BenchmarkSummary",
    "BotProvider",
    "BotStats",
    "DecisionRecord",
    "GameResult",
    "LocalGame",
    "PaymentRule",
    "RevealRecord",
    "Ruleset",
    "ScoreRow",
    "SimEngine",
    "TurnOutcome",
    "TurnRecord",
    "bot_label",
    "compute_paid",
    "generate_valid_chart",
    "generate_valid_charts",
    "resolve_chart",
    "run_games",
    "sample_bots",
]
