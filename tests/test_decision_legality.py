from __future__ import annotations

import pytest

from pocketrocks import BotDecision, Suit
from pocketrocks.exceptions import InvalidBotDecision
from pocketrocks.testing import scenario
from pocketrocks.types import DecisionContext


def _bid_context(legal_max: int) -> DecisionContext:
    # A submitBid context whose legal max is the winner's remaining cash.
    return (
        scenario(players=2, starting_cash=legal_max)
        .deciding(seat=0, hand=[Suit.BRICK], kind="submitBid")
        .to_context()
    )


def _reveal_context(revealable: int) -> DecisionContext:
    hand = [Suit.BRICK] * revealable
    return (
        scenario(players=2, starting_cash=0)
        .deciding(seat=0, hand=hand, kind="selectInfoToReveal")
        .to_context()
    )


def test_pass_is_always_legal() -> None:
    assert _bid_context(10).is_legal(BotDecision.pass_turn())
    assert _reveal_context(3).is_legal(BotDecision.pass_turn())


def test_bid_within_legal_max_is_legal() -> None:
    ctx = _bid_context(10)
    assert ctx.is_legal(BotDecision.submit_bid(0))
    assert ctx.is_legal(BotDecision.submit_bid(10))


def test_bid_over_legal_max_is_rejected() -> None:
    ctx = _bid_context(10)
    assert not ctx.is_legal(BotDecision.submit_bid(11))
    with pytest.raises(InvalidBotDecision, match="legal maximum"):
        ctx.validate(BotDecision.submit_bid(11))


def test_negative_bid_is_rejected() -> None:
    with pytest.raises(InvalidBotDecision, match="non-negative"):
        _bid_context(10).validate(BotDecision.submit_bid(-1))


def test_reveal_response_to_a_bid_request_is_rejected() -> None:
    with pytest.raises(InvalidBotDecision, match="cannot receive reveal"):
        _bid_context(10).validate(BotDecision.select_info_to_reveal(0))


def test_reveal_index_in_range_is_legal() -> None:
    ctx = _reveal_context(3)
    assert ctx.is_legal(BotDecision.select_info_to_reveal(0))
    assert ctx.is_legal(BotDecision.select_info_to_reveal(2))


def test_reveal_index_out_of_range_is_rejected() -> None:
    ctx = _reveal_context(3)
    assert not ctx.is_legal(BotDecision.select_info_to_reveal(3))
    with pytest.raises(InvalidBotDecision, match="out of range"):
        ctx.validate(BotDecision.select_info_to_reveal(3))


def test_bid_response_to_a_reveal_request_is_rejected() -> None:
    with pytest.raises(InvalidBotDecision, match="cannot receive bid"):
        _reveal_context(3).validate(BotDecision.submit_bid(1))
