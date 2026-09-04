from __future__ import annotations

from dataclasses import fields

from pocketrocks import ActionId, DecisionContext, Suit
from pocketrocks.internal.bot_wire import (
    DecisionRequest,
    ReconstructedDecisionContext,
    reconstruct_decision_context,
)
from pocketrocks.protocol import build_decision_context, decode_frame
from pocketrocks.testing import scenario


def test_every_reconstructed_field_exists_on_decision_context() -> None:
    # Locks the name-matching in build_decision_context: if upstream regenerates
    # ReconstructedDecisionContext with a field DecisionContext lacks, the spread
    # would raise at runtime — this catches it structurally first.
    reconstructed_names = {f.name for f in fields(ReconstructedDecisionContext)}
    context_names = {f.name for f in fields(DecisionContext)}
    assert reconstructed_names <= context_names


def test_build_decision_context_copies_every_shared_field_verbatim() -> None:
    request = decode_frame(
        scenario(players=3, starting_cash=20)
        .turn(ActionId.AUCTION1, resources=(Suit.BRICK, Suit.WOOD))
        .auction(bids={0: 4, 1: 0, 2: 0})
        .reveal(Suit.WOOD)
        .deciding(seat=0, hand=[Suit.BRICK, Suit.ORE], kind="submitBid")
        .to_bytes()
    )
    assert isinstance(request, DecisionRequest)
    reconstructed = reconstruct_decision_context(request)
    context = build_decision_context(request, received_at=0)

    for field in fields(ReconstructedDecisionContext):
        assert getattr(context, field.name) == getattr(reconstructed, field.name), field.name
