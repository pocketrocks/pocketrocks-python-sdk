from __future__ import annotations

from pocketrocks import BotDecision, DecisionContext, PocketRocksBot


class RawFrameBot(PocketRocksBot):
    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        raise RuntimeError("raw callback should be used")

    async def choose_raw_decision(self, frame: object, context: DecisionContext) -> BotDecision:
        if frame.decision_kind == "submitBid":
            if context.legal_max_amount is None or context.legal_max_amount < 2:
                return BotDecision.pass_turn()
            return BotDecision.submit_bid(2)
        return BotDecision.select_info_to_reveal(0)


if __name__ == "__main__":
    RawFrameBot().run()
