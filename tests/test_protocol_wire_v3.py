"""Bot-wire v3 through the SDK: the golden frame, signed chart cells, presence
slots, and the payment rule from ``gameSetup`` to the public ``DecisionContext``.

The golden fixtures are copies of the TS monorepo's ``testFixtures/botWireV3.json``
and ``botWirePrimitives.json``: both codecs assert against the same committed
bytes, so byte identity is held by a third party rather than one side trusting
the other.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from pocketrocks import ActionId, Suit
from pocketrocks.internal.bot_wire import (
    AuctionResolvedEvent,
    DecisionRequest,
    GameSetupEvent,
    InfoRevealedEvent,
    PaymentRule,
    TurnOpenedEvent,
    bot_wire_game_setup_reserved_slots,
    decode_presence,
    decode_signed_varint,
    encode_presence,
    encode_signed_varint,
    reconstruct_decision_context,
)
from pocketrocks.protocol import PROTOCOL_VERSION, decode_frame, encode_frame
from pocketrocks.testing import scenario

_FIXTURES = Path(__file__).parent / "fixtures"
_GOLDEN = json.loads((_FIXTURES / "bot_wire_v3.json").read_text(encoding="utf8"))
_PRIMITIVES = json.loads((_FIXTURES / "bot_wire_primitives.json").read_text(encoding="utf8"))

# The golden request, constructed from the schema rather than decoded from the
# fixture, so the encode direction is asserted independently of the decode one.
# A second-price room on a custom chart with negative cells: every field v2
# could not carry.
_GOLDEN_REQUEST = DecisionRequest(
    kind="decisionRequest",
    request_id="00112233-4455-6677-8899-aabbccddeeff",
    deadline_at=1_750_000_000_000,
    decision_kind="submitBid",
    common_events=(
        GameSetupEvent(
            kind="gameSetup",
            player_count=3,
            starting_cash=20,
            value_chart=(-20, -4, 0, 8, 16, 20),
            initial_tiebreak_seat=1,
            objective_ids=(1, 2, 3, 4),
            payment_rule="second-price",
        ),
        TurnOpenedEvent(kind="turnOpened", action_id=1, resource_ids=(1, 2)),
        AuctionResolvedEvent(kind="auctionResolved", bids_by_seat=(4, 2, 1)),
        InfoRevealedEvent(kind="infoRevealed", suit_id=5),
        TurnOpenedEvent(kind="turnOpened", action_id=3, resource_ids=(3, 4)),
    ),
    bot_seat=0,
    current_hand_suit_ids=(1, 1, 3),
)


# --- Golden frame ------------------------------------------------------------


def test_golden_frame_decodes_reconstructs_and_re_encodes_byte_identically() -> None:
    golden = bytes.fromhex(_GOLDEN["decisionRequestHex"])
    assert golden[0] == PROTOCOL_VERSION

    frame = decode_frame(golden)
    assert frame == _GOLDEN_REQUEST
    assert isinstance(frame, DecisionRequest)

    context = reconstruct_decision_context(frame)
    # Second price: seat 0 wins (4, 2, 1) and pays the runner-up's 2, not its own
    # 4; the open Loan10 lifts the legal max from 18 to 28.
    assert context.payment_rule == "second-price"
    assert context.value_chart == (-20, -4, 0, 8, 16, 20)
    assert context.cash_by_seat == (18, 20, 20)
    assert context.legal_max_amount == 28
    assert context.won_resource_counts_by_seat[0] == (1, 0, 0, 0, 0)

    assert encode_frame(frame).hex() == _GOLDEN["decisionRequestHex"]
    assert encode_frame(_GOLDEN_REQUEST).hex() == _GOLDEN["decisionRequestHex"]


# --- Signed chart cells --------------------------------------------------------


def test_signed_varint_primitives_match_the_typescript_vectors() -> None:
    for value, hexed in _PRIMITIVES["signedVarintHex"].items():
        assert encode_signed_varint(int(value)).hex() == hexed, value
        assert decode_signed_varint(bytes.fromhex(hexed)) == int(value), value
    assert encode_presence(True).hex() == _PRIMITIVES["presenceHex"]["present"]
    assert encode_presence(False).hex() == _PRIMITIVES["presenceHex"]["absent"]


def test_negative_chart_cells_round_trip_through_the_sdk_frame_path() -> None:
    chart = (-20, -3, 0, 5, 12, 20)
    context = (
        scenario(players=3, starting_cash=20, value_chart=chart)
        .deciding(seat=0, hand=[Suit.ORE], kind="submitBid")
        .to_context()
    )
    assert context.value_chart == chart

    frame = decode_frame(
        scenario(players=3, starting_cash=20, value_chart=chart)
        .deciding(seat=0, hand=[Suit.ORE], kind="submitBid")
        .to_bytes(deadline_at=1)
    )
    assert isinstance(frame, DecisionRequest)
    setup = frame.common_events[0]
    assert isinstance(setup, GameSetupEvent)
    assert setup.value_chart == chart


# --- Presence slots ------------------------------------------------------------


def _lone_setup_frame() -> tuple[DecisionRequest, bytes]:
    # A one-event common log, so the reserved slots are the last bytes of it and
    # the per-decision suffix (bot seat, hand count, 3 suits = 5 bytes) follows.
    request = replace(_GOLDEN_REQUEST, common_events=_GOLDEN_REQUEST.common_events[:1])
    return request, encode_frame(request)


_SUFFIX_LEN = 5
# Header (1 + 1 + 16), deadline (6 bytes for 1.75e12), decision kind (1) -> the
# common-log length prefix sits at offset 25.
_COMMON_LENGTH_OFFSET = 25


def test_every_reserved_slot_is_written_absent_one_byte_each() -> None:
    # The absent path first and hardest: it is what runs on every frame today.
    _request, encoded = _lone_setup_frame()
    slots = encoded[-_SUFFIX_LEN - bot_wire_game_setup_reserved_slots : -_SUFFIX_LEN]
    assert slots == bytes(bot_wire_game_setup_reserved_slots)
    assert all(decode_presence(bytes([flag])) is False for flag in slots)


def test_a_present_reserved_slot_from_a_newer_server_is_skipped() -> None:
    # A tenant claims the last slot with an opaque 3-byte payload: presence 1,
    # varint length 3, then the bytes. A reader that predates the tenant skips it
    # and the suffix still decodes -- the reason the slots exist.
    request, encoded = _lone_setup_frame()
    payload = bytes([1, 3, 0xAA, 0xBB, 0xCC])
    claimed = bytearray(encoded[: -_SUFFIX_LEN - 1]) + payload + encoded[-_SUFFIX_LEN:]
    claimed[_COMMON_LENGTH_OFFSET] += len(payload) - 1
    assert decode_frame(bytes(claimed)) == request


def test_a_presence_byte_that_is_neither_zero_nor_one_is_malformed() -> None:
    _request, encoded = _lone_setup_frame()
    bad_flag = bytearray(encoded)
    bad_flag[-_SUFFIX_LEN - 1] = 2
    with pytest.raises(ValueError, match="presence flag"):
        decode_frame(bytes(bad_flag))


def test_a_present_slot_shorter_than_its_declared_length_is_malformed() -> None:
    _request, encoded = _lone_setup_frame()
    payload = bytes([1, 3, 0xAA])  # declares 3 bytes, carries 1
    short = bytearray(encoded[: -_SUFFIX_LEN - 1]) + payload + encoded[-_SUFFIX_LEN:]
    short[_COMMON_LENGTH_OFFSET] += len(payload) - 1
    with pytest.raises(ValueError, match="truncated"):
        decode_frame(bytes(short))


# --- Payment rule: pricing and the public context -----------------------------


@pytest.mark.parametrize(
    ("payment_rule", "bids", "expected_paid"),
    [
        ("first-price", (4, 2, 1), 4),
        ("second-price", (4, 2, 1), 2),
        ("first-price", (5, 5, 1), 5),
        ("second-price", (5, 5, 1), 5),  # a tie for first pays the tied amount
        ("first-price", (7, 0, 0), 7),
        ("second-price", (7, 0, 0), 0),  # a lone bid pays nothing
    ],
)
def test_reconstruction_prices_each_auction_by_the_setup_rule(
    payment_rule: PaymentRule, bids: tuple[int, ...], expected_paid: int
) -> None:
    context = (
        scenario(players=3, starting_cash=20, initial_tiebreak_seat=2, payment_rule=payment_rule)
        .turn(ActionId.INVEST5)
        .auction(bids)
        .deciding(seat=0, hand=[Suit.BRICK], kind="submitBid")
        .to_context()
    )
    assert sum(20 - cash for cash in context.cash_by_seat) == expected_paid
    # Winner selection is the same under both rules: highest bid, ties clockwise
    # from the tiebreak seat (seat 2 -> seat 0 wins the (5, 5, 1) tie).
    assert context.tiebreak_seat == 0
    assert context.cash_by_seat[0] == 20 - expected_paid


def test_payment_rule_flows_from_game_setup_to_the_public_context() -> None:
    for rule in ("first-price", "second-price"):
        context = (
            scenario(players=3, starting_cash=20, payment_rule=rule)
            .deciding(seat=0, hand=[Suit.BRICK], kind="submitBid")
            .to_context()
        )
        assert context.payment_rule == rule


def test_public_context_defaults_to_first_price() -> None:
    # Bots and the sim construct contexts directly; the default is the rule the
    # game has always had, so an unstated rule means what it always meant.
    context = (
        scenario(players=3, starting_cash=20)
        .deciding(seat=0, hand=[Suit.BRICK], kind="submitBid")
        .to_context()
    )
    assert context.payment_rule == "first-price"
