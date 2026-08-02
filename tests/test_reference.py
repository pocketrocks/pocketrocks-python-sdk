from __future__ import annotations

from pocketrocks import (
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
from pocketrocks.internal.bot_wire_v2.constants import (
    bot_wire_action_ids,
    bot_wire_objective_definitions,
)


def test_suit_values_and_labels() -> None:
    assert [int(s) for s in Suit] == [1, 2, 3, 4, 5]
    assert Suit.BRICK.label == "Brick"
    assert Suit.WHEAT.label == "Wheat"
    assert SUIT_LABELS == {1: "Brick", 2: "Wood", 3: "Ore", 4: "Sheep", 5: "Wheat"}


def test_action_ids_match_wire_protocol() -> None:
    # The public enum must not drift from the vendored wire ids.
    assert {a.value for a in ActionId} == set(bot_wire_action_ids.values())
    assert bot_wire_action_ids["Loan10"] == ActionId.LOAN10


def test_describe_action_is_human_readable() -> None:
    assert "gains $10" in describe_action(ActionId.LOAN10)
    assert "plus $10" in describe_action(ActionId.INVEST10)
    assert describe_action(999) == "Unknown action id 999"


def test_describe_suit() -> None:
    assert describe_suit(3) == "Ore"
    assert describe_suit(0) == "Unknown suit id 0"


def test_objectives_cover_the_full_catalog() -> None:
    assert len(OBJECTIVES) == len(bot_wire_objective_definitions)
    assert set(OBJECTIVES) == {int(k) for k in bot_wire_objective_definitions}


def test_pattern_objective() -> None:
    obj = OBJECTIVES[1]
    assert isinstance(obj, ObjectiveInfo)
    assert obj.slug == "prod-any-same2"
    assert obj.pattern == "same2"
    assert obj.requirement is None
    assert describe_objective(1) == "Any two cards of a single suit"


def test_suit_specific_objective_requirement_and_description() -> None:
    # objective 6 = pair of suit 1 (Brick)
    obj = OBJECTIVES[6]
    assert obj.pattern is None
    assert obj.requirement == (2, 0, 0, 0, 0)
    assert describe_objective(6) == "2x Brick"
    # objective 11 = one each of suits 1 and 2
    assert describe_objective(11) == "1x Brick + 1x Wood"


def test_describe_objective_unknown() -> None:
    assert describe_objective(0) == "Unknown objective id 0"


def test_objective_payouts_match_catalog() -> None:
    # Sourced from the upstream objective catalog: pattern payouts, and
    # suit-specific pairs pay 5 while three-different sets pay 10.
    expected: dict[int, int] = {1: 5, 2: 10, 3: 5, 4: 10, 5: 15}
    for oid in range(6, 21):  # same2 (6-10) + diff2 (11-20)
        expected[oid] = 5
    for oid in range(21, 31):  # diff3 (21-30)
        expected[oid] = 10
    assert {oid: OBJECTIVES[oid].payout for oid in OBJECTIVES} == expected


def test_objective_payout_helper() -> None:
    assert objective_payout(5) == 15
    assert objective_payout(21) == 10
    assert objective_payout(999) is None
