# Vendored fixtures from the main repo

Every file listed here is produced by `jaiparera/pocketrocks` and copied in
verbatim (the only permitted difference is the trailing newline this repo's
`end-of-file-fixer` hook appends; `JSON.stringify` writes none). Never edit
one by hand: a fixture that disagrees with this engine is a rules divergence,
and the fix goes in `src/pocketrocks/sim/`, never in the fixture
(CONTRIBUTING.md, "Releasing a rules change").

## Provenance

| File | Source in `jaiparera/pocketrocks` | Commit |
|---|---|---|
| `traces/trace-000..060.json` | `yarn workspace @pocketrocks/server fixtures:bot-sdk <outDir>` (`apps/server/scripts/export-bot-sdk-fixtures.ts`) | `8fb0f33501215f2d5bab4cd424e47b2e8de1f5ab` (`origin/develop` after #688) |
| `shuffles.json` | same exporter | `8fb0f33501215f2d5bab4cd424e47b2e8de1f5ab` (byte-identical to the previous copy) |
| `../chart_envelope.json` | `packages/shared/testFixtures/chartEnvelope.json` (#683) | `8fb0f33501215f2d5bab4cd424e47b2e8de1f5ab` |

When you re-vendor, replace the commit column with the SHA you exported from.

## Trace corpus (`rulesVersion` 2)

61 traces. Each carries `paymentRule`, `objectivesEnabled`, the full `ruleset`,
and an `endgameReveals` section; `valueChartKey` is `A`-`E` or `custom`
(inline cells in `valueChart`). Objectives are off on every fourth trace
(`index % 4 == 3`) so the disabled path spans every chart and player count.

| Traces | Payment rule | Charts | Player counts |
|---|---|---|---|
| `000`-`029` | first-price | fixed A-E, each twice | 3, 4, 5 (cycling) |
| `030`-`044` | second-price | fixed A-E, once per player count | 3, 4, 5 |
| `045`-`060` | alternating first/second | 8 seeded custom charts, each under both rules; 6 of the 8 have a negative cell | 3, 4, 5 (cycling) |

`tests/sim/test_conformance.py` replays every trace end to end and asserts the
corpus still covers every (payment rule x fixed chart x player count) cell plus
negative-cell custom charts under both rules, so a reduced re-export fails
loudly instead of silently unpinning a slice.
