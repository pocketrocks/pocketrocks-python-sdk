from __future__ import annotations

import pytest

from pocketrocks.internal.bot_wire_v2 import AuctionResolvedEvent, TurnOpenedEvent
from pocketrocks.sim.engine import SimEngine


def _engine_with(action: str, seed: str = "t") -> SimEngine:
    """An engine whose next action is forced to ``action`` (test-only surgery)."""
    engine = SimEngine(3, seed)
    engine.action_deck[0] = action
    return engine


def test_flip_emits_turn_opened_with_upcoming() -> None:
    engine = _engine_with("Loan10")
    assert engine.flip_action() == "Loan10"
    event = engine.events[-1]
    assert isinstance(event, TurnOpenedEvent)
    # visible resources are emitted for every action type, zero-padded to 2
    assert event.resource_ids == (engine.upcoming[0], engine.upcoming[1])


def test_bid_clamped_to_cash_on_normal_actions() -> None:
    engine = _engine_with("Auction1")
    engine.flip_action()
    outcome = engine.resolve([99, 0, 0])
    assert outcome.effective_bids[0] == 30  # clamped, not zeroed
    assert outcome.winner_seat == 0
    assert outcome.paid == 30


def test_loan_allows_bid_up_to_cash_plus_principal() -> None:
    engine = _engine_with("Loan20")
    engine.flip_action()
    assert engine.legal_max_bid(0) == 50
    outcome = engine.resolve([50, 0, 0])
    assert outcome.paid == 50
    # paid 50, received 20 principal
    assert engine.players[0].cash == 30 - 50 + 20
    assert engine.players[0].loans == [20]


def test_tie_goes_clockwise_after_leader_and_marker_rotates() -> None:
    engine = _engine_with("Auction1")
    engine.tiebreak_seat = 1
    engine.flip_action()
    outcome = engine.resolve([5, 5, 5])
    assert outcome.winner_seat == 2  # first seat clockwise AFTER leader 1
    assert engine.tiebreak_seat == 2


def test_all_zero_bids_still_selects_winner_for_free() -> None:
    engine = _engine_with("Auction1")
    engine.tiebreak_seat = 0
    engine.flip_action()
    outcome = engine.resolve([0, 0, 0])
    assert outcome.winner_seat == 1
    assert outcome.paid == 0


def test_auction2_grants_two_and_auction_resolved_event_carries_bids() -> None:
    engine = _engine_with("Auction2")
    engine.flip_action()
    expected = tuple(engine.upcoming)
    outcome = engine.resolve([3, 1, 0])
    assert outcome.bundle_suits == expected
    assert engine.players[0].won_suits == list(expected)
    event = [e for e in engine.events if isinstance(e, AuctionResolvedEvent)][-1]
    assert event.bids_by_seat == outcome.effective_bids
    assert len(engine.upcoming) == 2  # refilled


def test_investment_locks_bid() -> None:
    engine = _engine_with("Invest5")
    engine.flip_action()
    engine.resolve([7, 0, 0])
    assert engine.players[0].cash == 23
    assert engine.players[0].investments == [(7, 5)]


def test_reveal_needed_states() -> None:
    engine = _engine_with("Auction1")
    engine.flip_action()
    engine.players[0].hand_suits = [1, 2]
    outcome = engine.resolve([5, 0, 0])
    assert outcome.reveal_needed == "choice"
    record = engine.apply_reveal(0, 1, auto=False)
    assert record.suit == 2
    assert engine.players[0].hand_suits == [1]
    assert engine.players[0].revealed_suits == [2]


def test_reveal_out_of_range_falls_back_to_first() -> None:
    engine = _engine_with("Auction1")
    engine.flip_action()
    engine.players[0].hand_suits = [4, 5]
    engine.resolve([5, 0, 0])
    record = engine.apply_reveal(0, 99, auto=False)
    assert record.suit == 4


def test_game_ends_when_action_deck_empty() -> None:
    engine = SimEngine(3, "end")
    engine.action_deck = []
    assert engine.flip_action() is None
    assert engine.game_over


def test_game_ends_when_no_items_left() -> None:
    engine = SimEngine(3, "end2")
    engine.upcoming = []
    engine.pile = []
    assert engine.flip_action() is None
    assert engine.game_over


def test_objective_claimed_through_resolve() -> None:
    # Wire id 1 is "any pair" (same2): met once a player's won-suit counts
    # have any suit at count >= 2.
    engine = _engine_with("Auction1")
    engine.active_objectives = [(1, None)]
    engine.flip_action()
    suit = engine.upcoming[0]
    engine.players[0].won_suits = [suit]  # one more of `suit` completes the pair
    outcome = engine.resolve([5, 0, 0])
    assert outcome.winner_seat == 0
    assert outcome.claimed_objective_wire_ids == (1,)
    assert engine.active_objectives[0] == (1, 0)
    assert 1 in engine.players[0].objective_wire_ids


def test_objective_not_reclaimed_once_already_claimed() -> None:
    engine = _engine_with("Auction1")
    engine.active_objectives = [(1, 2)]  # already claimed by seat 2
    engine.flip_action()
    suit = engine.upcoming[0]
    engine.players[0].won_suits = [suit]  # seat 0 would otherwise meet the pattern
    outcome = engine.resolve([5, 0, 0])
    assert outcome.claimed_objective_wire_ids == ()
    assert engine.active_objectives[0] == (1, 2)


def test_history_records_turn_details_with_clamped_bid() -> None:
    engine = _engine_with("Auction1")
    engine.flip_action()
    expected_upcoming_before = tuple(engine.upcoming)
    outcome = engine.resolve([99, 0, 0])
    record = engine.history[-1]
    assert record.turn_index == 0
    assert record.action == "Auction1"
    assert record.upcoming_before == expected_upcoming_before
    assert record.raw_bids == (99, 0, 0)
    assert record.effective_bids == (30, 0, 0)  # clamped to seat 0's cash
    assert record.raw_bids != record.effective_bids
    assert record.winner_seat == outcome.winner_seat
    assert record.paid == outcome.paid
    assert record.reveal is None


def test_reveal_patches_last_history_record() -> None:
    engine = _engine_with("Auction1")
    engine.flip_action()
    engine.players[0].hand_suits = [1, 2]
    engine.resolve([5, 0, 0])
    record = engine.apply_reveal(0, 1, auto=False)
    patched = engine.history[-1]
    assert patched.reveal is record
    assert patched.reveal.seat == 0
    assert patched.reveal.suit == 2
    assert patched.reveal.auto is False


def test_apply_reveal_before_resolve_raises() -> None:
    engine = SimEngine(3, "guard")
    with pytest.raises(RuntimeError):
        engine.apply_reveal(0, 0, auto=False)


def test_reveal_needed_auto_when_one_card_left() -> None:
    engine = _engine_with("Auction1")
    engine.flip_action()
    engine.players[0].hand_suits = [3]
    outcome = engine.resolve([5, 0, 0])
    assert outcome.reveal_needed == "auto"


def test_reveal_needed_none_when_hand_empty() -> None:
    engine = _engine_with("Auction1")
    engine.flip_action()
    engine.players[0].hand_suits = []
    outcome = engine.resolve([5, 0, 0])
    assert outcome.reveal_needed is None
