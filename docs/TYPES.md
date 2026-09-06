# Types reference

Everything you need to write a bot is importable from the top-level package:

```python
from pocketrocks import (
    PocketRocksBot,  # base class you subclass
    BotDecision,  # what you return from a decision
    DecisionContext,  # the game state you're given
    RuntimeEvent,  # lifecycle events (optional to use)
)
```

The context hands you bare integers (action ids, suit ids, objective ids). To
interpret them without magic numbers, the SDK also exports a **decoder ring**:

```python
from pocketrocks import (
    ActionId,  # IntEnum: LOAN10, AUCTION1, ...
    Suit,  # IntEnum: BRICK, WOOD, ORE, SHEEP, WHEAT
    OBJECTIVES,  # dict[int, ObjectiveInfo]
    ObjectiveInfo,
    SUIT_LABELS,  # dict[int, str]
    ACTION_DESCRIPTIONS,
    describe_action,
    describe_suit,
    describe_objective,
    objective_payout,  # int payout for an objective id
)
```

These names are the entire public API for *playing* — see the
[Reference](#reference-decoder-ring) section below, and
[`MAPPINGS.md`](MAPPINGS.md) for the full ID tables. Local simulation lives in
`pocketrocks.sim` (see the [README](../README.md#local-training--simulation));
its rules seam, [`Ruleset`](#ruleset-pocketrockssim), is documented at the end of
this file. Everything under `pocketrocks.internal` is an implementation detail
and may change without notice — don't import from it.

---

## `PocketRocksBot`

Abstract base class. Subclass it and implement `choose_decision`. Create an
instance and call `.run()` to connect and play.

### Methods you implement

| Method | Required | Description |
| --- | --- | --- |
| `async choose_decision(context: DecisionContext) -> BotDecision` | **Yes** | Called for every decision the server asks for. Return your move. |
| `async choose_raw_decision(frame, context: DecisionContext) -> BotDecision` | No | Override only if you need the raw wire frame. Defaults to calling `choose_decision`. |

### Lifecycle hooks you may override

All are `async`, optional, and no-ops by default:

| Hook | Called when |
| --- | --- |
| `async on_connect()` | The bot successfully connects. |
| `async on_disconnect()` | The connection drops. |
| `async on_runtime_event(event: RuntimeEvent)` | Any lifecycle event fires (see `RuntimeEvent`). |
| `async on_error(error: Exception)` | A recoverable, per-request error occurs. |

### Methods you call

| Method | Description |
| --- | --- |
| `run()` | Blocking. Installs logging, connects, and runs until stopped (Ctrl+C). |
| `async run_async()` | Same as `run()` but awaitable, for embedding in your own event loop. |

### Constructor

Every configuration value can be passed to `__init__` (takes precedence over the
environment / `.env`). All are optional except that `api_key` and `bot_id` must
resolve from *somewhere* — a constructor argument or an environment variable —
or construction raises `ValueError`.

```python
MyBot(
    api_key: str | None = None,
    bot_id: str | None = None,
    server_url: str | None = None,               # default "wss://pocketrocks.xyz"
    capacity: int | None = None,                 # default 1
    protocol_version: int | None = None,         # default 3; must equal it
    max_in_flight_decisions: int | None = None,  # default 4
    max_queue_size: int | None = None,           # default 32
    min_remaining_deadline_ms_to_start: int | None = None,  # default 100
    request_timeout_slack_ms: int | None = None, # default 25
    reconnect: bool | None = None,               # default True
    reconnect_base_delay_seconds: float | None = None,          # default 0.5
    reconnect_max_delay_seconds: float | None = None,           # default 8.0
    rejected_reconnect_max_delay_seconds: float | None = None,  # default 60.0
    debug: bool | None = None,                   # default False
)
```

`debug` (env: `POCKETROCKS_DEBUG`) is detail-only: it adds the full
[`DecisionContext`](#decisioncontext) to a
[`decisionRejected`](#decisionrejected-details) event's `details["context"]`, so
you can see exactly what your bot was looking at when it played an illegal move.
It never gates whether that event fires, whether the rejection is logged, or what
the SDK sends to the server.

---

## `BotDecision`

An immutable value describing your move. Build it with one of the three
classmethods — you never construct it by hand.

| Constructor | Meaning | `action_kind` | `value` |
| --- | --- | --- | --- |
| `BotDecision.pass_turn()` | Take no action this turn. | `"pass"` | `None` |
| `BotDecision.submit_bid(amount: int)` | Bid `amount`. | `"submitBid"` | `amount` |
| `BotDecision.select_info_to_reveal(card_index: int)` | Reveal the card at `card_index`. | `"selectInfoToReveal"` | `card_index` |

Fields (read-only): `action_kind: str`, `value: int | None`.

---

## `DecisionContext`

Immutable snapshot of the game state for one decision. Passed to
`choose_decision`. All fields are read-only.

### Which decision is this?

| Field | Type | Meaning |
| --- | --- | --- |
| `decision_kind` | `"submitBid" \| "selectInfoToReveal"` | What kind of move the server wants. Branch on this. |
| `legal_max_amount` | `int \| None` | For `"submitBid"`: the highest bid you're allowed to make (accounts for available loans). `None` when not bidding. |
| `revealable_count` | `int` | For `"selectInfoToReveal"`: valid indices are `0 .. revealable_count - 1`. |

### Timing

| Field | Type | Meaning |
| --- | --- | --- |
| `request_id` | `str` | Unique ID of this request. |
| `deadline_at` | `int` | Timestamp (ms) by which the server needs your answer. |
| `received_at` | `int` | Timestamp (ms) when the SDK received the request. |

For how long you have left, use the derived `remaining_deadline_ms` property
([below](#derived-computed-properties)).

### Where you sit

| Field | Type | Meaning |
| --- | --- | --- |
| `bot_seat` | `int` | Your seat index (`0`-based). |
| `tiebreak_seat` | `int` | Seat that currently holds the tiebreak marker (and is the one revealing info). Ties are **not** won by this seat directly: resolution starts at the seat immediately after it in seat order and wraps around, so the holder only wins a tie if no later seat also tied. |
| `current_hand_suit_ids` | `tuple[int, ...]` | The suit IDs in your hand. |

### The table

| Field | Type | Meaning |
| --- | --- | --- |
| `player_count` | `int` | Number of players. |
| `starting_cash` | `int` | Cash each player began with. |
| `cash_by_seat` | `tuple[int, ...]` | Current cash for each seat, indexed by seat. |
| `value_chart` | `tuple[int, ...]` | Score-by-count table (6 entries, indexed by count `0..5`): `value_chart[n]` is the points for holding `n` cards of a single suit. E.g. `(0, 4, 8, 12, 16, 20)`. May be a custom chart for this game, and cells may be negative. |
| `payment_rule` | `"first-price" \| "second-price"` | How the auction winner pays: their own bid (first-price) or the second-highest bid (second-price, Vickrey). Flips optimal bidding from shading to truthful — see the README's [Supported rules & compatibility](../README.md#supported-rules--compatibility). `cash_by_seat` already reflects it. |
| `objective_ids` | `tuple[int, ...]` | The objectives in play this game. |
| `current_action_id` | `int \| None` | The action being auctioned this turn (`None` outside a turn). |
| `current_resource_ids` | `tuple[int, int]` | Suit IDs of the resource(s) on offer this turn. |
| `won_resource_counts_by_seat` | `tuple[tuple[int, ...], ...]` | Per seat, count of each suit won so far. |
| `revealed_info_counts_by_seat` | `tuple[tuple[int, ...], ...]` | Per seat, count of each suit revealed so far. |
| `owned_objective_ids_by_seat` | `tuple[tuple[int, ...], ...]` | Per seat, the objective IDs that seat has completed. |
| `metadata` | `dict[str, Any]` | Extra server-provided data; empty by default. |

### Derived (computed) properties

Convenience views computed from the fields above — nothing extra is sent over
the wire:

| Property | Type | Meaning |
| --- | --- | --- |
| `remaining_deadline_ms` | `int` | Milliseconds left until `deadline_at`, measured from the current time (not `received_at`), clamped at `0`. Reflects the real budget after any time the request spent queued. |
| `won_resource_counts_by_suit` | `tuple[int, ...]` | Per-suit totals across all seats (column sums of `won_resource_counts_by_seat`). Index `i` is `Suit(i + 1)`. |
| `revealed_info_counts_by_suit` | `tuple[int, ...]` | Per-suit totals across all seats (column sums of `revealed_info_counts_by_seat`). Index `i` is `Suit(i + 1)`. |

---

## `RuntimeEvent`

Passed to `on_runtime_event`. Read-only.

| Field | Type | Meaning |
| --- | --- | --- |
| `kind` | `str` (see below) | What happened. |
| `details` | `dict[str, Any]` | Event-specific extra data; may be empty. |

`kind` is one of:

`connected`, `disconnected`, `connectionRejected`, `connectionError`,
`heartbeatReceived`, `heartbeatSent`, `requestQueued`, `requestDropped`,
`requestCompleted`, `requestFailed`, `malformedFrame`, `decisionRejected`.

### `decisionRejected` details

Emitted when a bot's decision fails legality checking. `applied` is the fate
the SDK's internal `classify()` sorted it into; the possible values are the
[`decisionFate`](#type-aliases) alias below.

| Field | Type | Meaning |
| --- | --- | --- |
| `request_id` | `str` | The request the decision answered. |
| `decision_kind` | `str` | The request's `decisionKind` (`submitBid` or `selectInfoToReveal`). |
| `action_kind` | `str` | The bot's decision's `action_kind`. |
| `value` | `int \| None` | The bot's original value, before any correction. |
| `detail` | `str` | Human-readable reason the decision was rejected. |
| `applied` | `str` (`decisionFate`) | `"discarded"`, `"corrected"`, or `"forwarded"`. |
| `corrected_value` | `int \| None` | Present only when `applied == "corrected"` — the wire-representable value actually sent. |
| `context` | `DecisionContext` | Present only when `debug` is on. |

---

## Reference (decoder ring)

Importable from `pocketrocks` (defined in `pocketrocks.reference`). Use these
instead of hardcoding the integers you get in `DecisionContext`. The full ID
tables live in [`MAPPINGS.md`](MAPPINGS.md).

### `Suit` — `IntEnum`

`BRICK = 1`, `WOOD = 2`, `ORE = 3`, `SHEEP = 4`, `WHEAT = 5`. Values equal the
suit ids in the context. `Suit(3).label == "Ore"`. Suit-indexed arrays are
`0`-based, so a suit's slot is `Suit.ORE - 1`.

### `ActionId` — `IntEnum`

`AUCTION1 = 1`, `AUCTION2 = 2`, `LOAN10 = 3`, `LOAN20 = 4`, `INVEST5 = 5`,
`INVEST10 = 6`. Values equal `DecisionContext.current_action_id`.

### `ObjectiveInfo` — dataclass

| Field | Type | Meaning |
| --- | --- | --- |
| `objective_id` | `int` | Wire id, `1..30` (matches `objective_ids`). |
| `slug` | `str` | Stable string id, e.g. `"prod-any-same2"`. |
| `description` | `str` | Plain-English summary, e.g. `"2x Brick"`. |
| `payout` | `int` | Fixed cash for completing it — known upfront, same every game. |
| `pattern` | `str \| None` | `"same2" \| "same3" \| "different3" \| "different4" \| "twoPairs4"` for flexible objectives; `None` otherwise. |
| `requirement` | `tuple[int, ...] \| None` | Per-suit counts (index `i` = `Suit(i + 1)`) for suit-specific objectives; `None` for pattern objectives. |

### Lookups

| Name | Description |
| --- | --- |
| `SUIT_LABELS: dict[int, str]` | `{1: "Brick", ...}` |
| `ACTION_DESCRIPTIONS: dict[int, str]` | Action id → what winning it does. |
| `OBJECTIVES: dict[int, ObjectiveInfo]` | All 30 objectives by id. |
| `describe_action(id) -> str` | Human description for an action id. |
| `describe_suit(id) -> str` | Human name for a suit id. |
| `describe_objective(id) -> str` | Human description for an objective id. |
| `objective_payout(id) -> int \| None` | Fixed payout for an objective id (`None` if unknown). |

The `describe_*` helpers return an `"Unknown ... id N"` string for unrecognized
ids rather than raising.

---

## `Ruleset` (`pocketrocks.sim`)

The game-defining settings a simulated game is played under — the same four
facts the live server's ruleset carries, in snake_case. Frozen dataclass;
validated on construction. Accepted by `LocalGame`, `run_games`, `SimEngine`
and `BatchSimEngine.start` as `ruleset=` (or one per row as `rulesets=`).

```python
from pocketrocks.sim import Ruleset, PaymentRule, resolve_chart, compute_paid
```

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `player_count` | `int` | — | `3`-`5`. |
| `value_chart` | `str \| tuple[int, ...]` | `"A"` | A fixed chart key `"A"`-`"E"` (case-insensitive; stored upper-case) or an inline **custom value chart** of exactly 6 integers, validated against the constraint envelope below. |
| `payment_rule` | `PaymentRule` | `"first-price"` | What the auction winner pays: `"first-price"` their own bid, `"second-price"` the runner-up bid (a lone positive bid pays 0). The highest bidder wins under either rule. |
| `objectives_enabled` | `bool` | `True` | Whether the four objective cards are in play. |

Derived:

| Property | Type | Meaning |
| --- | --- | --- |
| `chart` | `tuple[int, ...]` | The resolved 6 cells. This is what `DecisionContext.value_chart` carries — bots never see the key. |
| `chart_label` | `str` | `"A"`-`"E"` for a fixed chart, `custom(c0,c1,...)` for an inline one; for naming runs. |

### Constraint envelope

Inline charts must satisfy the envelope the server generates custom charts
under, or `Ruleset(...)` / `resolve_chart(...)` raise `ValueError` naming the
violated constraint:

| Constant | Value | Rule |
| --- | --- | --- |
| `CHART_CELL_CAP` | `20` | Every cell within `[-20, 20]`. |
| `MAX_TURNS` | `1` | At most one direction reversal across the six cells. |
| `SUM_FLOOR` | `38` | Monotone and hump charts total at least 38 (fixed chart `E` sums to exactly 38). |
| `VALLEY_SUM_FLOOR` | `75` | A valley (fall then rise) totals at least 75... |
| `VALLEY_MIN_CELL` | `2` | ...and has no cell below 2. |

The constants are importable from `pocketrocks.sim.ruleset`. The shared
accept/reject table both the server and this SDK assert against is
`tests/fixtures/chart_envelope.json`.

### Functions

| Name | Description |
| --- | --- |
| `resolve_chart(selection) -> tuple[int, ...]` | Key or inline cells → the 6 cells. The one place chart selections are validated. |
| `compute_paid(rule, bids) -> int` | The auction price for a set of effective bids under a payment rule. Winner selection is not its job. |

`PaymentRule` is the same `Literal["first-price", "second-price"]` alias
`DecisionContext.payment_rule` carries (defined in `pocketrocks.types`, re-exported
from `pocketrocks.sim`); see [Type aliases](#type-aliases).

---

## Type aliases

Exposed on the dataclasses for reference / type-checking:

```python
PaymentRule = Literal["first-price", "second-price"]
decisionKind = Literal["submitBid", "selectInfoToReveal"]
decisionActionKind = Literal["pass", "submitBid", "selectInfoToReveal"]
decisionFate = Literal["ok", "discarded", "corrected", "forwarded"]
runtimeEventKind = Literal[
    "connected",
    "disconnected",
    "connectionRejected",
    "connectionError",
    "heartbeatReceived",
    "heartbeatSent",
    "requestQueued",
    "requestDropped",
    "requestCompleted",
    "requestFailed",
    "malformedFrame",
    "decisionRejected",
]
```

The package ships a `py.typed` marker, so these types flow into your editor and
`mypy` automatically once the SDK is installed.
