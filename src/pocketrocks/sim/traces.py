"""Golden-trace replay: pin this engine to games played by the real TS engine.

A trace records a full seeded game (raw bids in, everything observable out).
Replaying feeds the recorded raw bids into ``SimEngine`` and asserts the entire
state evolution matches. If the server rules change, regenerate fixtures in the
main repo and re-sync this engine; the ``rulesVersion`` gate in the test suite
keeps the two from silently drifting.
"""

from __future__ import annotations

from typing import Any

from pocketrocks.protocol import build_decision_context

from .constants import ACTION_WIRE_IDS, INFO_CARDS_PER_PLAYER, STARTING_CASH
from .context import build_sim_request_and_context
from .engine import SimEngine


def replay_trace(trace: dict[str, Any]) -> None:
    setup = trace["setup"]
    player_count = int(trace["playerCount"])
    engine = SimEngine(
        player_count,
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
    assert setup["startingCash"] == STARTING_CASH[player_count], f"{label}: starting cash constant"
    assert all(p.cash == setup["startingCash"] for p in engine.players), (
        f"{label}: dealt starting cash"
    )
    assert setup["infoCardsPerPlayer"] == INFO_CARDS_PER_PLAYER[player_count], (
        f"{label}: info cards per player"
    )
    assert list(engine.value_chart) == trace["valueChart"], f"{label}: value chart"

    for i, turn in enumerate(trace["turns"]):
        where = f"{label} turn {i}"
        action = engine.flip_action()
        assert action is not None, f"{where}: expected another turn"
        assert action == turn["actionType"], f"{where}: flipped action"
        assert ACTION_WIRE_IDS[action] == turn["actionWireId"], f"{where}: action wire id"
        assert list(engine.upcoming) == turn["upcomingBefore"], f"{where}: upcoming"
        # Context parity anchored to TS-recorded states: the direct build must
        # match production wire reconstruction on every decision the real
        # engine reached, not just on states self-play policies happen to hit.
        for seat in range(player_count):
            request, direct = build_sim_request_and_context(
                engine, seat, "submitBid", budget_ms=1_000
            )
            reconstructed = build_decision_context(request, received_at=direct.received_at)
            assert direct == reconstructed, f"{where}: bid context parity (seat {seat})"
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
            # The reveal belongs to turn ``i`` but ``resolve()`` already advanced
            # the engine's counter, so pin ``turn_index`` (as ``LocalGame`` does).
            request, direct = build_sim_request_and_context(
                engine, reveal["seat"], "selectInfoToReveal", budget_ms=1_000, turn_index=i
            )
            reconstructed = build_decision_context(request, received_at=direct.received_at)
            assert direct == reconstructed, f"{where}: reveal context parity"
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
