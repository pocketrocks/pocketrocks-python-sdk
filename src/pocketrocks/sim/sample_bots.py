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
        self._rng = random.Random(seed)  # noqa: S311 -- reproducible sim RNG, not security-sensitive

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
    """Prices offered resources from the active chart and known information."""

    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        if context.decision_kind != "submitBid":
            # Reveal the suit it holds most of (strongest public signal).
            hand = context.current_hand_suit_ids
            if not hand:
                return BotDecision.select_info_to_reveal(0)
            favorite = max(set(hand), key=lambda suit: sum(1 for s in hand if s == suit))
            return BotDecision.select_info_to_reveal(hand.index(favorite))
        known_counts = list(context.revealed_info_counts_by_suit)
        for suit_id in context.current_hand_suit_ids:
            known_counts[suit_id - 1] += 1

        estimated_value = 0
        resource_count = 0
        for suit_id in context.current_resource_ids:
            if not suit_id:
                continue
            known_count = min(known_counts[suit_id - 1], len(context.value_chart) - 1)
            estimated_value += context.value_chart[known_count]
            resource_count += 1

        cash = context.cash_by_seat[context.bot_seat]
        cash_budget = resource_count * cash // 3
        return BotDecision.submit_bid(
            min(context.legal_max_amount or 0, estimated_value, cash_budget)
        )
