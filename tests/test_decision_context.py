from __future__ import annotations

from pocketrocks import DecisionContext


def _context(
    *,
    won: tuple[tuple[int, ...], ...],
    revealed: tuple[tuple[int, ...], ...],
) -> DecisionContext:
    return DecisionContext(
        request_id="r",
        deadline_at=100,
        received_at=10,
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


def test_remaining_deadline_ms() -> None:
    ctx = _context(won=((0,) * 5,), revealed=((0,) * 5,))
    assert ctx.remaining_deadline_ms == 90


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
