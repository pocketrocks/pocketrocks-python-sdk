from __future__ import annotations

import pytest

from pocketrocks.internal.bot_wire_v2 import decode_frame, encode_frame
from pocketrocks.protocol import build_decision_context
from pocketrocks.sim.context import build_sim_context, build_sim_request_and_context
from pocketrocks.sim.engine import SimEngine


def test_bid_context_matches_engine_state() -> None:
    engine = SimEngine(4, "ctx-seed")
    engine.action_deck[0] = "Auction1"
    engine.flip_action()
    context = build_sim_context(engine, seat=2, kind="submitBid", budget_ms=60_000)
    assert context.decision_kind == "submitBid"
    assert context.player_count == 4
    assert context.bot_seat == 2
    assert context.starting_cash == 25
    assert context.cash_by_seat == (25, 25, 25, 25)
    assert context.tiebreak_seat == engine.tiebreak_seat
    assert context.current_action_id == 1
    assert context.current_resource_ids == (engine.upcoming[0], engine.upcoming[1])
    assert context.current_hand_suit_ids == tuple(engine.players[2].hand_suits)
    assert context.legal_max_amount == 25
    assert context.remaining_deadline_ms > 50_000


def test_loan_context_extends_legal_max() -> None:
    engine = SimEngine(3, "ctx-loan")
    engine.action_deck[0] = "Loan10"
    engine.flip_action()
    context = build_sim_context(engine, seat=0, kind="submitBid", budget_ms=60_000)
    assert context.legal_max_amount == 40  # 30 cash + 10 principal


def test_context_survives_wire_round_trip() -> None:
    """The request the sim builds is a valid, canonical wire frame."""
    engine = SimEngine(3, "ctx-wire")
    engine.flip_action()
    from pocketrocks.sim.context import build_sim_request

    request = build_sim_request(engine, seat=1, kind="submitBid", budget_ms=1_000)
    assert decode_frame(encode_frame(request)) == request


def test_state_evolves_into_context() -> None:
    engine = SimEngine(3, "ctx-evolve")
    engine.action_deck[0] = "Auction1"
    engine.tiebreak_seat = 0
    engine.flip_action()
    engine.resolve([5, 0, 0])  # seat 0 bids 5 and wins outright
    context = build_sim_context(engine, seat=0, kind="submitBid", budget_ms=1_000)
    assert context.cash_by_seat[0] == 25  # 30 - 5
    assert sum(context.won_resource_counts_by_seat[0]) == 1
    assert context.tiebreak_seat == 0


def test_context_does_not_reconstruct_event_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = SimEngine(3, "ctx-direct")
    engine.flip_action()

    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("sim context replayed the event history")

    monkeypatch.setattr(
        "pocketrocks.protocol.reconstruct_decision_context",
        fail_if_called,
    )

    build_sim_context(engine, seat=0, kind="submitBid", budget_ms=1_000)


@pytest.mark.parametrize("player_count", [3, 4, 5])
@pytest.mark.parametrize("value_chart", ["A", "B", "C", "D", "E"])
@pytest.mark.parametrize("objectives_enabled", [False, True])
def test_direct_context_matches_production_reconstruction_through_full_game(
    player_count: int,
    value_chart: str,
    objectives_enabled: bool,
) -> None:
    engine = SimEngine(
        player_count,
        f"ctx-parity-{player_count}-{value_chart}-{objectives_enabled}",
        value_chart=value_chart,
        objectives_enabled=objectives_enabled,
    )

    while engine.flip_action() is not None:
        bids: list[int] = []
        for seat in range(player_count):
            request, direct = build_sim_request_and_context(
                engine,
                seat=seat,
                kind="submitBid",
                budget_ms=1_000,
            )
            reconstructed = build_decision_context(
                request,
                received_at=direct.received_at,
            )
            assert direct == reconstructed
            bids.append((engine.turn_index + seat + 1) % (engine.legal_max_bid(seat) + 1))

        outcome = engine.resolve(bids)
        if outcome.reveal_needed == "auto":
            engine.apply_reveal(outcome.winner_seat, 0, auto=True)
        elif outcome.reveal_needed == "choice":
            request, direct = build_sim_request_and_context(
                engine,
                seat=outcome.winner_seat,
                kind="selectInfoToReveal",
                budget_ms=1_000,
                turn_index=engine.turn_index - 1,
            )
            reconstructed = build_decision_context(
                request,
                received_at=direct.received_at,
            )
            assert direct == reconstructed
            engine.apply_reveal(outcome.winner_seat, 0, auto=False)
