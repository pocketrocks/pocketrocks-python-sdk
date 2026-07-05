from __future__ import annotations

import random

from pocketrocks import BotDecision, DecisionContext, PocketRocksBot


class RandomBot(PocketRocksBot):
    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        if context.decision_kind == "submitBid":
            if context.legal_max_amount is None:
                return BotDecision.pass_turn()
            options = [0, context.legal_max_amount // 2, context.legal_max_amount]
            amount = max(0, random.choice(options))
            return BotDecision.pass_turn() if amount == 0 else BotDecision.submit_bid(amount)
        return BotDecision.select_info_to_reveal(random.randrange(context.revealable_count))


if __name__ == "__main__":
    RandomBot().run()
