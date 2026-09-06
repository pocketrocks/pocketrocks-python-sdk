from __future__ import annotations

import pytest

from pocketrocks.internal.bot_wire import GameSetupEvent
from pocketrocks.protocol import build_decision_context, decode_frame, encode_frame
from pocketrocks.sim.batch_engine import BatchSimEngine
from pocketrocks.sim.context import build_sim_context, build_sim_request_and_context
from pocketrocks.sim.engine import SimEngine
from pocketrocks.sim.ruleset import PaymentRule, Ruleset


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


def test_direct_context_reflects_the_second_price_paid() -> None:
    # The sim shapes the context from engine state, so cash is right under either
    # rule, and the context states the rule so a bot can price accordingly.
    engine = SimEngine(3, "ctx-second-price", payment_rule="second-price")
    engine.action_deck[0] = "Auction1"
    engine.tiebreak_seat = 0
    engine.flip_action()
    outcome = engine.resolve([9, 4, 0])
    assert outcome.paid == 4
    context = build_sim_context(engine, seat=0, kind="submitBid", budget_ms=1_000)
    assert context.cash_by_seat == (26, 30, 30)
    assert context.legal_max_amount == 26
    assert context.payment_rule == "second-price"


def test_direct_context_defaults_to_first_price() -> None:
    engine = SimEngine(3, "ctx-first-price")
    engine.flip_action()
    context = build_sim_context(engine, seat=0, kind="submitBid", budget_ms=1_000)
    assert context.payment_rule == "first-price"


def test_context_payment_rule_is_the_batch_kernel_row() -> None:
    # SimEngine is a size-one facade over BatchSimEngine; the field a bot reads
    # must be the same rule the kernel's row prices with. Build a mixed batch and
    # check every row's rule reappears on a scalar engine's context.
    rows: tuple[tuple[str, PaymentRule], ...] = (
        ("A", "second-price"),
        ("B", "first-price"),
        ("E", "second-price"),
    )
    rulesets = tuple(
        Ruleset(player_count=3, value_chart=chart, payment_rule=rule) for chart, rule in rows
    )
    batch = BatchSimEngine.start(seeds=("r0", "r1", "r2"), rulesets=rulesets)
    assert batch.payment_rules == ("second-price", "first-price", "second-price")
    for row, ruleset in enumerate(rulesets):
        engine = SimEngine(3, f"row-{row}", ruleset=ruleset)
        engine.flip_action()
        context = build_sim_context(engine, seat=0, kind="submitBid", budget_ms=1_000)
        assert context.payment_rule == batch.payment_rules[row] == engine.ruleset.payment_rule
        assert engine._batch.payment_rules == (batch.payment_rules[row],)


def test_sim_game_setup_event_carries_the_payment_rule() -> None:
    # The wire request the sim builds must say the rule, or reconstruction on the
    # other side would price every auction first-price and cash would drift.
    engine = SimEngine(3, "ctx-setup-rule", payment_rule="second-price")
    setup = engine.events[0]
    assert isinstance(setup, GameSetupEvent)
    assert setup.payment_rule == "second-price"


def test_direct_context_carries_negative_chart_cells() -> None:
    engine = SimEngine(3, "ctx-negative", value_chart=(-20, 0, 20, 20, 10, 8))
    engine.flip_action()
    context = build_sim_context(engine, seat=0, kind="submitBid", budget_ms=1_000)
    assert context.value_chart == (-20, 0, 20, 20, 10, 8)


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
@pytest.mark.parametrize("payment_rule", ["first-price", "second-price"])
def test_direct_context_matches_production_reconstruction_through_full_game(
    player_count: int,
    value_chart: str,
    objectives_enabled: bool,
    payment_rule: PaymentRule,
) -> None:
    # Under second-price the two paths must agree on cash after every auction,
    # which pins the engine's compute_paid against the codec's reconstruction.
    engine = SimEngine(
        player_count,
        f"ctx-parity-{player_count}-{value_chart}-{objectives_enabled}-{payment_rule}",
        value_chart=value_chart,
        objectives_enabled=objectives_enabled,
        payment_rule=payment_rule,
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
