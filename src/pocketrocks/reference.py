"""Decoder ring for the raw IDs in :class:`~pocketrocks.DecisionContext`.

``DecisionContext`` hands your bot bare integers — action ids, suit ids, and
objective ids. This module is the *supported, stable* way to interpret them, so
you never have to reach into ``pocketrocks.internal`` (which may change without
notice). The underlying values are sourced from the vendored wire-protocol
package, so they stay in lockstep with the protocol.

Example::

    from pocketrocks import DecisionContext, Suit, ActionId, describe_objective

    def summarize(context: DecisionContext) -> None:
        if context.current_action_id == ActionId.LOAN10:
            ...
        wheat_on_table = context.won_resource_counts_by_suit[Suit.WHEAT - 1]
        for oid in context.objective_ids:
            print(oid, describe_objective(oid))
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import cast

from pocketrocks.internal.bot_wire.constants import (
    bot_wire_action_ids,
    bot_wire_objective_definitions,
)


class Suit(IntEnum):
    """The five resource suits. Values match the suit ids in ``DecisionContext``.

    Suit-indexed arrays (e.g. ``won_resource_counts_by_suit``) are ``0``-based,
    so a suit's slot is ``Suit.BRICK - 1``.
    """

    BRICK = 1
    WOOD = 2
    ORE = 3
    SHEEP = 4
    WHEAT = 5

    @property
    def label(self) -> str:
        """Human-readable name, e.g. ``"Brick"``."""
        return self.name.capitalize()


class ActionId(IntEnum):
    """The auctionable actions. Values match ``DecisionContext.current_action_id``."""

    AUCTION1 = 1
    AUCTION2 = 2
    LOAN10 = 3
    LOAN20 = 4
    INVEST5 = 5
    INVEST10 = 6


#: Suit id (1-5) -> human-readable name.
SUIT_LABELS: dict[int, str] = {suit.value: suit.label for suit in Suit}

#: Action id (1-6) -> plain-English description of what winning it does.
ACTION_DESCRIPTIONS: dict[int, str] = {
    ActionId.AUCTION1: (
        "Auction for 1 resource card. The winner pays the auction price and gains the "
        "offered resource."
    ),
    ActionId.AUCTION2: (
        "Auction for 2 resource cards. The winner pays the auction price and gains both "
        "offered resources."
    ),
    ActionId.LOAN10: (
        "Loan 10. The winner pays the auction price now, immediately gains $10 cash, and "
        "repays $10 during scoring."
    ),
    ActionId.LOAN20: (
        "Loan 20. The winner pays the auction price now, immediately gains $20 cash, and "
        "repays $20 during scoring."
    ),
    ActionId.INVEST5: (
        "Invest 5. The winner locks the auction price and gets it back plus $5 during scoring."
    ),
    ActionId.INVEST10: (
        "Invest 10. The winner locks the auction price and gets it back plus $10 during scoring."
    ),
}
# "The auction price" rather than "their bid": under the first-price payment
# rule the two are the same, under second-price the winner pays the runner-up
# bid. The highest bidder wins under either rule (see ``pocketrocks.sim.Ruleset``).


@dataclass(frozen=True, slots=True)
class ObjectiveInfo:
    """Everything the SDK knows about one objective.

    :param objective_id: Wire id, 1-30. Matches the values in
        ``DecisionContext.objective_ids`` and ``owned_objective_ids_by_seat``.
    :param slug: Stable string identifier from the protocol, e.g.
        ``"prod-any-same2"``.
    :param description: Plain-English summary of what completes it.
    :param payout: Fixed cash the owner is paid for completing it. Known upfront
        and the same in every game.
    :param pattern: For flexible objectives, the pattern name (``"same2"``,
        ``"same3"``, ``"different3"``, ``"different4"``, ``"twoPairs4"``);
        ``None`` for suit-specific objectives.
    :param requirement: For suit-specific objectives, the per-suit counts needed
        (index ``i`` is ``Suit(i + 1)``); ``None`` for pattern objectives.
    """

    objective_id: int
    slug: str
    description: str
    payout: int
    pattern: str | None
    requirement: tuple[int, ...] | None


_PATTERN_DESCRIPTIONS: dict[str, str] = {
    "same2": "Any two cards of a single suit",
    "same3": "Any three cards of a single suit",
    "different3": "One card each of any three different suits",
    "different4": "One card each of any four different suits",
    "twoPairs4": "Two cards each of any two suits",
}


#: Payout for each flexible (pattern) objective.
_PATTERN_PAYOUTS: dict[str, int] = {
    "same2": 5,
    "same3": 10,
    "different3": 5,
    "different4": 10,
    "twoPairs4": 15,
}


def _describe(definition: dict[str, object]) -> str:
    pattern = definition.get("pattern")
    if isinstance(pattern, str):
        return _PATTERN_DESCRIPTIONS[pattern]
    requirement = cast("list[int]", definition["requirement"])
    parts = [
        f"{count}x {Suit(index + 1).label}" for index, count in enumerate(requirement) if count
    ]
    return " + ".join(parts)


def _payout(definition: dict[str, object]) -> int:
    pattern = definition.get("pattern")
    if isinstance(pattern, str):
        return _PATTERN_PAYOUTS[pattern]
    # Suit-specific objectives: a set of three different suits pays 10, while the
    # pairs (two of one suit, or one each of two suits) pay 5. Mirrors upstream.
    requirement = cast("list[int]", definition["requirement"])
    return 10 if sum(requirement) >= 3 else 5


def _build_objectives() -> dict[int, ObjectiveInfo]:
    objectives: dict[int, ObjectiveInfo] = {}
    for key, definition in bot_wire_objective_definitions.items():
        pattern = definition.get("pattern")
        requirement = definition.get("requirement")
        objectives[int(key)] = ObjectiveInfo(
            objective_id=int(key),
            slug=cast(str, definition["id"]),
            description=_describe(definition),
            payout=_payout(definition),
            pattern=pattern if isinstance(pattern, str) else None,
            requirement=(
                tuple(cast("list[int]", requirement)) if requirement is not None else None
            ),
        )
    return objectives


#: Objective id (1-30) -> :class:`ObjectiveInfo`.
OBJECTIVES: dict[int, ObjectiveInfo] = _build_objectives()


def describe_action(action_id: int) -> str:
    """Return a plain-English description of ``action_id`` (see ``ActionId``)."""
    return ACTION_DESCRIPTIONS.get(action_id, f"Unknown action id {action_id}")


def describe_suit(suit_id: int) -> str:
    """Return the human-readable name of ``suit_id`` (see ``Suit``)."""
    try:
        return Suit(suit_id).label
    except ValueError:
        return f"Unknown suit id {suit_id}"


def describe_objective(objective_id: int) -> str:
    """Return a plain-English description of ``objective_id`` (see ``OBJECTIVES``)."""
    info = OBJECTIVES.get(objective_id)
    return info.description if info is not None else f"Unknown objective id {objective_id}"


def objective_payout(objective_id: int) -> int | None:
    """Return the fixed payout for ``objective_id``, or ``None`` if unknown.

    Payouts are known upfront and identical in every game, so you can score
    objectives directly, e.g. ``objective_payout(oid)`` for any id in
    ``DecisionContext.objective_ids``.
    """
    info = OBJECTIVES.get(objective_id)
    return info.payout if info is not None else None


# Guard against the enums drifting from the vendored wire ids. This is cheap and
# only runs once at import; it fails loudly if the protocol renumbers actions.
# A plain `assert` would vanish under `python -O`, silently disabling the guard
# it exists to provide, so raise explicitly instead.
if {action.value for action in ActionId} != set(bot_wire_action_ids.values()):
    raise AssertionError("ActionId enum values drifted from the vendored wire ids")

# Guard the payout mapping too: if upstream adds/reshapes objectives, the known
# distribution changes and this trips instead of silently mis-scoring.
_PAYOUT_DISTRIBUTION: dict[int, int] = {}
for _info in OBJECTIVES.values():
    _PAYOUT_DISTRIBUTION[_info.payout] = _PAYOUT_DISTRIBUTION.get(_info.payout, 0) + 1
if _PAYOUT_DISTRIBUTION != {5: 17, 10: 12, 15: 1}:
    raise AssertionError(f"objective payout distribution changed: {_PAYOUT_DISTRIBUTION}")
