"""Golden-trace replay: pin this engine to games played by the real TS engine.

A trace records a full seeded game (raw bids in, everything observable out).
Replaying feeds the recorded raw bids into ``SimEngine`` and asserts the entire
state evolution matches. If the server rules change, regenerate fixtures in the
main repo and re-sync this engine; the ``rulesVersion`` gate in the test suite
keeps the two from silently drifting.
"""

from __future__ import annotations

from typing import Any

from .engine import SimEngine


def replay_trace(trace: dict[str, Any]) -> None:
    setup = trace["setup"]
    engine = SimEngine(
        int(trace["playerCount"]),
        str(trace["seed"]),
        value_chart=str(trace["valueChartKey"]),
    )
    label = f"trace {trace['seed']}"

    assert list(engine.debug_item_deck_order) == setup["itemDeckOrder"], f"{label}: item deck order"
    assert list(engine.debug_action_deck_order) == setup["actionDeckOrder"], (
        f"{label}: action deck order"
    )
    assert [p.hand_suits for p in engine.players] == setup["handsBySeat"], f"{label}: dealt hands"
    assert list(engine.initial_info_counts) == setup["initialInfoCounts"], f"{label}: info counts"
    assert engine.tiebreak_seat == setup["tiebreakSeat"], f"{label}: tiebreak seat"
    assert [oid for oid, _ in engine.active_objectives] == setup["objectiveWireIds"], (
        f"{label}: objective selection"
    )

    for i, turn in enumerate(trace["turns"]):
        where = f"{label} turn {i}"
        action = engine.flip_action()
        assert action == turn["actionType"], f"{where}: flipped action"
        assert list(engine.upcoming) == turn["upcomingBefore"], f"{where}: upcoming"
        outcome = engine.resolve(turn["rawBids"])
        assert list(outcome.effective_bids) == turn["effectiveBids"], f"{where}: effective bids"
        assert outcome.winner_seat == turn["winnerSeat"], f"{where}: winner"
        assert outcome.paid == turn["paid"], f"{where}: paid"
        assert list(outcome.bundle_suits) == turn["bundleSuits"], f"{where}: bundle"
        assert list(outcome.claimed_objective_wire_ids) == turn["claimedObjectiveWireIds"], (
            f"{where}: claimed objectives"
        )
        reveal = turn["reveal"]
        if reveal is None:
            assert outcome.reveal_needed is None, f"{where}: unexpected reveal window"
        elif reveal["auto"]:
            assert outcome.reveal_needed == "auto", f"{where}: expected auto reveal"
            record = engine.apply_reveal(reveal["seat"], 0, auto=True)
            assert record.suit == reveal["suit"], f"{where}: auto-revealed suit"
        else:
            assert outcome.reveal_needed == "choice", f"{where}: expected reveal choice"
            record = engine.apply_reveal(reveal["seat"], reveal["handIndex"], auto=False)
            assert record.suit == reveal["suit"], f"{where}: revealed suit"

    assert engine.flip_action() is None, f"{label}: engine should now be game-over"

    rows = engine.score()
    for expected in trace["finalScores"]:
        row = rows[int(expected["seat"])]
        for field_name, key in (
            ("cash", "cash"), ("items_value", "itemsValue"),
            ("objectives_value", "objectivesValue"), ("investments_value", "investmentsValue"),
            ("loans_value", "loansValue"), ("total", "total"),
        ):
            assert getattr(row, field_name) == expected[key], (
                f"{label} seat {expected['seat']}: {key}"
            )
    assert engine.ranking() == trace["ranking"], f"{label}: ranking"
