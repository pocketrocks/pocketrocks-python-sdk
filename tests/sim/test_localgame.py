from __future__ import annotations

from pocketrocks import BotDecision, DecisionContext, PocketRocksBot
from pocketrocks.sim import LocalGame


class MaxBot(PocketRocksBot):
    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        if context.decision_kind == "submitBid":
            return BotDecision.submit_bid(context.legal_max_amount or 0)
        return BotDecision.select_info_to_reveal(0)


class PassBot(PocketRocksBot):
    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        return BotDecision.pass_turn()


class CrashBot(PocketRocksBot):
    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        raise RuntimeError("boom")


class IllegalBot(PocketRocksBot):
    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        return BotDecision.submit_bid(10_000)


def test_deterministic_game() -> None:
    a = LocalGame([MaxBot(), PassBot(), PassBot()], seed=42).play()
    b = LocalGame([MaxBot(), PassBot(), PassBot()], seed=42).play()
    assert a.scores == b.scores
    assert a.history == b.history
    assert len(a.history) > 0
    assert a.seats == ("MaxBot", "PassBot", "PassBot")


def test_crash_and_illegal_fall_back_like_a_timeout() -> None:
    result = LocalGame([CrashBot(), IllegalBot(), PassBot()], seed=7,
                       record_decisions=True).play()
    fallbacks = {d.fallback for d in result.decisions if d.seat == 0}
    assert "exception" in fallbacks
    fallbacks_illegal = {d.fallback for d in result.decisions if d.seat == 1}
    assert "illegal" in fallbacks_illegal
    # The game still completes and produces scores.
    assert len(result.scores) == 3


def test_decision_log_off_by_default() -> None:
    result = LocalGame([PassBot(), PassBot(), PassBot()], seed=1).play()
    assert result.decisions == ()


def test_pass_bots_still_produce_free_wins() -> None:
    result = LocalGame([PassBot(), PassBot(), PassBot()], seed=3).play()
    assert any(turn.paid == 0 and turn.winner_seat >= 0 for turn in result.history)


def test_reveal_decisions_stamped_with_their_own_turn_index() -> None:
    """Reveal asks happen after engine.resolve() bumps turn_index, so the
    ask must snapshot the pre-resolve turn index rather than reading it live.

    MaxBot wins outright/high enough to trigger "choice" reveals early
    (winner hand > 1 card), while PassBots keep the field thin. If reveal
    decisions were stamped with the post-resolve turn_index they would be
    one greater than the turn_index of the history record they belong to.
    """
    result = LocalGame(
        [MaxBot(), PassBot(), PassBot()], seed=42, record_decisions=True
    ).play()

    reveal_decisions = [
        d for d in result.decisions if d.kind == "selectInfoToReveal"
    ]
    assert reveal_decisions, "expected at least one reveal decision in this game"

    turns_with_real_reveal = {
        t.turn_index for t in result.history if t.reveal is not None and not t.reveal.auto
    }
    assert turns_with_real_reveal, "expected at least one non-auto reveal in history"

    for decision in reveal_decisions:
        assert decision.turn_index in turns_with_real_reveal
        # The reveal decision's turn must exist in history at all (i.e. it
        # was not stamped one-past-the-end from a post-resolve turn_index).
        assert decision.turn_index < len(result.history)

    # Bid decisions for the same turn share the same turn_index as the
    # reveal that resolves it.
    for turn_index in turns_with_real_reveal:
        bid_seats = {
            d.seat
            for d in result.decisions
            if d.kind == "submitBid" and d.turn_index == turn_index
        }
        assert bid_seats, f"expected bid decisions recorded for turn {turn_index}"
