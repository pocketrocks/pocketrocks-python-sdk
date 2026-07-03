# PocketRocks Python SDK

Python SDK for connecting long-running external bots to a PocketRocks server.

**This is a connector library, not a place to build your bot.** You install it
into your *own* project and write your bot there — the same way you'd install
`requests` or `numpy`. This repo is the SDK's source code; it is not your bot's
home. Think of it as the plug, not the appliance.

- ✅ **Do:** create your own project, install this SDK into a virtual
  environment, and write your bot against its API.
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
