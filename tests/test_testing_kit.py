from __future__ import annotations

import pytest

from pocketrocks import ActionId, BotDecision, DecisionContext, PocketRocksBot, Suit
from pocketrocks.internal.bot_wire import DecisionResponse
from pocketrocks.testing import FakeTransport, decode_frames, heartbeat_bytes, scenario


def test_scenario_derives_context_from_narrated_history() -> None:
    # Seat 0 wins a 1-resource auction for $4: cash drops 20 -> 16, one Brick won,
    # and the submitBid legal max is the winner's remaining cash.
    ctx = (
        scenario(players=3, starting_cash=20)
        .turn(ActionId.AUCTION1, resources=(Suit.BRICK, Suit.WOOD))
        .auction(bids={0: 4, 1: 0, 2: 0})
        .deciding(seat=0, hand=[Suit.BRICK, Suit.BRICK, Suit.ORE], kind="submitBid")
        .to_context()
    )

    assert isinstance(ctx, DecisionContext)
    assert ctx.decision_kind == "submitBid"
    assert ctx.cash_by_seat == (16, 20, 20)
    assert ctx.legal_max_amount == 16
    assert ctx.bot_seat == 0
    assert ctx.current_hand_suit_ids == (1, 1, 3)
    assert ctx.revealable_count == 3
    assert ctx.won_resource_counts_by_suit == (1, 0, 0, 0, 0)


def test_scenario_reveal_lands_on_the_current_tiebreak_seat() -> None:
    ctx = (
        scenario(players=3, starting_cash=20)
        .turn(ActionId.AUCTION1, resources=(Suit.BRICK, Suit.WOOD))
        .auction(bids={0: 4, 1: 0, 2: 0})  # winner seat 0 becomes tiebreak
        .reveal(Suit.WOOD)
        .deciding(seat=0, hand=[Suit.BRICK], kind="submitBid")
        .to_context()
    )
    assert ctx.revealed_info_counts_by_suit == (0, 1, 0, 0, 0)


def test_override_pins_a_field_the_narration_would_not_produce() -> None:
    ctx = (
        scenario(players=2, starting_cash=20)
        .deciding(seat=0, hand=[Suit.BRICK], kind="submitBid")
        .override(legal_max_amount=0)
        .to_context()
    )
    assert ctx.legal_max_amount == 0


def test_override_supports_arbitrary_matrices_for_property_math() -> None:
    ctx = (
        scenario(players=2, starting_cash=0)
        .deciding(seat=0, hand=[], kind="submitBid")
        .override(
            won_resource_counts_by_seat=((1, 0, 2, 0, 0), (0, 3, 0, 0, 1)),
            revealed_info_counts_by_seat=((0, 1, 0, 0, 0), (0, 0, 0, 2, 0)),
        )
        .to_context()
    )
    assert ctx.won_resource_counts_by_suit == (1, 3, 2, 0, 1)
    assert ctx.revealed_info_counts_by_suit == (0, 1, 0, 2, 0)


@pytest.mark.asyncio
async def test_scenario_bytes_drive_a_full_runtime_round_trip() -> None:
    class Bidder(PocketRocksBot):
        async def choose_decision(self, context: DecisionContext) -> BotDecision:
            return BotDecision.submit_bid(context.legal_max_amount or 0)

    request_bytes = (
        scenario(players=3, starting_cash=20)
        .turn(ActionId.AUCTION1, resources=(Suit.BRICK, Suit.WOOD))
        .deciding(seat=0, hand=[Suit.BRICK, Suit.BRICK, Suit.ORE], kind="submitBid")
        .to_bytes()
    )
    transport = FakeTransport(
        [heartbeat_bytes("11111111-1111-1111-1111-111111111111"), request_bytes]
    )
    bot = Bidder(
        api_key="k",
        bot_id="b",
        server_url="ws://example.test",
        reconnect=False,
        transport=transport,
    )

    await bot.run_async()

    sent = decode_frames(transport.sent_messages)
    assert [frame.kind for frame in sent] == ["heartbeatResponse", "decisionResponse"]
    decision_response = sent[1]
    assert isinstance(decision_response, DecisionResponse)
    assert decision_response.action_kind == "submitBid"
    assert decision_response.value == 20  # no auction resolved -> legal max is full starting cash
