# PocketRocks Python SDK

Python SDK for building, training, and connecting PocketRocks bots. Train
locally against the canonical rules engine; deploy the same class to the live
server.

**This is a connector and training library, not a place to build your bot.**
You install it into your *own* project and write your bot there — the same
way you'd install `requests` or `numpy`. This repo is the SDK's source code;
it is not your bot's home. Think of it as the plug, not the appliance — even
though the appliance now includes a test bench: `pocketrocks.sim` lets you
train and evaluate your bot offline, but that training happens in *your*
project too, against the same `PocketRocksBot` class you'll deploy live.

- ✅ **Do:** create your own project, install this SDK into a virtual
  environment, and write (and train) your bot against its API.
- ❌ **Don't:** build, edit, or run your bot inside this repository.

If you just want to get a bot running, **start here → [`starter/`](starter/)**.
It's a copy-paste project template with step-by-step instructions.

---

## Quickstart (5 steps)

You need **Python 3.10+** (`python3 --version`). The [`starter/`](starter/)
folder has the fully commented version of these steps; the short version:

```bash
# 1. Copy the starter template out to its own folder and go there
cp -r starter ~/my-pocketrocks-bot && cd ~/my-pocketrocks-bot

# 2. Create + activate an isolated virtual environment
python3 -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate

# 3. Install the SDK (and its dependencies)
pip install -r requirements.txt

# 4. Add your keys
cp .env.example .env      # then edit .env and paste your API key + bot ID

# 5. Run it
python bot.py             # Ctrl+C to stop
```

Your bot logic lives in one method — `choose_decision` in `bot.py`. Edit that,
rerun `python bot.py`, repeat.

### Where do my keys go?

Your API key and bot ID come from your PocketRocks dashboard. You put them in a
`.env` file in your bot's project folder — **never in the code**:

```
POCKETROCKS_API_KEY=your-real-key
POCKETROCKS_BOT_ID=your-bot-id
POCKETROCKS_SERVER_URL=wss://pocketrocks.xyz
```

The SDK loads `.env` automatically when your bot starts. `.env` is git-ignored
so your secret key stays local. (Prefer to pass values in code instead? Every
setting is also a constructor argument — see [Configuration](#configuration).)

---

## Local training & simulation

You don't need a server, an API key, or a bot ID to develop your strategy.
`pocketrocks.sim` runs the exact same rules engine the live server uses,
entirely in-process, against the exact same `PocketRocksBot` subclass you
deploy live — no separate "training" API to learn.

### One game: `LocalGame`

```python
from pocketrocks.sim import LocalGame

result = LocalGame(
    [MyBot(), OtherBot()],
    seed=0,                     # anything hashable-as-string; same seed -> same game
    value_chart="A",
    objectives_enabled=True,
    decision_budget_ms=60_000,
    record_decisions=False,
).play()

print(result.ranking)   # seats, best to worst
print(result.scores)    # one ScoreRow per seat
```

`LocalGame` takes 3-5 bot instances and plays one seeded game synchronously
(`play()`) or as a coroutine (`await play_async()`). A bot that raises or
returns an illegal decision doesn't crash the game — it gets the live
server's timeout fallback (bid 0 / reveal the first card), exactly as it
would in production. Note that the local sim does not enforce the decision
time budget itself (it just reports `decision_budget_ms` through
`remaining_deadline_ms`) — only the live server actually times out a slow
decision, so latency-sensitive bots should still be load-tested against a
real server with realistic budgets before deploying.

### Many games: `run_games`

```python
from pocketrocks.sim import run_games

summary = run_games(
    [MyBot, OtherBot, ThirdBot],   # see "providers" below
    n_games=500,
    seeds=None,          # default: "game-0", "game-1", ... ; or pass your own
    rotate_seats=True,   # rotate providers through seats so seat bias averages out
    workers=1,           # >1 uses a process pool
    value_chart="A",
    record_decisions=False,
    decision_budget_ms=60_000,
)
print(summary)   # win rate, mean score, and wins-by-seat per bot
```

`run_games` plays `n_games` seeded `LocalGame`s and returns a
`BenchmarkSummary` — per-bot `BotStats` (win rate, mean score, wins/games by
seat) plus the raw `GameResult`s (kept in full when `record_decisions=True`
or `n_games` is small; otherwise dropped to keep memory bounded).

### Providers: instance, class, or factory

Each entry in the list you pass to `run_games` (a `BotProvider`) can be:

- **An instance** — `MyBot()`. Only valid with `workers=1`. With multiple
  workers the instance would have to be pickled into each worker process, and
  any state it accumulated there would be silently lost — so `run_games`
  raises instead of returning a wrong result.
- **A class** — `MyBot`. Instantiated fresh, once per game, inside the
  worker. Safe with any `workers` value.
- **A zero-arg factory** — a module-level function, e.g.
  `def make_bot(): return MyBot(...)`. Instantiated the same way as a class.
  This is the pattern for evaluating an RL policy: have the factory load and
  memoize your model weights in a module-level global the first time it's
  called in a given worker process, so the (possibly expensive) load happens
  once per worker, not once per game. Prefer a named function over a
  `lambda` here — with `workers>1` the factory has to be pickled to reach the
  worker process, and lambdas aren't picklable under Windows' `spawn` start
  method. A `lambda` is fine only if you're pinned to `workers=1`.

To collect what your bot actually saw and did — for RL training data or
debugging — pass `record_decisions=True` and read `result.decisions`
(`DecisionRecord`: turn index, seat, decision kind, the exact
`DecisionContext`, the bot's `BotDecision`, and whether a fallback fired).
Don't try to recover this from bot instance state — with `workers>1` your
instance never comes back from the worker process, and even with `workers=1`
a fresh instance is constructed per game for class/factory providers.

### Sample opponents

```python
from pocketrocks.sim.sample_bots import AlwaysPassBot, RandomBot, GreedyValueBot, ValueTraderBot
```

Four ready-made opponents, ordered roughly weakest to strongest, ship inside
the package so a starter project can import them without copying code:
`AlwaysPassBot` (bids nothing), `RandomBot(seed=...)` (uniform random legal
bids, seeded), `GreedyValueBot` (bids proportional to its hand's implied
value in the offered suits), and `ValueTraderBot` (chases suits it holds
information about, conserves cash otherwise). Benchmark your bot against them
with `run_games([MyBot, GreedyValueBot, ValueTraderBot, AlwaysPassBot], 500)`.

### Determinism

Same `seed`, same bots, same moves, every time: `LocalGame` and `run_games`
seed the engine's RNG from the `seed` you pass (a `run_games` game's seed
defaults to `f"game-{i}"` but you can supply your own list). Anything your
bot itself does — e.g. a `RandomBot(seed=...)` — is only reproducible if you
seed *that* too; the sim doesn't reach into your bot's internals.

### Staying in sync with the live rules

Local results are only meaningful if the local rules match the ones the live
server enforces. Every `LocalGame`/`run_games` call does a best-effort,
silent, at-most-once-per-process check against this repo's default branch and
logs a warning if a newer SDK — especially one with a game **rules** change —
is available. It never blocks or raises; if you're offline, or you want to
turn it off entirely (e.g. in CI), set:

```bash
export POCKETROCKS_SKIP_VERSION_CHECK=1
```

### Watch your bot play

Local sim is for fast iteration — at some point you'll want to see your bot
in an actual game against other people:

1. Run your bot for real: `python bot.py` (needs the `.env` credentials from
   [Quickstart](#quickstart-5-steps)).
2. Open [pocketrocks.xyz](https://pocketrocks.xyz) in your browser.
3. Create a room.
4. Invite your bot to the room and start the game.

---

## Writing your bot

Subclass `PocketRocksBot` and implement `choose_decision`. That's the whole
contract — attach your strategy to that one function:

```python
from pocketrocks import BotDecision, DecisionContext, PocketRocksBot


class MyBot(PocketRocksBot):
    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        if context.decision_kind == "submitBid":
            if context.legal_max_amount is None or context.legal_max_amount <= 0:
                return BotDecision.pass_turn()
            return BotDecision.submit_bid(context.legal_max_amount)
        return BotDecision.select_info_to_reveal(0)


if __name__ == "__main__":
    MyBot().run()
```

`run()` reads your `.env`, connects, and keeps the bot alive — handling
authentication, heartbeats, reconnects, and concurrent games for you.

More runnable examples are in [`examples/`](examples/): a
[`simple_bot`](examples/simple_bot.py), a [`random_bot`](examples/random_bot.py),
and a protocol-aware [`raw_frame_bot`](examples/raw_frame_bot.py).

---

## Testing your bot

The SDK ships a test kit at `pocketrocks.testing` so you can exercise your
`choose_decision` without a live server. Narrate a game situation and derive the
exact `DecisionContext` your bot would see — it runs through the same
reconstruction the real wire uses, so the context is one a real game could reach:

```python
from pocketrocks import ActionId, Suit
from pocketrocks.testing import scenario


async def test_my_bot_bids_the_max():   # choose_decision is a coroutine
    ctx = (
        scenario(players=3, starting_cash=20)
        .turn(ActionId.AUCTION1, resources=(Suit.BRICK, Suit.WOOD))
        .auction(bids={0: 4, 1: 0, 2: 0})   # seat 0 wins for $4
        .deciding(seat=1, hand=[Suit.BRICK, Suit.ORE], kind="submitBid")
        .to_context()
    )
    assert await MyBot(api_key="x", bot_id="y").choose_decision(ctx) == ...
```

Need a value the narration can't reach (say `legal_max_amount == 0`)? Add
`.override(legal_max_amount=0)` before `.to_context()`.

To drive the whole runtime end-to-end, feed `.to_bytes()` through the shipped
`FakeTransport`:

```python
from pocketrocks.testing import FakeTransport, decode_frames, scenario

transport = FakeTransport([scenario(players=3, starting_cash=20)
                           .deciding(seat=0, hand=[Suit.BRICK], kind="submitBid")
                           .to_bytes()])
await MyBot(api_key="x", bot_id="y", reconnect=False, transport=transport).run_async()
sent = decode_frames(transport.sent_messages)   # inspect what your bot replied
```

---

## Bot API reference

> **Full type reference:** [`TYPES.md`](TYPES.md) documents every public type
> — `PocketRocksBot`, `BotDecision`, `DecisionContext` (all fields), and
> `RuntimeEvent`. The essentials are below.
>
> **Decoding the ids:** the context gives you raw action/suit/objective ids.
> Use the `ActionId` / `Suit` / `OBJECTIVES` / `describe_*` helpers exported from
> `pocketrocks` instead of magic numbers — full ID tables are in
> [`MAPPINGS.md`](MAPPINGS.md).

### `choose_decision(context) -> BotDecision`

Called whenever the server needs a move. Return one of:

| Move | Meaning |
| --- | --- |
| `BotDecision.pass_turn()` | Take no action this turn |
| `BotDecision.submit_bid(amount)` | Bid `amount` |
| `BotDecision.select_info_to_reveal(index)` | Reveal the card at `index` |

Useful fields on `context` (`DecisionContext`): `decision_kind`
(`"submitBid"` or `"selectInfoToReveal"`), `legal_max_amount`,
`revealable_count`, `bot_seat`, `cash_by_seat`, `player_count`, and
`remaining_deadline_ms`. See [`TYPES.md`](TYPES.md#decisioncontext) for every
field with its type and meaning.

### Optional runtime hooks

Override any of these coroutines as needed; all are no-ops by default:

- `on_connect()` / `on_disconnect()`
- `on_runtime_event(event)` — observe lifecycle events
- `on_error(error)` — observe recoverable per-request errors

`RuntimeEvent.kind` values: `connected`, `disconnected`, `connectionRejected`,
`connectionError`, `heartbeatReceived`, `heartbeatSent`, `requestQueued`,
`requestDropped`, `requestCompleted`, `requestFailed`, `malformedFrame`.

### Protocol-aware bots

For bots that need the raw wire frame, override `choose_raw_decision(frame,
context)` instead of `choose_decision` — see
[`examples/raw_frame_bot.py`](examples/raw_frame_bot.py).

---

## Configuration

Every setting can be provided two ways — as an environment variable (usually via
`.env`) **or** as a constructor argument to your bot (which takes precedence):

```python
MyBot(api_key="...", bot_id="123", server_url="wss://host").run()
```

| Environment variable | Constructor arg | Required? | Default |
| --- | --- | --- | --- |
| `POCKETROCKS_API_KEY` | `api_key` | **Yes** | — |
| `POCKETROCKS_BOT_ID` | `bot_id` | **Yes** | — |
| `POCKETROCKS_SERVER_URL` | `server_url` | No | `wss://pocketrocks.xyz` |
| `POCKETROCKS_BOT_CAPACITY` | `capacity` | No | `1` |
| `POCKETROCKS_PROTOCOL_VERSION` | `protocol_version` | No | `2` |
| `POCKETROCKS_MAX_IN_FLIGHT_DECISIONS` | `max_in_flight_decisions` | No | `4` |
| `POCKETROCKS_MAX_QUEUE_SIZE` | `max_queue_size` | No | `32` |
| `POCKETROCKS_MIN_REMAINING_DEADLINE_MS_TO_START` | `min_remaining_deadline_ms_to_start` | No | `100` |
| `POCKETROCKS_REQUEST_TIMEOUT_SLACK_MS` | `request_timeout_slack_ms` | No | `25` |
| `POCKETROCKS_RECONNECT` | `reconnect` | No | `true` |
| `POCKETROCKS_RECONNECT_BASE_DELAY_SECONDS` | `reconnect_base_delay_seconds` | No | `0.5` |
| `POCKETROCKS_RECONNECT_MAX_DELAY_SECONDS` | `reconnect_max_delay_seconds` | No | `8` |
| `POCKETROCKS_REJECTED_RECONNECT_MAX_DELAY_SECONDS` | `rejected_reconnect_max_delay_seconds` | No | `60` |
| `POCKETROCKS_LOG_LEVEL` | — | No | `INFO` |

The annotated template is [`.env.example`](.env.example).

---

## How the SDK behaves at runtime

You don't have to manage any of this — it's handled for you:

- Connects to `GET /api/bots/connect` with bearer API-key auth, speaking binary
  bot-wire protocol version `2`.
- Answers heartbeats automatically on the read loop.
- Processes decisions in parallel via a bounded worker pool; writes are
  serialized so concurrent tasks can't corrupt the socket.
- Treats overload as normal: requests whose remaining deadline is too small, or
  that arrive when the queue is full, are dropped rather than crashing the bot.
- Surfaces every drop/failure through `on_runtime_event(...)` / `on_error(...)`.
- Reconnects with exponential backoff (jittered) when enabled.

---

## Developing the SDK itself

The rest of this section is **only** for people modifying this SDK — not for
writing a bot (for that, use [`starter/`](starter/)).

```bash
git clone git@github.com:jaiparera/pocketrocks-python-sdk.git
cd pocketrocks-python-sdk
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"     # editable install with dev tools
pytest                       # run the test suite
ruff check . && mypy src     # lint + type-check
```

### Vendored protocol package

The generated Python bot-wire package is vendored under
[`src/pocketrocks/internal/bot_wire_v2`](src/pocketrocks/internal/bot_wire_v2).

- Upstream source: `../pocketrocks/packages/shared/python/pocketrocks_bot_wire`
- Protocol version: `2`
- Parity is verified by a golden-fixture test in
  [`tests/test_external_bot_runtime.py`](tests/test_external_bot_runtime.py).

### Benchmarks

```bash
python benchmarks/measure_runtime.py
```

Reports decode time, decode-plus-reconstruct time, and a synthetic concurrent
throughput scenario. Sample results are committed in
[`benchmarks/sample_results.md`](benchmarks/sample_results.md).
