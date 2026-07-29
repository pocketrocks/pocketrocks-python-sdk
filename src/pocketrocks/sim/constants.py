"""Canonical rules constants, mirrored from the server's rules engine.

Sources: ``apps/server/src/rules/constants.ts`` (decks, ruleset numbers) and
``packages/shared/src/index.ts`` (value charts). Objective patterns reuse the
vendored wire-protocol definitions so sim and live reconstruction can never
disagree. Any change here is a rules change: bump ``RULES_VERSION`` and
regenerate the golden traces.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from pocketrocks.internal.bot_wire_v2.constants import (
    bot_wire_action_ids,
    bot_wire_objective_definitions,
)

VALUE_CHARTS: dict[str, tuple[int, ...]] = {
    "A": (0, 4, 8, 12, 16, 20),
    "B": (20, 16, 12, 8, 4, 0),
    "C": (0, 2, 5, 9, 14, 20),
    "D": (20, 18, 15, 11, 6, 0),
    "E": (0, 4, 10, 18, 6, 0),
}

ACTION_DECK: tuple[str, ...] = (
    ("Auction1",) * 12 + ("Auction2",) * 8 + ("Loan10",) * 3
    + ("Loan20",) * 2 + ("Invest5",) * 3 + ("Invest10",) * 2
)
ITEM_DECK_SUITS: tuple[int, ...] = tuple(s for s in (1, 2, 3, 4, 5) for _ in range(6))

STARTING_CASH: dict[int, int] = {3: 30, 4: 25, 5: 20}
INFO_CARDS_PER_PLAYER: dict[int, int] = {3: 5, 4: 4, 5: 3}
OBJECTIVES_PER_GAME = 4
LOAN_PRINCIPAL: dict[str, int] = {"Loan10": 10, "Loan20": 20}
INVEST_PAYOUT: dict[str, int] = {"Invest5": 5, "Invest10": 10}
ACTION_WIRE_IDS: dict[str, int] = dict(bot_wire_action_ids)
ALL_OBJECTIVE_WIRE_IDS: tuple[int, ...] = tuple(range(1, 31))


def objective_pattern_met(objective_wire_id: int, counts_by_suit: Sequence[int]) -> bool:
    """Whether a won-resource count vector satisfies an objective. Mirrors both
    the server's ``objectives.ts`` and the SDK's wire reconstruction."""
    definition = bot_wire_objective_definitions[str(objective_wire_id)]
    pattern = definition.get("pattern")
    counts = list(counts_by_suit)
    if pattern == "same2":
        return any(c >= 2 for c in counts)
    if pattern == "same3":
        return any(c >= 3 for c in counts)
    if pattern == "different3":
        return sum(c > 0 for c in counts) >= 3
    if pattern == "different4":
        return sum(c > 0 for c in counts) >= 4
    if pattern == "twoPairs4":
        return sum(c >= 2 for c in counts) >= 2
    requirement = cast("list[int]", definition["requirement"])
    return all(counts[i] >= needed for i, needed in enumerate(requirement))
