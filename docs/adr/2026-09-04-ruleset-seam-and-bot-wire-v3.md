# Ruleset is a first-class seam, and bot-wire v3 replaces v2 outright

Context: the server ships two ruleset variants dev-gated — the second-price
payment rule and custom value charts (see `CONTEXT.md` → "Payment rule",
"Custom value chart"). The SDK cannot express either. The sim engine hardcodes
first-price in `src/pocketrocks/sim/batch_engine.py` (`resolve_bids`, the
`paid[active] = highest[active]` line) and again in
`src/pocketrocks/internal/bot_wire_v2/reconstruction.py` (`cash[winner] -=
event.bids_by_seat[winner]`); charts are a closed A–E dict in
`sim/constants.py` that every entry point validates keys against; the public
`DecisionContext` carries a bare 6-tuple and no rule; and the wire version is
two unlinked knobs (`config.protocol_version`, default 2, and the codec's
`bot_wire_protocol_version` constant), so setting the env var to 3 negotiates
v3 and then fails every decode. Five decisions from the 2026-09-04 grilling
session are recorded here because each had a genuine alternative and the last
two are hard to reverse once bot authors depend on them.

## 1. One `Ruleset` dataclass is the single seam

A `Ruleset` dataclass mirroring the TS field names in snake_case —
`player_count`, `value_chart` (key or inline 6-tuple), `payment_rule`
(default `first-price`), `objectives_enabled` — is the one object read by the
batch engine, the scalar engine, replay reconstruction, the bot context
builder and tournament slicing. Alternative: keep threading loose keyword
arguments (`value_chart=`, plus a new `payment_rule=`) through each entry
point. Rejected: four entry points already disagree on what they accept
(`BatchSimEngine.start` takes a sequence of keys, `SimEngine`/`LocalGame`/
`run_games` a single key), and every new rule field would multiply that
drift. The dataclass matches where the server keeps the same facts.

## 2. The payment rule is priced through one function used by both settle paths

Both `resolve_bids()` in the batch engine and the replay reconstruction settle
through one pricing function keyed on `payment_rule`. Second-price pays the
runner-up maximum over the effective (clamped) bids; winner selection and
tiebreak are unchanged; a single positive bid pays 0. Alternative: implement
the rule twice, matching the existing duplication. Rejected: the two paths
are already a copy of each other and the sim/live parity tests exist
precisely because that copy drifts.

## 3. Charts are data behind one `resolve_chart()`

`value_chart` accepts a fixed key or an inline 6-tuple, and one
`resolve_chart()` turns either into cells and validates inline cells against
the constraint envelope. Downstream code (scoring, context, traces) sees only
cells — it already does; bots have never received the key. Alternative: add
the custom sentinel as a sixth entry in the A–E dict and generate on the fly.
Rejected: a chart is resolved once at game start and frozen, so the engine
must be handed cells, not a generator; and negative cells force an explicit
bounds check on the `int16` totals that a dict entry would not surface.

## 4. Bot-wire v3 replaces v2 outright

The vendored `internal/bot_wire_v2` package is replaced by the v3 package
generated in the main repo (`paymentRule` on `gameSetup`, signed zigzag chart
cells, presence slots). The two version knobs become one. `payment_rule` and
the chart kind/key are added to the public `DecisionContext` and to the
generated `ReconstructedDecisionContext` together, because
`protocol.build_decision_context` copies fields by name and raises on a
mismatch. Alternative: dual-version dispatch — carry both codecs and
negotiate per connection. Rejected: the server serves exactly one protocol
version at a time, the install channel is the tip of `develop` (there is no
old release to keep alive), and exactly one external bot exists, whose owner
is notified. Dual dispatch would double the codec surface to support a
population of zero.

## 5. Parity pins the chart validator, not the RNG stream

Cross-language parity with the TS server is asserted through one shared JSON
fixture of accept/reject charts plus the envelope constants, consumed by both
the TS specs and the Python tests. Each side generates its own charts.
Alternative: port the server's PRNG so both sides produce identical charts
from a seed. Rejected: the server persists the resolved cells of every game,
so a replay never needs to regenerate; an RNG port buys nothing and pins the
SDK to an implementation detail the server is free to change.

## Consequences

- `RULES_VERSION` bumps. All 30 golden traces regenerate, and new
  second-price and custom-chart (including negative-cell) traces are added.
  This depends on the release workflow in #7 landing first.
- `sample_bots.py` becomes rule-conditional (shade under first-price, bid
  truthfully under second-price).
- The README gains a "Supported rules & compatibility" section stating the
  shading-vs-truthful consequence and that the server serves exactly one
  protocol version.
- The v3 cutover is coordinated with the server's `botWireV3` flag flip
  (jaiparera/pocketrocks#405); until then the SDK on `develop` and the live
  server must agree on which version is live.
