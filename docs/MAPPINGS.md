# ID mappings

`DecisionContext` gives you bare integers — action ids, suit ids, and objective
ids. This is the decoder ring. Everything here is also available in code from
`pocketrocks` (see the [Reference section of `TYPES.md`](TYPES.md#reference-decoder-ring)),
so prefer `ActionId.LOAN10` over the literal `3`.

> These tables are sourced from the vendored wire-protocol package, so they
> track the protocol version the SDK ships.

---

## Suits

Suit ids are `1..5`. Suit-**indexed** arrays (`won_resource_counts_by_seat`,
`revealed_info_counts_by_seat`, objective `requirement`, and the derived
`*_by_suit` properties) are `0`-based, so suit `n` lives at index `n - 1`.

| Suit id | Name | `Suit` |
| --- | --- | --- |
| 1 | Brick | `Suit.BRICK` |
| 2 | Wood | `Suit.WOOD` |
| 3 | Ore | `Suit.ORE` |
| 4 | Sheep | `Suit.SHEEP` |
| 5 | Wheat | `Suit.WHEAT` |

Fields that carry suit ids: `current_resource_ids`, `current_hand_suit_ids`.

---

## Actions

Action ids are `1..6` and appear as `DecisionContext.current_action_id` (which
is `None` when no turn is open).

| Action id | `ActionId` | What winning it does |
| --- | --- | --- |
| 1 | `AUCTION1` | Auction for 1 resource card. The winner pays the auction price and gains the offered resource. |
| 2 | `AUCTION2` | Auction for 2 resource cards. The winner pays the auction price and gains both offered resources. |
| 3 | `LOAN10` | The winner pays the auction price now, immediately gains $10 cash, and repays $10 during scoring. |
| 4 | `LOAN20` | The winner pays the auction price now, immediately gains $20 cash, and repays $20 during scoring. |
| 5 | `INVEST5` | The winner locks the auction price and gets it back plus $5 during scoring. |
| 6 | `INVEST10` | The winner locks the auction price and gets it back plus $10 during scoring. |

Loans raise your legal bid ceiling for that turn — `legal_max_amount` already
accounts for this, so you don't have to.

---

## Objectives

Objective ids are `1..30` and appear in `objective_ids` (the objectives in play
this game) and `owned_objective_ids_by_seat` (which seat has completed each).

- **Pattern** objectives (1-5) are flexible: any suits that fit the shape.
- **Suit-specific** objectives (6-30) require exact per-suit counts. The
  `Requirement` column lists counts by suit index `[Brick, Wood, Ore, Sheep, Wheat]`.

Payouts are fixed and known upfront (identical in every game). In code:
`OBJECTIVES[id]` returns an `ObjectiveInfo` (with `.payout`), `objective_payout(id)`
gets just the value, and `describe_objective(id)` just the text.

| Id | Slug | Description | Payout | Pattern | Requirement `[Br, Wd, Or, Sh, Wh]` |
| --- | --- | --- | --- | --- | --- |
| 1 | `prod-any-same2` | Any two cards of a single suit | 5 | same2 |  |
| 2 | `prod-any-same3` | Any three cards of a single suit | 10 | same3 |  |
| 3 | `prod-any-different3` | One card each of any three different suits | 5 | different3 |  |
| 4 | `prod-any-different4` | One card each of any four different suits | 10 | different4 |  |
| 5 | `prod-any-two-pairs4` | Two cards each of any two suits | 15 | twoPairs4 |  |
| 6 | `prod-spec-same2-s1` | 2x Brick | 5 |  | [2, 0, 0, 0, 0] |
| 7 | `prod-spec-same2-s2` | 2x Wood | 5 |  | [0, 2, 0, 0, 0] |
| 8 | `prod-spec-same2-s3` | 2x Ore | 5 |  | [0, 0, 2, 0, 0] |
| 9 | `prod-spec-same2-s4` | 2x Sheep | 5 |  | [0, 0, 0, 2, 0] |
| 10 | `prod-spec-same2-s5` | 2x Wheat | 5 |  | [0, 0, 0, 0, 2] |
| 11 | `prod-spec-diff2-12` | 1x Brick + 1x Wood | 5 |  | [1, 1, 0, 0, 0] |
| 12 | `prod-spec-diff2-13` | 1x Brick + 1x Ore | 5 |  | [1, 0, 1, 0, 0] |
| 13 | `prod-spec-diff2-14` | 1x Brick + 1x Sheep | 5 |  | [1, 0, 0, 1, 0] |
| 14 | `prod-spec-diff2-15` | 1x Brick + 1x Wheat | 5 |  | [1, 0, 0, 0, 1] |
| 15 | `prod-spec-diff2-23` | 1x Wood + 1x Ore | 5 |  | [0, 1, 1, 0, 0] |
| 16 | `prod-spec-diff2-24` | 1x Wood + 1x Sheep | 5 |  | [0, 1, 0, 1, 0] |
| 17 | `prod-spec-diff2-25` | 1x Wood + 1x Wheat | 5 |  | [0, 1, 0, 0, 1] |
| 18 | `prod-spec-diff2-34` | 1x Ore + 1x Sheep | 5 |  | [0, 0, 1, 1, 0] |
| 19 | `prod-spec-diff2-35` | 1x Ore + 1x Wheat | 5 |  | [0, 0, 1, 0, 1] |
| 20 | `prod-spec-diff2-45` | 1x Sheep + 1x Wheat | 5 |  | [0, 0, 0, 1, 1] |
| 21 | `prod-spec-diff3-123` | 1x Brick + 1x Wood + 1x Ore | 10 |  | [1, 1, 1, 0, 0] |
| 22 | `prod-spec-diff3-124` | 1x Brick + 1x Wood + 1x Sheep | 10 |  | [1, 1, 0, 1, 0] |
| 23 | `prod-spec-diff3-125` | 1x Brick + 1x Wood + 1x Wheat | 10 |  | [1, 1, 0, 0, 1] |
| 24 | `prod-spec-diff3-134` | 1x Brick + 1x Ore + 1x Sheep | 10 |  | [1, 0, 1, 1, 0] |
| 25 | `prod-spec-diff3-135` | 1x Brick + 1x Ore + 1x Wheat | 10 |  | [1, 0, 1, 0, 1] |
| 26 | `prod-spec-diff3-145` | 1x Brick + 1x Sheep + 1x Wheat | 10 |  | [1, 0, 0, 1, 1] |
| 27 | `prod-spec-diff3-234` | 1x Wood + 1x Ore + 1x Sheep | 10 |  | [0, 1, 1, 1, 0] |
| 28 | `prod-spec-diff3-235` | 1x Wood + 1x Ore + 1x Wheat | 10 |  | [0, 1, 1, 0, 1] |
| 29 | `prod-spec-diff3-245` | 1x Wood + 1x Sheep + 1x Wheat | 10 |  | [0, 1, 0, 1, 1] |
| 30 | `prod-spec-diff3-345` | 1x Ore + 1x Sheep + 1x Wheat | 10 |  | [0, 0, 1, 1, 1] |

---

## Value chart

`DecisionContext.value_chart` is **not** indexed by suit. It's a 6-element table
indexed by **count** (`0..5`): `value_chart[n]` is the points you score for
holding `n` cards of a single suit. Example: `(0, 4, 8, 12, 16, 20)` means a
suit you hold 3 of is worth 12. The chart is the same for every suit in a game,
but which chart is in play varies per game.
