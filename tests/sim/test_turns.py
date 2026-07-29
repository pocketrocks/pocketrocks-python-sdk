from __future__ import annotations

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
