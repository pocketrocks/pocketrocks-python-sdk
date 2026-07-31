"""The sim and the live runtime must report an illegal decision identically.

These two surfaces silently diverged for months — the sim had a fallback net and
the live runtime did not — so this file runs the *real* LocalGame and the *real*
PocketRocksRuntime over one shared corpus and compares what each reports.

Every case is a bid request, which is enough to reach all four rejection
categories. Per-surface mechanics (live sends/withholds a frame; the sim
substitutes 0) are covered in test_external_bot_runtime.py and sim/test_localgame.py.

Deliberately NOT asserted: that both produce the same clamped bid. That is pinned
by the golden traces against the real TS engine and gated on rulesVersion (see
sim/traces.py). Re-checking it here would create a third copy of the server's clamp
formula that nothing keeps in sync — the exact failure this work removes.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from pocketrocks import ActionId, BotDecision, DecisionContext, PocketRocksBot, Suit
from pocketrocks.sim import LocalGame
from pocketrocks.testing import FakeTransport, scenario
from pocketrocks.types import RuntimeEvent

CASES = [
    pytest.param(BotDecision.submit_bid(9_999), "forwarded", id="overbid"),
    pytest.param(BotDecision.submit_bid(-1), "corrected", id="negative-bid"),
    pytest.param(BotDecision.select_info_to_reveal(0), "discarded", id="wrong-response-kind"),
    pytest.param(
        BotDecision(action_kind="submitBid", value=1.5),  # type: ignore[arg-type]
        "discarded",
        id="non-integer-bid",
    ),
]


class ScriptedBot(PocketRocksBot):
    """Answers every bid request with one scripted decision, recording rejections."""

    def __init__(self, decision: BotDecision, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._decision = decision
        self.rejections: list[dict[str, Any]] = []

    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        if context.decision_kind == "submitBid":
            return self._decision
        return BotDecision.select_info_to_reveal(0)

    async def on_runtime_event(self, event: RuntimeEvent) -> None:
        if event.kind == "decisionRejected":
            self.rejections.append(event.details)

    async def on_error(self, error: Exception) -> None:
        return None


class PassBot(PocketRocksBot):
    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        return BotDecision.pass_turn()


async def _sim_rejection(decision: BotDecision) -> dict[str, Any]:
    bot = ScriptedBot(decision)
    # play_async, not play: play() calls asyncio.run() and would explode here.
    await LocalGame([bot, PassBot(), PassBot()], seed=5).play_async()
    assert bot.rejections, "the sim reported no decisionRejected"
    return bot.rejections[0]


async def _live_rejection(decision: BotDecision) -> dict[str, Any]:
    request = (
        scenario(players=3, starting_cash=20, initial_tiebreak_seat=1)
        .turn(ActionId.AUCTION1, resources=(Suit.BRICK, Suit.WOOD))
        .deciding(
            seat=0,
            hand=[Suit.BRICK, Suit.BRICK, Suit.ORE],
            kind="submitBid",
            request_id="55555555-5555-5555-5555-555555555555",
        )
        .to_bytes(deadline_at=int(time.time() * 1000) + 5_000)
    )
    bot = ScriptedBot(
        decision,
        api_key="test-key",
        bot_id="bot_1234",
        server_url="ws://example.test",
        reconnect=False,
        transport=FakeTransport([request]),
    )
    await bot.run_async()
    assert bot.rejections, "the live runtime reported no decisionRejected"
    return bot.rejections[0]


@pytest.mark.parametrize(("decision", "expected"), CASES)
async def test_sim_and_live_report_the_same_rejection(
    decision: BotDecision, expected: str
) -> None:
    sim = await _sim_rejection(decision)
    live = await _live_rejection(decision)

    # request_id is the one field that legitimately differs — each surface mints
    # its own. Every other field must match, or the two have drifted apart again.
    assert sim.keys() == live.keys()
    comparable = {k: v for k, v in sim.items() if k != "request_id"}
    assert comparable == {k: v for k, v in live.items() if k != "request_id"}

    assert comparable["applied"] == expected
    assert comparable["decision_kind"] == "submitBid"
    assert comparable["action_kind"] == decision.action_kind
    assert comparable["value"] == decision.value  # always the bot's original value
    assert "context" not in comparable  # debug is off on both surfaces

    # A corrected decision must report what was actually used, on both surfaces.
    if expected == "corrected":
        assert comparable["corrected_value"] == 0
    else:
        assert "corrected_value" not in comparable
