"""Train a policy on ``BatchSimEngine`` arrays, then deploy it as a live bot.

``BatchSimEngine`` is the throughput interface: it hands a policy raw NumPy
arrays and no ``DecisionContext``. The deployable artifact, however, is still a
``PocketRocksBot`` — live games only speak the context/decision protocol. This
example is the worked path across that boundary, in three acts:

1. *Train on batch* — random-search a tiny two-parameter bid heuristic over a
   vectorized batch of games. The policy is deliberately simple; the point is
   the plumbing, not the strategy.
2. *Wrap for live* — ``BatchTrainedBot`` recomputes the SAME features from
   ``DecisionContext`` fields. The field mapping block inside it is the entire
   lesson: every batch array has a context counterpart.
3. *Validate before going live* — replay the wrapped bot through ``run_games``
   and eyeball the summary. This step is mandatory, not optional hygiene.

Run it directly (finishes in a few seconds, exits 0):

    POCKETROCKS_SKIP_VERSION_CHECK=1 python examples/train_batch_deploy_live.py
"""

from __future__ import annotations

import os

# Keep the example fully offline (same switch the test suite uses).
os.environ.setdefault("POCKETROCKS_SKIP_VERSION_CHECK", "1")

import numpy as np
from numpy.typing import NDArray

from pocketrocks import BotDecision, DecisionContext, PocketRocksBot
from pocketrocks.sim import BatchSimEngine, run_games
from pocketrocks.sim.sample_bots import GreedyValueBot, ValueTraderBot

PLAYER_COUNT = 3
CANDIDATES = 24  # random-search samples of (a, b)
GAMES_PER_CANDIDATE = 32  # 24 x 32 = 768 episodes, one batch, one pass


def batch_features(
    engine: BatchSimEngine,
    starting_cash: float,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Per-seat features from raw batch arrays: (estimated value, cash fraction).

    ``estimated_value[g, s]`` prices the upcoming resources using seat ``s``'s
    private signal: for each offered suit, hand copies + already-won copies
    index into the game's value chart. ``cash_fraction`` is cash / starting
    cash. ``BatchTrainedBot`` mirrors this computation field-for-field.
    """
    batch = engine.batch_size
    # hand_cards rows are 0-padded; counting matches ignores the padding.
    hand_counts = np.stack(
        [(engine.hand_cards == suit_id).sum(axis=2) for suit_id in range(1, 6)],
        axis=2,
    )
    signal = np.minimum(hand_counts + engine.won_counts, 5).astype(np.intp)
    estimated_value = np.zeros((batch, engine.player_count), dtype=np.float64)
    for slot in range(2):
        suits = engine.upcoming[:, slot].astype(np.intp)  # 0 means empty slot
        columns = np.maximum(suits - 1, 0)[:, None, None]
        levels = np.take_along_axis(
            signal,
            np.broadcast_to(columns, (batch, engine.player_count, 1)),
            axis=2,
        )[:, :, 0]
        values = np.take_along_axis(engine.value_charts, levels, axis=1)
        estimated_value += np.where((suits > 0)[:, None], values, 0)
    cash_fraction = engine.cash.astype(np.float64) / starting_cash
    return estimated_value, cash_fraction


def policy_bids(
    a: NDArray[np.float64],
    b: NDArray[np.float64],
    estimated_value: NDArray[np.float64],
    cash_fraction: NDArray[np.float64],
    legal_max: NDArray[np.int16],
) -> NDArray[np.int64]:
    """bid = clip(round(a * estimated_value + b * cash_fraction), 0, legal_max)."""
    raw = np.rint(a * estimated_value + b * cash_fraction).astype(np.int64)
    clipped = np.minimum(np.maximum(raw, 0), legal_max.astype(np.int64))
    return np.asarray(clipped, dtype=np.int64)


def train() -> tuple[float, float, float]:
    """Random-search (a, b), all candidates vectorized into one batch.

    Seat 0 plays the candidate policy; the other seats play a fixed baseline
    (bid a third of the legal maximum). Fitness is seat 0's mean final score
    across that candidate's games.
    """
    rng = np.random.default_rng(7)
    a_by_candidate = rng.uniform(0.0, 2.0, size=CANDIDATES)
    b_by_candidate = rng.uniform(0.0, 30.0, size=CANDIDATES)
    # Row layout: candidate c owns rows [c * GAMES_PER_CANDIDATE, (c + 1) * ...).
    a_by_row = np.repeat(a_by_candidate, GAMES_PER_CANDIDATE)[:, None]
    b_by_row = np.repeat(b_by_candidate, GAMES_PER_CANDIDATE)[:, None]

    engine = BatchSimEngine.start(
        player_count=PLAYER_COUNT,
        seeds=tuple(
            f"train-{row % GAMES_PER_CANDIDATE}"  # same seeds for every candidate
            for row in range(CANDIDATES * GAMES_PER_CANDIDATE)
        ),
    )
    starting_cash = float(engine.cash[0, 0])  # uniform before the first turn

    while engine.flip_actions().any():
        legal_max = engine.legal_max_bids()
        estimated_value, cash_fraction = batch_features(engine, starting_cash)
        # Baseline for every seat, then overwrite seat 0 with the candidate.
        bids = np.asarray(legal_max, dtype=np.int64) // 3
        candidate = policy_bids(
            a_by_row[:, 0], b_by_row[:, 0], estimated_value[:, 0],
            cash_fraction[:, 0], legal_max[:, 0],
        )
        bids[:, 0] = candidate
        outcome = engine.resolve_bids(bids)
        # Reveal the first hand card wherever a reveal is pending; -1 is the
        # explicit no-reveal sentinel. BatchSimEngine raises on out-of-range
        # indices (fail-fast for RL) — the live runtime would fall back instead.
        reveals = np.full(engine.batch_size, -1, dtype=np.int64)
        reveals[outcome.reveal_modes > 0] = 0
        engine.apply_reveals(reveals)

    totals = engine.scores().total.astype(np.float64)
    fitness = totals[:, 0].reshape(CANDIDATES, GAMES_PER_CANDIDATE).mean(axis=1)
    best = int(np.argmax(fitness))
    return float(a_by_candidate[best]), float(b_by_candidate[best]), float(fitness[best])


class BatchTrainedBot(PocketRocksBot):
    """The batch-trained policy behind the live decision interface.

    ``choose_decision`` recomputes ``batch_features`` from ``DecisionContext``
    fields. This mapping block is the bridge — get one row wrong and the bot
    silently plays a different policy live than the one you trained:

        batch array (this seat's slice)      DecisionContext counterpart
        -------------------------------      -----------------------------------------
        legal_max_bids()[g, s]           <-> legal_max_amount
        cash[g, s]                       <-> cash_by_seat[bot_seat]
        won_counts[g, s, suit - 1]       <-> won_resource_counts_by_seat[bot_seat][suit - 1]
        upcoming[g, slot]                <-> current_resource_ids[slot]
        hand_cards[g, s] (0-padded)      <-> current_hand_suit_ids (no padding)
        value_charts[g, level]           <-> value_chart[level]
    """

    def __init__(self, a: float, b: float) -> None:
        super().__init__()
        self._a = a
        self._b = b

    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        if context.decision_kind != "submitBid":
            # Training always revealed index 0; the deployed bot must match.
            return BotDecision.select_info_to_reveal(0)
        seat = context.bot_seat
        won = context.won_resource_counts_by_seat[seat]
        hand = context.current_hand_suit_ids
        estimated_value = 0.0
        for suit_id in context.current_resource_ids:
            if suit_id:
                signal = sum(1 for s in hand if s == suit_id) + won[suit_id - 1]
                estimated_value += context.value_chart[min(signal, 5)]
        cash_fraction = context.cash_by_seat[seat] / context.starting_cash
        legal_max = context.legal_max_amount or 0
        raw = round(self._a * estimated_value + self._b * cash_fraction)
        return BotDecision.submit_bid(min(max(raw, 0), legal_max))


def main() -> None:
    a, b, fitness = train()
    print(f"best params: a={a:.3f} b={b:.3f} (train mean score {fitness:.1f})")

    # Mandatory before going live: run_games exercises the exact context and
    # decision path the live server uses, so a bad batch->context field mapping
    # shows up here as a losing (or crashing) bot instead of in a live game.
    summary = run_games([BatchTrainedBot(a, b), GreedyValueBot, ValueTraderBot], 200)
    print(summary)


if __name__ == "__main__":
    main()
