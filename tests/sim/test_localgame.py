from __future__ import annotations

import asyncio

import pytest

from pocketrocks import BotDecision, DecisionContext, PocketRocksBot
from pocketrocks import _reporting as reporting
from pocketrocks.sim import LocalGame, Ruleset, compute_paid
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


def test_negative_cell_second_price_game_plays_to_completion() -> None:
    ruleset = Ruleset(
        player_count=3, value_chart=(-20, 0, 20, 20, 10, 8), payment_rule="second-price"
    )
    game = LocalGame([MaxBot(), MaxBot(), PassBot()], seed="negative-second-12", ruleset=ruleset)
    assert game.ruleset is ruleset
    result = game.play()

    assert len(result.history) > 0
    for turn in result.history:
        # The price is the runner-up effective bid, never the winner's own.
        assert turn.paid == compute_paid("second-price", turn.effective_bids)
        assert turn.paid == sorted(turn.effective_bids)[-2]
    assert any(turn.paid > 0 for turn in result.history)
    for row in result.scores:
        components = (row.cash, row.items_value, row.objectives_value, row.investments_value)
        assert row.total == sum(components) - row.loans_value
    # Cells at -20 make an item value negative; the sign carries through to a
    # negative final total, and the ranking still orders by total.
    assert min(row.items_value for row in result.scores) < 0
    assert min(row.total for row in result.scores) < 0
    assert result.ranking == tuple(sorted(range(3), key=lambda seat: -result.scores[seat].total))


def test_local_game_rejects_ruleset_mixed_with_loose_keywords() -> None:
    with pytest.raises(ValueError, match="not both"):
        LocalGame([PassBot(), PassBot(), PassBot()], seed=1, ruleset=Ruleset(3), value_chart="B")
    with pytest.raises(ValueError, match="implies 3 players"):
        LocalGame([PassBot(), PassBot(), PassBot()], seed=1, ruleset=Ruleset(player_count=4))


def test_crash_and_unrepairable_illegal_fall_back_like_a_timeout() -> None:
    result = LocalGame(
        [CrashBot(), WrongKindBot(), PassBot()], seed=7, record_decisions=True
    ).play()
    assert "exception" in {d.fallback for d in result.decisions if d.seat == 0}
    assert "illegal" in {d.fallback for d in result.decisions if d.seat == 1}
    # The game still completes and produces scores.
    assert len(result.scores) == 3


def test_an_overbid_is_no_longer_a_fallback() -> None:
    # IllegalBot bids 10_000. The server would clamp that to legal max, so the sim
    # must forward it to the engine (which clamps identically) rather than
    # collapsing it to 0 and training the bot against a penalty that does not exist.
    result = LocalGame([IllegalBot(), PassBot(), PassBot()], seed=7, record_decisions=True).play()
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
    result = LocalGame([MaxBot(), PassBot(), PassBot()], seed=42, record_decisions=True).play()

    reveal_decisions = [d for d in result.decisions if d.kind == "selectInfoToReveal"]
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
            d.seat for d in result.decisions if d.kind == "submitBid" and d.turn_index == turn_index
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
    result = LocalGame([RawOnlyBot(), PassBot(), PassBot()], seed=11, record_decisions=True).play()
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
        # Deliberately pass float to test SDK rejects non-integral reveal indices.
        return BotDecision("selectInfoToReveal", 0.5)  # type: ignore[arg-type]


def test_non_integral_values_become_illegal_fallbacks() -> None:
    result = LocalGame(
        [FloatRevealBot(), PassBot(), PassBot()], seed=13, record_decisions=True
    ).play()
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


class _LoggingBot(PocketRocksBot):
    """Appends to a shared log when it decides and when it is told of a rejection.

    Lets a test observe the interleaving of decisions and rejection reports across
    seats within a turn.
    """

    def __init__(self, seat: int, log: list[str], *, overbid: bool) -> None:
        super().__init__()
        self._seat = seat
        self._log = log
        self._overbid = overbid

    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        self._log.append(f"decide:{self._seat}")
        if context.decision_kind == "submitBid":
            return BotDecision.submit_bid(9_999 if self._overbid else 0)
        return BotDecision.select_info_to_reveal(0)

    async def on_runtime_event(self, event: RuntimeEvent) -> None:
        if event.kind == "decisionRejected":
            self._log.append(f"report:{self._seat}")


def test_sim_reports_a_rejection_only_after_the_engine_has_the_bids() -> None:
    # Ordering guard: reporting awaits user telemetry hooks, so it must run only
    # after the engine has consumed the turn's bids — never interleaved during
    # bid gathering, where a slow hook would stall the auction. Seat 0 overbids
    # (forwarded, so reported); seats 1 and 2 pass. The report for seat 0 must
    # come after every seat has decided for the turn, not before seats 1 and 2.
    log: list[str] = []
    bots = [
        _LoggingBot(0, log, overbid=True),
        _LoggingBot(1, log, overbid=False),
        _LoggingBot(2, log, overbid=False),
    ]
    LocalGame(bots, seed=7).play()

    assert "report:0" in log, "an overbid must be reported"
    first_report = log.index("report:0")
    # Both other seats decided (for the first turn) before seat 0's rejection was
    # reported. Under the old in-_ask reporting this failed: report:0 fired inside
    # seat 0's turn, before decide:1 / decide:2.
    assert log.index("decide:1") < first_report
    assert log.index("decide:2") < first_report


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
    # Reports are drained by one shared worker, so a hook that raises must not
    # take the worker down with it: later turns' rejections are still reported.
    assert len(_rejections(bot)) > 1
    assert len(bot.errors) == len(_rejections(bot))
    assert any(max(turn.effective_bids) > 0 for turn in result.history)


class HangingReportBot(ReportingOverbidBot):
    """Overbids every turn and never returns from the rejection hook.

    The worst realistic telemetry bug: a hook that awaits something that never
    fires (an unresolved future, a request with no timeout).
    """

    async def on_runtime_event(self, event: RuntimeEvent) -> None:
        await super().on_runtime_event(event)
        await asyncio.Event().wait()


async def test_a_hanging_report_hook_does_not_stall_the_game(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Liveness guard: reporting is best-effort telemetry, so it must sit off the
    # game's critical path entirely. A hook that never returns may cost its own
    # report (and the ones behind it) plus a bounded drain at game end, but it
    # must not stop later seats deciding, later turns running, or the GameResult
    # coming back. Deferring the await to just after engine.resolve() was not
    # enough: the loop still awaited it, so the game hung on the first rejection.
    monkeypatch.setattr(reporting, "DEFAULT_DRAIN_TIMEOUT_S", 0.05)
    bot = HangingReportBot()
    game = LocalGame([bot, PassBot(), PassBot()], seed=7, record_decisions=True)

    result = await asyncio.wait_for(game.play_async(), timeout=10)

    assert len(result.scores) == 3
    assert bot.runtime_events, "the hook was never invoked at all"
    # The game kept going past the turn whose report is still stuck.
    assert len(result.history) > 1
    bids = [d for d in result.decisions if d.seat == 0 and d.kind == "submitBid"]
    assert len(bids) == len(result.history), "every turn's bid was asked and recorded"
    assert all(d.fallback is None for d in bids)


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


class HangingHookOverbidBot(PocketRocksBot):
    """Overbids (so it produces a rejection) and then hangs forever in its
    reporting hooks, wedging its own reporter."""

    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        if context.decision_kind == "submitBid":
            return BotDecision.submit_bid(9_999)
        return BotDecision.select_info_to_reveal(0)

    async def on_runtime_event(self, event: RuntimeEvent) -> None:
        await asyncio.Event().wait()  # never returns

    async def on_error(self, error: Exception) -> None:
        await asyncio.Event().wait()  # never returns


def test_one_bots_hanging_hook_does_not_suppress_another_bots_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Per-bot reporters: seat 0's hook hangs forever, but seat 1's rejection must
    # still be delivered. A single game-wide reporter would wedge on seat 0 and
    # cancel at drain, so seat 1 would never see its decisionRejected — and the
    # sim/live parity would break, since live gives each bot its own reporter.
    monkeypatch.setattr("pocketrocks._reporting.DEFAULT_DRAIN_TIMEOUT_S", 0.1)

    healthy = ReportingOverbidBot()  # also overbids -> rejection, records events
    LocalGame([HangingHookOverbidBot(), healthy, PassBot()], seed=7).play()

    assert _rejections(healthy), (
        "the healthy bot's rejection must be delivered despite another seat's hanging hook"
    )
