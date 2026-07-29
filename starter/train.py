"""Train and evaluate your bot locally — no server, no credentials needed.

Edit ``choose_decision`` in bot.py, then:  python train.py
When your win rate beats the samples, go live:  python bot.py
"""

from bot import MyBot  # your bot class in bot.py

from pocketrocks.sim import LocalGame, run_games
from pocketrocks.sim.sample_bots import AlwaysPassBot, GreedyValueBot, ValueTraderBot


def main() -> None:
    # Fast sanity check: one inspectable game.
    result = LocalGame([MyBot(), GreedyValueBot(), ValueTraderBot()], seed=0).play()
    print(f"single game ranking (seats): {result.ranking}")

    # The real signal: many games, rotated seats.
    summary = run_games(
        [MyBot, GreedyValueBot, ValueTraderBot, AlwaysPassBot],
        n_games=500,
        rotate_seats=True,
    )
    print(summary)
    # RL evaluation tip: pass a zero-arg factory that memoizes your model load
    # in a module global, and scale with workers=N. Collect trajectories with
    # record_decisions=True — never from bot instance state.


if __name__ == "__main__":
    main()
