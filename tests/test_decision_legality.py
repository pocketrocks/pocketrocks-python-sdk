from __future__ import annotations

import pytest

from pocketrocks import BotDecision, Suit
from pocketrocks.exceptions import InvalidBotDecision
from pocketrocks.testing import scenario
from pocketrocks.types import DecisionContext, classify


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


def test_classify_accepts_a_legal_decision() -> None:
    applied, error, _outgoing = classify(_bid_context(10), BotDecision.submit_bid(5))
    assert applied == "ok"
    assert error is None


def test_classify_forwards_an_overbid_because_the_server_clamps_it() -> None:
    applied, error, _outgoing = classify(_bid_context(10), BotDecision.submit_bid(11))
    assert applied == "forwarded"
    assert error is not None
    assert "legal maximum" in str(error)


def test_classify_discards_an_out_of_range_reveal_index() -> None:
    applied, error, _outgoing = classify(_reveal_context(3), BotDecision.select_info_to_reveal(3))
    assert applied == "discarded"
    assert error is not None
    assert "out of range" in str(error)


def test_classify_discards_a_mismatched_response_kind() -> None:
    applied, _error, _outgoing = classify(_bid_context(10), BotDecision.select_info_to_reveal(0))
    assert applied == "discarded"


def test_classify_discards_a_non_integer_bid() -> None:
    applied, error, _outgoing = classify(
        _bid_context(10),
        BotDecision(action_kind="submitBid", value=1.5),  # type: ignore[arg-type]
    )
    assert applied == "discarded"
    assert error is not None
    assert "integer" in str(error)


def test_classify_accepts_pass_for_both_request_kinds() -> None:
    assert classify(_bid_context(10), BotDecision.pass_turn())[0] == "ok"
    assert classify(_reveal_context(3), BotDecision.pass_turn())[0] == "ok"


def test_a_pass_carrying_a_value_is_unencodable() -> None:
    # The wire has no field for a value on a pass, so encode_frame rejects it.
    # Both request kinds must discard it — otherwise the live runtime raises in
    # the codec (requestFailed) while the sim silently ignores the stray value.
    valued_pass = BotDecision(action_kind="pass", value=1)
    for context in (_bid_context(10), _reveal_context(3)):
        applied, error, _ = classify(context, valued_pass)
        assert applied == "discarded"
        assert error is not None
        assert "pass" in str(error)


def test_a_valued_pass_survives_the_codec_after_discarding() -> None:
    # Proof the classification matches the codec: a plain pass encodes, a valued
    # one would raise — which is exactly why it is discarded rather than sent.
    from pocketrocks.exceptions import InvalidBotDecision
    from pocketrocks.internal.bot_wire import DecisionResponse
    from pocketrocks.protocol import encode_frame

    _bid_context(10).validate(BotDecision(action_kind="pass"))  # legal, no raise
    with pytest.raises(InvalidBotDecision, match="pass responses must not carry a value"):
        _bid_context(10).validate(BotDecision(action_kind="pass", value=1))
    with pytest.raises(ValueError, match="pass responses must not include a value"):
        encode_frame(
            DecisionResponse(
                kind="decisionResponse",
                request_id="11111111-1111-1111-1111-111111111111",
                action_kind="pass",
                value=1,
            )
        )


def test_classify_corrects_a_negative_bid_to_zero() -> None:
    # The wire cannot carry a negative varint, so "forward it and let the server
    # clamp" is impossible. 0 is what the server would have computed anyway.
    applied, error, outgoing = classify(_bid_context(10), BotDecision.submit_bid(-1))
    assert applied == "corrected"
    assert error is not None
    assert "non-negative" in str(error)
    assert outgoing.action_kind == "submitBid"
    assert outgoing.value == 0


def test_classify_corrects_an_unencodable_large_bid() -> None:
    from pocketrocks.internal.bot_wire import max_safe_integer

    applied, error, outgoing = classify(
        _bid_context(10), BotDecision.submit_bid(max_safe_integer + 1)
    )
    assert applied == "corrected"
    assert error is not None
    assert outgoing.value == max_safe_integer
    # The reported reason must name the encodability failure. Reusing the
    # game-rule message here would be actively misleading: the substitute still
    # exceeds legal_max_amount and gets clamped again server-side, so "bid
    # exceeds legal maximum" would explain neither why it was replaced nor why
    # it was replaced with this particular value.
    assert "encodable" in str(error)
    assert "legal maximum" not in str(error)


def test_an_unencodable_bid_is_corrected_even_without_a_legal_max() -> None:
    # Encodability must not depend on a game rule firing first. If correction
    # were decided inside the _check_clampable failure branch, a context with no
    # legal_max_amount would classify this as "ok" and it would then blow up in
    # the codec and be swallowed — the exact bug the corrected tier prevents.
    from dataclasses import replace

    from pocketrocks.internal.bot_wire import max_safe_integer

    context = replace(_bid_context(10), legal_max_amount=None)
    applied, error, outgoing = classify(context, BotDecision.submit_bid(max_safe_integer + 1))

    assert applied == "corrected"
    assert error is not None
    assert outgoing.value == max_safe_integer


def test_classify_forwards_an_encodable_overbid_unchanged() -> None:
    # Within wire range: send it raw and let the server clamp to legal max.
    applied, error, outgoing = classify(_bid_context(10), BotDecision.submit_bid(11))
    assert applied == "forwarded"
    assert error is not None
    assert outgoing.value == 11


def test_classify_returns_the_original_decision_when_legal() -> None:
    decision = BotDecision.submit_bid(5)
    applied, error, outgoing = classify(_bid_context(10), decision)
    assert (applied, error) == ("ok", None)
    assert outgoing is decision


def test_a_corrected_bid_is_encodable() -> None:
    # The whole point: what classify hands back must survive the codec.
    from pocketrocks.internal.bot_wire import DecisionResponse
    from pocketrocks.protocol import encode_frame

    _applied, _error, outgoing = classify(_bid_context(10), BotDecision.submit_bid(-1))
    encode_frame(
        DecisionResponse(
            kind="decisionResponse",
            request_id="11111111-1111-1111-1111-111111111111",
            action_kind=outgoing.action_kind,
            value=outgoing.value,
        )
    )
