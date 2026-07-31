import logging

from pocketrocks._version import __version__
from pocketrocks.bot import PocketRocksBot
from pocketrocks.reference import (
    ACTION_DESCRIPTIONS,
    OBJECTIVES,
    SUIT_LABELS,
    ActionId,
    ObjectiveInfo,
    Suit,
    describe_action,
    describe_objective,
    describe_suit,
    objective_payout,
)
from pocketrocks.types import BotDecision, DecisionContext, RuntimeEvent

# Library best practice: never emit "no handler" warnings or force output just
# by importing. run() installs a real handler for the script use case.
logging.getLogger("pocketrocks").addHandler(logging.NullHandler())

__all__ = [  # noqa: RUF022 -- grouped by category (version/core/reference docs), not
    # alphabetical; the grouping is the point.
    # Version
    "__version__",
    # Core
    "PocketRocksBot",
    "BotDecision",
    "DecisionContext",
    "RuntimeEvent",
    # Reference / decoder ring for the raw ids in DecisionContext
    "ActionId",
    "Suit",
    "ObjectiveInfo",
    "OBJECTIVES",
    "SUIT_LABELS",
    "ACTION_DESCRIPTIONS",
    "describe_action",
    "describe_suit",
    "describe_objective",
    "objective_payout",
]
