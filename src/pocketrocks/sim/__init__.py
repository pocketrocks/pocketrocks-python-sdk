"""Local simulation toolkit: train and evaluate bots offline against the
canonical rules, using the exact same bot class you deploy live."""

from .engine import SimEngine, TurnOutcome
from .game import DecisionRecord, GameResult, LocalGame, bot_label
from .state import RevealRecord, ScoreRow, TurnRecord

__all__ = [
    "DecisionRecord",
    "GameResult",
    "LocalGame",
    "RevealRecord",
    "ScoreRow",
    "SimEngine",
    "TurnOutcome",
    "TurnRecord",
    "bot_label",
]
