"""Ready-made opponents for local training. Import them, don't copy them:
``run_games([MyBot, GreedyValueBot, ValueTraderBot], 1000)``."""

from __future__ import annotations

import random

from pocketrocks.bot import PocketRocksBot
from pocketrocks.types import BotDecision, DecisionContext


class AlwaysPassBot(PocketRocksBot):
    """Bids nothing, reveals its first card. The floor to beat."""

    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        if context.decision_kind == "submitBid":
            return BotDecision.submit_bid(0)
        return BotDecision.select_info_to_reveal(0)


class RandomBot(PocketRocksBot):
    """Uniform random legal bids; random reveal. Seeded for reproducibility."""

    def __init__(self, seed: int = 0) -> None:
        super().__init__()
        self._rng = random.Random(seed)

    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        if context.decision_kind == "submitBid":
            return BotDecision.submit_bid(self._rng.randint(0, context.legal_max_amount or 0))
        return BotDecision.select_info_to_reveal(
            self._rng.randrange(max(1, context.revealable_count))
        )


class GreedyValueBot(PocketRocksBot):
    """Bids proportionally to the value its own hand implies the offered suits hold."""

    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        if context.decision_kind != "submitBid":
            return BotDecision.select_info_to_reveal(0)
        cash = context.cash_by_seat[context.bot_seat]
        estimate = 0
        for suit_id in context.current_resource_ids:
            if suit_id:
                own_signal = sum(1 for s in context.current_hand_suit_ids if s == suit_id)
                revealed = context.revealed_info_counts_by_suit[suit_id - 1]
                estimate += context.value_chart[min(own_signal + revealed, 5)]
        bid = min(context.legal_max_amount or 0, estimate, max(0, cash // 2 + estimate // 2))
        return BotDecision.submit_bid(bid)


class ValueTraderBot(PocketRocksBot):
    """Chases resources whose suits it holds info about; conserves cash otherwise."""

    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        if context.decision_kind != "submitBid":
            # Reveal the suit it holds most of (strongest public signal).
            hand = context.current_hand_suit_ids
            if not hand:
                return BotDecision.select_info_to_reveal(0)
            favorite = max(set(hand), key=lambda suit: sum(1 for s in hand if s == suit))
            return BotDecision.select_info_to_reveal(hand.index(favorite))
        matches = sum(
            1
            for suit_id in context.current_resource_ids
            if suit_id and suit_id in context.current_hand_suit_ids
        )
        if matches == 0:
            return BotDecision.submit_bid(0)
        cash = context.cash_by_seat[context.bot_seat]
        return BotDecision.submit_bid(min(context.legal_max_amount or 0, matches * cash // 3))
