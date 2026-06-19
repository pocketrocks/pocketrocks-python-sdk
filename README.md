# PocketRocks Python SDK

Python SDK for long-running PocketRocks external bots using the live websocket
protocol from `../pocketrocks/docs/openapi/server-api.yaml`.

## Install

```bash
pip install -e .[dev]
```

## What It Does

- Connects to `GET /api/bots/connect` with bearer API-key auth.
- Speaks protocol version `2` over binary bot-wire frames.
- Answers heartbeat requests automatically.
- Reconstructs decision requests into a typed high-level context.
- Supports raw-frame bot callbacks for protocol-aware bots.
- Handles concurrent in-flight decisions with bounded queueing and deadline-aware
  dropping.
- Contains request-level errors so the process can run for a long time.

## Environment Variables

Copy `.env.example` and set:

- `POCKETROCKS_API_KEY`
- `POCKETROCKS_BOT_ID`
- `POCKETROCKS_SERVER_URL`
- `POCKETROCKS_BOT_CAPACITY`
- `POCKETROCKS_PROTOCOL_VERSION`
- `POCKETROCKS_MAX_IN_FLIGHT_DECISIONS`
- `POCKETROCKS_MAX_QUEUE_SIZE`
- `POCKETROCKS_MIN_REMAINING_DEADLINE_MS_TO_START`
- `POCKETROCKS_REQUEST_TIMEOUT_SLACK_MS`
- `POCKETROCKS_RECONNECT`
- `POCKETROCKS_RECONNECT_BASE_DELAY_SECONDS`
- `POCKETROCKS_RECONNECT_MAX_DELAY_SECONDS`

## Public API

```python
from pocketrocks import BotDecision, DecisionContext, PocketRocksBot, RuntimeEvent
```

## High-Level Bot Example

```python
from pocketrocks import BotDecision, DecisionContext, PocketRocksBot


class ExampleBot(PocketRocksBot):
    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        if context.decision_kind == "submitBid":
            if context.legal_max_amount is None or context.legal_max_amount <= 0:
                return BotDecision.pass_turn()
            return BotDecision.submit_bid(context.legal_max_amount)
        return BotDecision.select_info_to_reveal(0)


if __name__ == "__main__":
    ExampleBot().run()
```

## Raw Frame Example

```python
from pocketrocks import BotDecision, DecisionContext, PocketRocksBot


class RawBot(PocketRocksBot):
    async def choose_decision(self, context: DecisionContext) -> BotDecision:
        raise RuntimeError("raw callback should be used")

    async def choose_raw_decision(self, frame: object, context: DecisionContext) -> BotDecision:
        if frame.decision_kind == "submitBid":
            return BotDecision.submit_bid(1)
        return BotDecision.select_info_to_reveal(0)
```

## Runtime Hooks

Override these coroutine hooks as needed:

- `on_connect()`
- `on_disconnect()`
- `on_runtime_event(event)`
- `on_error(error)`

`RuntimeEvent.kind` currently includes:

- `connected`
- `disconnected`
- `heartbeatReceived`
- `heartbeatSent`
- `requestQueued`
- `requestDropped`
- `requestCompleted`
- `requestFailed`
- `malformedFrame`

## Deadline And Overload Handling

The SDK treats overload as a normal operating condition.

- Requests whose remaining deadline is already too small are dropped before
  work starts.
- Requests can also be dropped when the runtime queue is full.
- Decision callbacks are bounded by the remaining deadline minus configurable
  slack.
- Every drop/failure path is surfaced through `on_runtime_event(...)` and
  `on_error(...)` rather than crashing the process.

## Long-Running Behavior

- Heartbeats are handled on the read loop and written immediately.
- Decision work is processed in parallel by a bounded worker pool.
- Write operations are serialized so concurrent tasks do not corrupt the socket.
- Per-request callback failures are isolated to that request.
- Optional reconnect behavior uses exponential backoff.

## Vendored Protocol Package

The generated Python bot-wire package is vendored under
`src/pocketrocks/internal/bot_wire_v2`.

- Upstream source: `../pocketrocks/packages/shared/python/pocketrocks_bot_wire`
- Protocol version: `2`
- Verification: `tests/test_external_bot_runtime.py` includes a golden fixture
  parity test.

## Benchmarks

Run the local benchmark harness:

```bash
py benchmarks\measure_runtime.py
```

This reports decode time, decode-plus-reconstruct time, and a synthetic
concurrent throughput scenario for payloads up to 5 players and 20 turns deep.

Sample results are committed in
`benchmarks/sample_results.md`.
