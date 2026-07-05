"""
Your PocketRocks bot lives here.

This is YOUR file — edit `choose_decision` below to make the bot play the way
you want. Everything else (connecting, auth, heartbeats, reconnects) is handled
for you by the pocketrocks SDK.

Run it with:

    python bot.py

Your API key and bot ID are read from the `.env` file next to this script,
so you don't paste any secrets into the code.
"""

from __future__ import annotations

from pocketrocks import BotDecision, DecisionContext, PocketRocksBot


class MyBot(PocketRocksBot):
    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        """Called every time the game needs a decision from your bot.

        `context` describes the current game state. Return a `BotDecision`
        describing what your bot wants to do. The three moves you can make:

            BotDecision.pass_turn()                  # do nothing this turn
            BotDecision.submit_bid(amount)           # bid `amount`
            BotDecision.select_info_to_reveal(index) # reveal card at `index`

        The starter logic below just bids the max it's allowed to. Replace it
        with your own strategy.
        """
        if context.decision_kind == "submitBid":
            # No legal bid available -> pass.
            if context.legal_max_amount is None or context.legal_max_amount <= 0:
                return BotDecision.pass_turn()
            return BotDecision.submit_bid(context.legal_max_amount)

        # The other kind of decision: pick which piece of info to reveal.
        return BotDecision.select_info_to_reveal(0)


if __name__ == "__main__":
    # Reads config from `.env`, connects, and runs until you stop it (Ctrl+C).
    MyBot().run()
