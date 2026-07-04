from __future__ import annotations

import time

from pocketrocks import DecisionContext


def _context(
    *,
    won: tuple[tuple[int, ...], ...],
    revealed: tuple[tuple[int, ...], ...],
    deadline_at: int = 100,
    received_at: int = 10,
) -> DecisionContext:
    return DecisionContext(
        request_id="r",
        deadline_at=deadline_at,
        received_at=received_at,
        decision_kind="submitBid",
        player_count=len(won),
        starting_cash=0,
        value_chart=(0, 4, 8, 12, 16, 20),
        objective_ids=(),
        current_action_id=None,
        current_resource_ids=(0, 0),
        cash_by_seat=tuple(0 for _ in won),
        tiebreak_seat=0,
        won_resource_counts_by_seat=won,
        revealed_info_counts_by_seat=revealed,
        owned_objective_ids_by_seat=tuple(() for _ in won),
        bot_seat=0,
        current_hand_suit_ids=(),
        legal_max_amount=0,
        revealable_count=0,
    )


def test_remaining_deadline_ms_measures_from_now() -> None:
    # Budget is measured from the current time, not received_at, so it reflects
    # the real time left after any queue delay.
    now_ms = int(time.time() * 1000)
    ctx = _context(
        won=((0,) * 5,),
        revealed=((0,) * 5,),
        deadline_at=now_ms + 5_000,
        received_at=now_ms - 2_000,
    )
    # ~5s remaining regardless of the (earlier) received_at; allow scheduling slack.
    assert 4_000 <= ctx.remaining_deadline_ms <= 5_000


def test_remaining_deadline_ms_clamps_at_zero() -> None:
    ctx = _context(
        won=((0,) * 5,),
        revealed=((0,) * 5,),
        deadline_at=int(time.time() * 1000) - 1_000,
    )
    assert ctx.remaining_deadline_ms == 0


def test_by_suit_totals_are_column_sums() -> None:
    ctx = _context(
        won=((1, 0, 2, 0, 0), (0, 3, 0, 0, 1)),
        revealed=((0, 1, 0, 0, 0), (0, 0, 0, 2, 0)),
    )
    assert ctx.won_resource_counts_by_suit == (1, 3, 2, 0, 1)
    assert ctx.revealed_info_counts_by_suit == (0, 1, 0, 2, 0)
    # totals across suits match totals across seats
    assert sum(ctx.won_resource_counts_by_suit) == sum(
        sum(seat) for seat in ctx.won_resource_counts_by_seat
    )
