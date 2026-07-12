from __future__ import annotations

import time

from pocketrocks import DecisionContext, Suit
from pocketrocks.testing import scenario


def _context(
    *,
    won: tuple[tuple[int, ...], ...],
    revealed: tuple[tuple[int, ...], ...],
    deadline_at: int = 100,
    received_at: int = 10,
) -> DecisionContext:
    # These tests assert the dataclass's own derived-property math on arbitrary
    # per-seat matrices, which no realistic history would produce — the override
    # hatch is exactly for that. deadline_at/received_at are pinned too so the
    # remaining-budget assertions are deterministic.
    return (
        scenario(players=len(won), starting_cash=0)
        .deciding(seat=0, hand=[Suit.BRICK], kind="submitBid")
        .override(
            deadline_at=deadline_at,
            received_at=received_at,
            won_resource_counts_by_seat=won,
            revealed_info_counts_by_seat=revealed,
        )
        .to_context()
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
