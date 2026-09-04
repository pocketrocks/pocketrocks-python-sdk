# pocketrocks-python-sdk

Domain vocabulary for the PocketRocks bidding game as the Python SDK exposes it
to bot authors. Glossary only: what a word means and which words to avoid. How
a thing is implemented lives next to the code; why a decision was made lives in
`docs/adr/`.

## Language

### Value charts

**Value chart**:
The 6-cell integer table mapping how many cards of a suit a player holds
(index 0–5) to that suit's payout at game end. Bots receive it as raw numbers,
never as an identifying key, so a chart they have never seen needs no bot
change.
_Avoid_: scoring table, payoff curve.

**Fixed charts (A–E)**:
The five built-in value charts. A/B are linear (ascending/descending), C/D are
curved, E is a non-monotonic hump. Selected by key.

**Custom value chart**:
A value chart generated under the constraint envelope rather than picked from
A–E. It is resolved once at game start and frozen for the whole game; cells
may be negative. "Random" is the mechanism that produces it; "custom" is the
term.
_Avoid_: random chart, generated chart (as a term — fine as a description of
the mechanism).

**Constraint envelope**:
The bounds every custom value chart must satisfy: each cell within ±20, at most
one turning point, and cell sum at least 38 (so fixed chart E, sum 38, is the
minimum any chart can total). Valleys (fall then rise) additionally need a sum
of at least 75 and a minimum cell of 2. Both the server and the SDK validate
against the same envelope.
_Avoid_: chart rules, chart constraints (too easily confused with the game
rules).

### Auctions

**Payment rule**:
How much the auction winner pays given the sorted bids. `first-price`: the
winner pays their own bid. `second-price` (Vickrey): the winner pays the
second-highest bid. Distinct from the winner rule — the highest bidder always
wins under either. The rule flips optimal bidding: first-price rewards shading
below your value, second-price makes truthful bidding dominant.
_Avoid_: second-highest-bid-wins (wrong — that would change the winner, not
the price), highest-bid-wins (names the winner rule, not the price).

### Rules

**Ruleset**:
The game-defining settings a bot must know to play correctly: player count,
value chart selection (a fixed key or an inline custom chart), payment rule,
and whether objectives are enabled. Everything a bot's model of the game
depends on and nothing else; lobby ergonomics such as move timers are not part
of it.
_Avoid_: game settings, room settings, variant (a variant is one value of a
ruleset field, not the ruleset).

**Rules version**:
`RULES_VERSION`, an integer that increments whenever the canonical game rules
change. A mismatch between the SDK's value and the server's means local
simulation results may diverge from live play.
_Avoid_: SDK version (that is `__version__`, bumped on any SDK code change,
rules or not).
