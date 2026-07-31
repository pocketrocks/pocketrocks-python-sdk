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

These names are the entire public API — see the [Reference](#reference-decoder-ring)
section below, and [`MAPPINGS.md`](MAPPINGS.md) for the full ID tables.
Everything under `pocketrocks.internal` is an implementation detail and may
change without notice — don't import from it.

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
    protocol_version: int | None = None,         # default 2
    max_in_flight_decisions: int | None = None,  # default 4
    max_queue_size: int | None = None,           # default 32
    min_remaining_deadline_ms_to_start: int | None = None,  # default 100
    request_timeout_slack_ms: int | None = None, # default 25
    reconnect: bool | None = None,               # default True
    reconnect_base_delay_seconds: float | None = None,          # default 0.5
    reconnect_max_delay_seconds: float | None = None,           # default 8.0
    rejected_reconnect_max_delay_seconds: float | None = None,  # default 60.0
)
```

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
| `value_chart` | `tuple[int, ...]` | Score-by-count table (6 entries, indexed by count `0..5`): `value_chart[n]` is the points for holding `n` cards of a single suit. E.g. `(0, 4, 8, 12, 16, 20)`. |
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
`requestCompleted`, `requestFailed`, `malformedFrame`.

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

## Type aliases

Exposed on the dataclasses for reference / type-checking:

```python
decisionKind = Literal["submitBid", "selectInfoToReveal"]
decisionActionKind = Literal["pass", "submitBid", "selectInfoToReveal"]
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
]
```

The package ships a `py.typed` marker, so these types flow into your editor and
`mypy` automatically once the SDK is installed.
