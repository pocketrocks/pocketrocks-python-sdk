from __future__ import annotations

from pocketrocks import BotDecision, DecisionContext, PocketRocksBot
from pocketrocks.sim import LocalGame
from pocketrocks.types import RuntimeEvent


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


class WrongKindBot(PocketRocksBot):
    """Answers a bid request with a reveal — Tier A: the server has no repair path."""

    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        return BotDecision.select_info_to_reveal(0)


def test_deterministic_game() -> None:
    a = LocalGame([MaxBot(), PassBot(), PassBot()], seed=42).play()
    b = LocalGame([MaxBot(), PassBot(), PassBot()], seed=42).play()
    assert a.scores == b.scores
    assert a.history == b.history
    assert len(a.history) > 0
    assert a.seats == ("MaxBot", "PassBot", "PassBot")


def test_crash_and_unrepairable_illegal_fall_back_like_a_timeout() -> None:
    result = LocalGame([CrashBot(), WrongKindBot(), PassBot()], seed=7,
                       record_decisions=True).play()
    assert "exception" in {d.fallback for d in result.decisions if d.seat == 0}
    assert "illegal" in {d.fallback for d in result.decisions if d.seat == 1}
    # The game still completes and produces scores.
    assert len(result.scores) == 3


def test_an_overbid_is_no_longer_a_fallback() -> None:
    # IllegalBot bids 10_000. The server would clamp that to legal max, so the sim
    # must forward it to the engine (which clamps identically) rather than
    # collapsing it to 0 and training the bot against a penalty that does not exist.
    result = LocalGame([IllegalBot(), PassBot(), PassBot()], seed=7,
                       record_decisions=True).play()
    bids = [d for d in result.decisions if d.seat == 0 and d.kind == "submitBid"]
    assert bids, "seat 0 was never asked to bid"
    assert all(d.fallback is None for d in bids)


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


class RawOnlyBot(PocketRocksBot):
    """Mirrors examples/raw_frame_bot.py: strategy lives in the raw override,
    choose_decision deliberately raises. The live runtime dispatches to
    choose_raw_decision for such bots; the sim must do the same or every
    decision silently becomes a fallback."""

    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        raise RuntimeError("raw bots never use the derived-context path")

    async def choose_raw_decision(self, frame: object, context: DecisionContext) -> BotDecision:
        from pocketrocks.internal.bot_wire_v2 import DecisionRequest

        assert isinstance(frame, DecisionRequest)
        assert frame.decision_kind == context.decision_kind
        if context.decision_kind == "submitBid":
            return BotDecision.submit_bid(min(1, context.legal_max_amount or 0))
        return BotDecision.select_info_to_reveal(0)


def test_raw_decision_bots_get_live_dispatch() -> None:
    result = LocalGame([RawOnlyBot(), PassBot(), PassBot()], seed=11,
                       record_decisions=True).play()
    raw_seat_decisions = [d for d in result.decisions if d.seat == 0]
    assert raw_seat_decisions, "raw bot was never asked"
    assert all(d.fallback is None for d in raw_seat_decisions)
    assert len(result.scores) == 3


class FloatRevealBot(PocketRocksBot):
    """Returns a non-integral reveal index (as an untyped model output might).
    Range checks alone would accept 0.5; it must be rejected as illegal, not
    crash the game via list.pop(0.5) outside the fallback net."""

    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        if context.decision_kind == "submitBid":
            return BotDecision.submit_bid(context.legal_max_amount or 0)
        return BotDecision("selectInfoToReveal", 0.5)  # type: ignore[arg-type]


def test_non_integral_values_become_illegal_fallbacks() -> None:
    result = LocalGame([FloatRevealBot(), PassBot(), PassBot()], seed=13,
                       record_decisions=True).play()
    assert len(result.scores) == 3  # the game completed — no TypeError escape
    reveal_decisions = [
        d for d in result.decisions if d.seat == 0 and d.kind == "selectInfoToReveal"
    ]
    assert reveal_decisions, "winner was never asked to reveal"
    assert all(d.fallback == "illegal" for d in reveal_decisions)


class ReportingOverbidBot(PocketRocksBot):
    """Bids far above legal max and records everything the runtime tells it."""

    def __init__(self) -> None:
        super().__init__()
        self.runtime_events: list[RuntimeEvent] = []
        self.errors: list[Exception] = []

    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        if context.decision_kind == "submitBid":
            return BotDecision.submit_bid(9_999)
        return BotDecision.select_info_to_reveal(0)

    async def on_runtime_event(self, event: RuntimeEvent) -> None:
        self.runtime_events.append(event)

    async def on_error(self, error: Exception) -> None:
        self.errors.append(error)


def _rejections(bot: ReportingOverbidBot) -> list[RuntimeEvent]:
    return [e for e in bot.runtime_events if e.kind == "decisionRejected"]


def test_sim_reports_an_overbid_as_forwarded() -> None:
    bot = ReportingOverbidBot()
    result = LocalGame([bot, PassBot(), PassBot()], seed=7, record_decisions=True).play()

    events = _rejections(bot)
    assert events, "an overbid must be reported in the sim, not silently absorbed"
    assert events[0].details["applied"] == "forwarded"
    assert events[0].details["value"] == 9_999
    assert "legal maximum" in events[0].details["detail"]
    assert bot.errors

    # Forwarded, so the engine received the raw value and clamped it. The
    # overbidding bot therefore actually competes for auctions.
    assert any(max(turn.effective_bids) > 0 for turn in result.history)


class NegativeBidBot(PocketRocksBot):
    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        if context.decision_kind == "submitBid":
            return BotDecision.submit_bid(-1)
        return BotDecision.select_info_to_reveal(0)


def test_negative_bid_record_keeps_the_bots_value_and_flags_the_substitute() -> None:
    # -1 cannot be encoded on the wire, so classify() corrects it to 0. The
    # DecisionRecord must still remember the bot's own -1, with the substitute
    # surfaced separately in `corrected` rather than overwriting `decision`.
    bot = NegativeBidBot()
    result = LocalGame([bot, PassBot(), PassBot()], seed=7, record_decisions=True).play()

    bids = [d for d in result.decisions if d.seat == 0 and d.kind == "submitBid"]
    assert bids, "seat 0 was never asked to bid"
    for record in bids:
        assert record.decision is not None
        assert record.decision.value == -1
        assert record.corrected is not None
        assert record.corrected.value == 0
        assert record.fallback is None


class RaisingOnErrorOverbidBot(ReportingOverbidBot):
    async def on_error(self, error: Exception) -> None:
        await super().on_error(error)
        raise RuntimeError("on_error blew up")


def test_raising_on_error_does_not_turn_a_forwarded_overbid_into_a_fallback() -> None:
    # report_rejection is best-effort: a bot's on_error blowing up must not
    # corrupt the sim's own bookkeeping. The engine must still receive the raw
    # overbid (forwarded, not a fallback), and the game must still complete.
    bot = RaisingOnErrorOverbidBot()
    result = LocalGame([bot, PassBot(), PassBot()], seed=7, record_decisions=True).play()

    bids = [d for d in result.decisions if d.seat == 0 and d.kind == "submitBid"]
    assert bids, "seat 0 was never asked to bid"
    assert all(d.fallback is None for d in bids)
    assert bot.errors  # on_error was in fact called, before it raised
    assert any(max(turn.effective_bids) > 0 for turn in result.history)


def test_sim_reports_an_out_of_range_reveal_as_discarded() -> None:
    class BadRevealBot(ReportingOverbidBot):
        async def choose_decision(self, context: DecisionContext) -> BotDecision:
            if context.decision_kind == "submitBid":
                return BotDecision.submit_bid(context.legal_max_amount or 0)
            return BotDecision.select_info_to_reveal(99)

    bot = BadRevealBot()
    result = LocalGame([bot, PassBot(), PassBot()], seed=13, record_decisions=True).play()

    events = _rejections(bot)
    assert events
    assert events[0].details["applied"] == "discarded"
    reveals = [d for d in result.decisions if d.seat == 0 and d.kind == "selectInfoToReveal"]
    assert reveals, "winner was never asked to reveal"
    assert all(d.fallback == "illegal" for d in reveals)
