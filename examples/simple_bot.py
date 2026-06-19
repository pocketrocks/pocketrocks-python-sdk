from __future__ import annotations

from pocketrocks import BotDecision, DecisionContext, PocketRocksBot


class SimpleBot(PocketRocksBot):
    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        if context.decision_kind == "submitBid":
            if context.legal_max_amount is None or context.legal_max_amount <= 0:
                return BotDecision.pass_turn()
            return BotDecision.submit_bid(context.legal_max_amount)
        return BotDecision.select_info_to_reveal(0)


if __name__ == "__main__":
    SimpleBot().run()
