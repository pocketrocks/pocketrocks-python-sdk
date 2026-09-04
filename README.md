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

### Choosing the rules: `Ruleset`

Every entry point below plays under a `Ruleset` — the same four facts the
live server's ruleset carries, in snake_case:

```python
from pocketrocks.sim import Ruleset

Ruleset(
    player_count=3,  # 3-5
    value_chart="A",  # a fixed chart key A-E, or an inline chart (below)
    payment_rule="first-price",  # or "second-price"
    objectives_enabled=True,
)
```

The five fixed value charts (index = cards of one suit you hold, 0-5):

| Key | Cells | Shape |
| --- | --- | --- |
| `A` | `(0, 4, 8, 12, 16, 20)` | linear, ascending |
| `B` | `(20, 16, 12, 8, 4, 0)` | linear, descending |
| `C` | `(0, 2, 5, 9, 14, 20)` | curved, ascending |
| `D` | `(20, 18, 15, 11, 6, 0)` | curved, descending |
| `E` | `(0, 4, 10, 18, 6, 0)` | hump |

A **custom value chart** is an inline 6-tuple instead of a key. Cells may be
negative. It must sit inside the constraint envelope the server generates
custom charts under — every cell within ±20, at most one turning point, a sum
of at least 38 (so `E` is the minimum any chart totals), and valleys (fall then
rise) need a sum of at least 75 and no cell below 2 — or construction raises
naming the violated constraint:

```python
Ruleset(player_count=3, value_chart=(-20, 0, 20, 20, 10, 8))  # a hump with a negative cell
Ruleset(player_count=3, value_chart=(0, 2, 4, 6, 8, 10))  # ValueError: breaks the sum floor
```

The **payment rule** decides what the auction winner pays. Under
`"first-price"` the winner pays their own bid; under `"second-price"` the
winner pays the runner-up bid (a lone positive bid pays 0). The highest bidder
wins under either rule, but the rule flips optimal bidding: shade below your
value under first-price, bid your value truthfully under second-price.

```python
Ruleset(player_count=4, value_chart="C", payment_rule="second-price")
```

`LocalGame`, `run_games`, `SimEngine` and `BatchSimEngine` all take
`ruleset=`; they also keep `value_chart=` / `payment_rule=` /
`objectives_enabled=` keywords as a convenience that builds the same
`Ruleset` for you (pass one style or the other, not both). Bots never see the
key: `DecisionContext.value_chart` is always the resolved cells.

### One game: `LocalGame`

```python
from pocketrocks.sim import LocalGame, Ruleset

result = LocalGame(
    [MyBot(), OtherBot(), ThirdBot()],
    seed=0,  # anything hashable-as-string; same seed -> same game
    ruleset=Ruleset(player_count=3, value_chart="A", payment_rule="first-price"),
    decision_budget_ms=60_000,
    record_decisions=False,
).play()

print(result.ranking)  # seats, best to worst
print(result.scores)  # one ScoreRow per seat
```

`LocalGame` takes 3-5 bot instances and plays one seeded game synchronously
(`play()`) or as a coroutine (`await play_async()`). A bot that raises, times
out, or returns an *unrepairable* decision doesn't crash the game — it gets the
live server's timeout fallback (bid 0 / reveal the first card), exactly as it
would in production. A decision the server would *repair* is treated as the
server would treat it, not collapsed to the fallback: an over-max bid is
forwarded and the engine clamps it to the legal maximum (matching `recordBid`),
and a bid the wire can't carry (negative, or above the wire limit) is corrected
into range and then clamped. So an overbidding bot competes for the auction in
the sim exactly as it would live, rather than training against a 0-bid penalty
that production never applies. A decision the SDK flags as *illegal* — whether
it is discarded to the fallback, forwarded, or corrected — is reported to your
`on_runtime_event` / `on_error` hooks off the game's path, by a background
reporter. A bot that *raises* or times out is caught and given the fallback but
is **not** surfaced through those hooks; only decisions the SDK inspects and
rejects are reported. Delivery is best-effort: a slow or hanging hook never
stalls the game, but its report (and any queued behind it) may be dropped at
game end with a logged warning.
Note that the local sim does not enforce the decision
time budget itself (it just reports `decision_budget_ms` through
`remaining_deadline_ms`) — only the live server actually times out a slow
decision, so latency-sensitive bots should still be load-tested against a
real server with realistic budgets before deploying.

### Many games: `run_games`

```python
from pocketrocks.sim import run_games

summary = run_games(
    [MyBot, OtherBot, ThirdBot],  # see "providers" below
    n_games=500,
    seeds=None,  # default: "game-0", "game-1", ... ; or pass your own
    rotate_seats=True,  # rotate providers through seats so seat bias averages out
    workers=1,  # >1 uses a process pool
    ruleset=Ruleset(player_count=3, value_chart="A", payment_rule="second-price"),
    record_decisions=False,
    decision_budget_ms=60_000,
)
print(summary)  # win rate, mean score, and wins-by-seat per bot
```

`run_games` plays `n_games` seeded `LocalGame`s and returns a
`BenchmarkSummary` — per-bot `BotStats` (win rate, mean score, wins/games by
seat) plus the raw `GameResult`s (kept in full when `record_decisions=True`
or `n_games` is small; otherwise dropped to keep memory bounded).

### Vectorized RL batches: `BatchSimEngine`

For RL systems that already choose actions in batches, `BatchSimEngine` keeps
all games in compact NumPy arrays and resolves a phase for the whole batch per
Python call. It intentionally skips bot callbacks, wire contexts, snapshots,
and event objects:

```python
import numpy as np

from pocketrocks.sim import BatchSimEngine

engine = BatchSimEngine.start(
    player_count=3,
    seeds=tuple(f"episode-{index}" for index in range(1024)),
    # Optional per-row rules, each one entry per seed (defaults: A, first-price, on):
    value_charts=tuple("ABCDE"[index % 5] for index in range(1024)),  # keys or inline 6-tuples
    payment_rules=tuple("second-price" if index % 2 else "first-price" for index in range(1024)),
    objectives_enabled=tuple(True for _ in range(1024)),
    # ...or `rulesets=(Ruleset(...), ...)` in place of the three sequences.
)
while (actions := engine.flip_actions()).any():
    legal = engine.legal_max_bids()
    bids = np.zeros_like(legal)  # replace with batched policy output
    outcome = engine.resolve_bids(bids)
    reveals = np.full(engine.batch_size, -1, dtype=np.int8)
    reveals[outcome.reveal_modes > 0] = 0
    engine.apply_reveals(reveals)

scores = engine.scores()
rankings = engine.rankings()
```

One batch has a homogeneous player count; value charts, payment rules and
objective flags may vary by row (`engine.rulesets` holds one `Ruleset` per row). Use `SimEngine` or `LocalGame` when you need the traditional
single-game interface, bot callbacks, or canonical trace objects. `SimEngine`
is a size-one facade over the same batch rules kernel, so scalar and bulk rules
cannot drift.

Calls follow a strict phase order:
`flip_actions()` → `legal_max_bids()` / `resolve_bids()` →
`apply_reveals()`. Call `apply_reveals()` after every resolve, including turns
where every row uses the `-1` no-reveal sentinel. `reveal_modes` uses `0` for
none, `1` for an automatic single-card reveal, and `2` for a policy choice.
Terminal rows return action `0`, winner seat `-1`, and paid amount `0`.

The main policy-facing arrays are fixed-shape numeric values:

| Value | Shape | dtype |
| --- | --- | --- |
| legal bids / submitted bids | `(batch, players)` | signed integer |
| action IDs / reveal modes | `(batch,)` | `uint8` |
| reveal indices | `(batch,)` | signed integer; `-1` means none |
| cash / score components | `(batch, players)` | signed integer |
| hand cards | `(batch, players, max_hand)` | `uint8`; `0` is padding |

`BatchSimEngine` is the throughput interface: batch size one still runs the
NumPy kernel and therefore pays fixed array setup/dispatch overhead.

#### From batch training to live play

A policy trained against batch arrays still deploys as a `PocketRocksBot`:
live games only speak the context/decision protocol. Every batch array a
policy reads has a `DecisionContext` counterpart — the wrapper bot recomputes
its features from these fields:

| Batch array (seat `s` of game `g`) | `DecisionContext` attribute |
| --- | --- |
| `legal_max_bids()[g, s]` | `legal_max_amount` |
| `cash[g, s]` | `cash_by_seat[bot_seat]` |
| `won_counts[g, s]` | `won_resource_counts_by_seat[bot_seat]` |
| `upcoming[g]` | `current_resource_ids` |
| `hand_cards[g, s]` (`0`-padded) | `current_hand_suit_ids` (no padding) |

Reveal indices live in the same space on both sides — an index into the
seat's current (compacted) hand — but batch uses the `-1` sentinel for rows
with no pending reveal, while a live bot is only asked when a choice exists.
The two runtimes also fail differently on purpose: `BatchSimEngine` raises on
invalid reveal indices or non-integer dtypes (fail-fast, so RL bugs surface at
the call site), while `LocalGame` and the live server apply the timeout
fallback instead.

[`examples/train_batch_deploy_live.py`](examples/train_batch_deploy_live.py)
is the worked path: train on batch arrays, wrap the policy in a bot, then —
always — validate the wrapped bot with `run_games` before pointing it at the
live server. That replay exercises the exact context/decision path the live
server uses, so feature-mapping mistakes show up offline instead of in a
live game.

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
  worker process, and lambdas aren't picklable. A `lambda` is fine only if
  you're pinned to `workers=1`.

To collect what your bot actually saw and did — for RL training data or
debugging — pass `record_decisions=True` and read `result.decisions`
(`DecisionRecord`: turn index, seat, decision kind, the exact
`DecisionContext`, the bot's original `BotDecision`, whether a fallback fired,
and — when the bot's bid could not be encoded and was corrected into wire range
— the `corrected` substitute actually dispatched to the engine, so training-data
consumers can tell the bot's intent from what the engine received).
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

The two value-estimating bots shade under first-price and bid their estimate
under second-price; tell them the rule at construction when the game is not
first-price — `GreedyValueBot(payment_rule="second-price")` (a zero-arg
factory, `lambda: GreedyValueBot(payment_rule="second-price")`, does the same
for `run_games` with `workers=1`).

### Determinism

Same `seed`, same bots, same moves, every time: `LocalGame` and `run_games`
seed the engine's RNG from the `seed` you pass (a `run_games` game's seed
defaults to `f"game-{i}"` but you can supply your own list; the empty string
is rejected). Anything your bot itself does — e.g. a `RandomBot(seed=...)` —
is only reproducible if you seed *that* too; the sim doesn't reach into your
bot's internals. One deliberate exception: the deadline fields
(`deadline_at`, `received_at`, `remaining_deadline_ms`) are stamped from the
real clock to model the live time budget, so a bot that branches on them is
excluded from the same-seed guarantee — read game state for strategy, use
deadline fields for budget management only.

### Staying in sync with the live rules

Local results are only meaningful if the local rules match the ones the live
server enforces. The SDK's `RULES_VERSION` (in `pocketrocks._version`) names
the rules revision the sim implements; it increments whenever the canonical
rules change. Every `LocalGame`/`run_games` call does a best-effort,
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


async def test_my_bot_bids_the_max():  # choose_decision is a coroutine
    ctx = (
        scenario(players=3, starting_cash=20)
        .turn(ActionId.AUCTION1, resources=(Suit.BRICK, Suit.WOOD))
        .auction(bids={0: 4, 1: 0, 2: 0})  # seat 0 wins for $4
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

transport = FakeTransport(
    [
        scenario(players=3, starting_cash=20)
        .deciding(seat=0, hand=[Suit.BRICK], kind="submitBid")
        .to_bytes()
    ]
)
await MyBot(api_key="x", bot_id="y", reconnect=False, transport=transport).run_async()
sent = decode_frames(transport.sent_messages)  # inspect what your bot replied
```

---

## Bot API reference

> **Full type reference:** [`docs/TYPES.md`](docs/TYPES.md) documents every public type
> — `PocketRocksBot`, `BotDecision`, `DecisionContext` (all fields), and
> `RuntimeEvent`. The essentials are below.
>
> **Decoding the ids:** the context gives you raw action/suit/objective ids.
> Use the `ActionId` / `Suit` / `OBJECTIVES` / `describe_*` helpers exported from
> `pocketrocks` instead of magic numbers — full ID tables are in
> [`docs/MAPPINGS.md`](docs/MAPPINGS.md).

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
`remaining_deadline_ms`. See [`docs/TYPES.md`](docs/TYPES.md#decisioncontext) for every
field with its type and meaning.

### Optional runtime hooks

Override any of these coroutines as needed; all are no-ops by default:

- `on_connect()` / `on_disconnect()`
- `on_runtime_event(event)` — observe lifecycle events
- `on_error(error)` — observe recoverable per-request errors

`RuntimeEvent.kind` values: `connected`, `disconnected`, `connectionRejected`,
`connectionError`, `heartbeatReceived`, `heartbeatSent`, `requestQueued`,
`requestDropped`, `requestCompleted`, `requestFailed`, `malformedFrame`,
`decisionRejected`.

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
| `POCKETROCKS_PROTOCOL_VERSION` | `protocol_version` | No | `3` (must equal the SDK's version; see [compatibility](#supported-rules--compatibility)) |
| `POCKETROCKS_MAX_IN_FLIGHT_DECISIONS` | `max_in_flight_decisions` | No | `4` |
| `POCKETROCKS_MAX_QUEUE_SIZE` | `max_queue_size` | No | `32` |
| `POCKETROCKS_MIN_REMAINING_DEADLINE_MS_TO_START` | `min_remaining_deadline_ms_to_start` | No | `100` |
| `POCKETROCKS_REQUEST_TIMEOUT_SLACK_MS` | `request_timeout_slack_ms` | No | `25` |
| `POCKETROCKS_RECONNECT` | `reconnect` | No | `true` |
| `POCKETROCKS_RECONNECT_BASE_DELAY_SECONDS` | `reconnect_base_delay_seconds` | No | `0.5` |
| `POCKETROCKS_RECONNECT_MAX_DELAY_SECONDS` | `reconnect_max_delay_seconds` | No | `8` |
| `POCKETROCKS_REJECTED_RECONNECT_MAX_DELAY_SECONDS` | `rejected_reconnect_max_delay_seconds` | No | `60` |
| `POCKETROCKS_LOG_LEVEL` | — | No | `INFO` |
| `POCKETROCKS_DEBUG` | `debug` | No | `false` |

The annotated template is [`.env.example`](.env.example).

---

## Supported rules & compatibility

**Payment rule.** A game is played under one of two payment rules, and your
bot is told which in `context.payment_rule`:

- `"first-price"` — the winner pays their own bid. Bidding your full valuation
  wins auctions at zero profit, so shading below it is rewarded.
- `"second-price"` (Vickrey) — the winner pays the second-highest bid. What you
  bid only decides *whether* you win, never *how much* you pay, so bidding your
  true valuation is the dominant strategy; shading only loses auctions you
  wanted.

The highest bidder wins under either rule (ties break clockwise from the
tiebreak seat); `cash_by_seat` already reflects whichever rule is in play. A
bot that ignores `payment_rule` and shades under second-price is leaving money
on the table.

**Value charts.** `context.value_chart` may be one of the five fixed charts or a
custom chart generated for that game, and custom charts may contain negative
cells (holding *n* of a suit can cost points). Read the six numbers; never
assume a chart shape.

**Protocol version.** The server serves exactly one bot-wire protocol version
at a time, and this SDK speaks exactly one (`3`). A handshake offering any
other version is rejected at connect time (HTTP 400, which the runtime treats
as fatal and stops), and the SDK refuses to start if
`POCKETROCKS_PROTOCOL_VERSION` / `protocol_version` names anything but its own
version. If the server has moved on, the fix is to upgrade, not to change the
setting:

```bash
pip install --upgrade git+https://github.com/jaiparera/pocketrocks-python-sdk.git
```

---

## How the SDK behaves at runtime

You don't have to manage any of this — it's handled for you:

- Connects to `GET /api/bots/connect` with bearer API-key auth, speaking binary
  bot-wire protocol version `3` — the only version this SDK speaks (see
  [Supported rules & compatibility](#supported-rules--compatibility)).
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
writing a bot (for that, use [`starter/`](starter/)). `uv` is the toolchain
entry point for setup, tests, and linting — see
[`CONTRIBUTING.md`](CONTRIBUTING.md) for the full contribution gate and
[`docs/README.md`](docs/README.md) for the documentation hub.

```bash
git clone git@github.com:jaiparera/pocketrocks-python-sdk.git
cd pocketrocks-python-sdk
uv sync --all-extras
```

### Vendored protocol package

The generated Python bot-wire package is vendored under
[`src/pocketrocks/internal/bot_wire`](src/pocketrocks/internal/bot_wire); its
`README.md` holds the sync procedure.

- Upstream source: `../pocketrocks/packages/shared/python/pocketrocks_bot_wire`
- Protocol version the SDK speaks: `3`, pinned once in
  `src/pocketrocks/protocol.py` (`PROTOCOL_VERSION`).
- Parity is verified byte for byte against the upstream golden fixtures in
  [`tests/test_protocol_wire_v3.py`](tests/test_protocol_wire_v3.py).

### Benchmarks

```bash
python benchmarks/measure_runtime.py
```

Reports decode time, decode-plus-reconstruct time, and a synthetic concurrent
throughput scenario. Sample results are committed in
[`benchmarks/sample_results.md`](benchmarks/sample_results.md).
