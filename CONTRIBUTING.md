# Contributing

This repo is the **SDK's source code**. If you want to *write a bot*, you don't
belong here — create your own project and install the SDK into it, following the
root [README](README.md). Read [`docs/README.md`](docs/README.md) before changing
behavior.

## Setup

```bash
uv sync --all-extras
uv run pre-commit install
```

`--all-extras` matters: the `dev` extra is where `pytest`, `mypy`, `ruff`, and
`pre-commit` itself live, and `uv sync` alone won't install it. `uv` is the
single entry point beyond this: every command below is `uv run <something>`,
which uses the locked environment from `uv.lock` rather than whatever happens
to be on your `PATH`.

If you don't have `uv`: https://docs.astral.sh/uv/getting-started/installation/

### Using `git worktree`?

`pre-commit install` writes its hooks into `.git/hooks` — and with worktrees,
that directory is **shared** across every worktree and the main checkout, not
per-worktree. Installing hooks from one worktree activates them everywhere,
including on branches that have no `.pre-commit-config.yaml`, where every
commit then fails with "No `.pre-commit-config.yaml` file was found." If that
happens, run `uv run pre-commit uninstall` from the worktree that installed
them, or switch back to a branch that has the config.

## The gate

`pre-commit` runs on every commit, staged-scoped and fast:

| Hook | Does |
|---|---|
| `ruff-format` | Formats |
| `ruff --fix` | Lints and autofixes |
| `gitleaks` | Blocks committed secrets |
| `conventional-pre-commit` | Validates the commit message |
| hygiene hooks | Whitespace, EOF, YAML/TOML validity, merge markers, large-file guard, `develop` protection |

There is deliberately **no pre-push hook**. The heavy checks (full test matrix,
type checking, docs policy) run in CI, which has no minute budget to protect.

**Hooks are a convenience, not the enforcer.** CI runs
`uv run pre-commit run --all-files`, so if you never install the hooks, nothing
you push gets a free pass on formatting, lint, or hygiene — you just find out
later. The one exception is `gitleaks`: it's staged-scoped by design (see
below), so CI's `pre-commit` pass can't re-check it — a separate `secret-scan`
CI job does that instead. Run the gate by hand any time:

```bash
uv run pre-commit run --all-files
```

## Before you push

```bash
uv run pre-commit run --all-files   # format, lint, secrets, hygiene
uv run mypy src tests               # strict type checking
uv run pytest                       # test suite
```

`gitleaks` needs no local install: `pre-commit` builds it itself the first
time it runs, from its own bundled Go toolchain, independent of whatever `go`
or `gitleaks` you do or don't have on `PATH`. The local hook only scans
*staged* content, though, so it can't be the thing CI relies on — a clean CI
checkout has nothing staged. A separate `secret-scan` job in `ci.yml` scans
the actual committed git history on every push, pinned to the same gitleaks
version as this file's hook `rev`, so `git commit --no-verify` still can't
land a secret undetected.

## Commits and PR titles

This repo uses [Conventional Commits](https://www.conventionalcommits.org/).
Because PRs are **squash-merged**, the **PR title** is what lands on `develop` —
a CI check blocks non-conforming titles.

Commit messages themselves are validated only by the local
`conventional-pre-commit` hook, not by CI — `pre-commit run --all-files` runs
`pre-commit`-stage hooks only, and that hook runs at `commit-msg` stage. This
is fine in practice: squash-merge means the PR title is what actually lands
on `develop`, and the PR title *is* the one CI enforces.

Allowed types: `feat`, `fix`, `chore`, `docs`, `refactor`, `perf`, `test`,
`build`, `ci`, `revert`, `style`. Scope optional.

```
feat(sim): add deterministic replay seeds
fix: guard against a missing legal_max_amount
docs(readme): document POCKETROCKS_SKIP_VERSION_CHECK
```

### Branch protection

CI enforces nothing unless branch protection on `develop` actually requires
it. Two separate checks must both be marked required, because they come from
two separate workflows and neither can see the other:

- `CI OK`
- `PR title is a Conventional Commit`

Without both set, every gate described in this document is advisory only.

## Branches

Branch off `develop`; open a PR into `develop`.

**Merging to `develop` publishes.** Users install with `pip install
git+https://github.com/jaiparera/pocketrocks-python-sdk.git`, which resolves to
the tip of `develop`. There is no staging branch between your merge and them.

## Versioning

`src/pocketrocks/_version.py` holds two numbers:

- `__version__` — bump on any change to `src/pocketrocks/**`. The SDK's staleness
  warning compares against this, so an unbumped version means existing installs
  are never told to upgrade.
- `RULES_VERSION` — bump whenever canonical game rules change and the golden-trace
  fixtures are regenerated. A mismatch tells users their local simulation results
  may diverge from the live server.

## Releasing a rules change

The golden traces under `tests/fixtures/botsdk/` pin this engine to games the
real TS engine played, gated on `RULES_VERSION`. When the canonical game rules
change, the release routine is:

1. **Bump both version numbers together.** `rulesVersion` in the main repo's
   `apps/server/scripts/export-bot-sdk-fixtures.ts` and `RULES_VERSION` in
   `src/pocketrocks/_version.py` here. They are the same integer; a mismatch is
   the conformance suite's first failure.
2. **Regenerate the fixtures in the main repo:**
   `yarn workspace @pocketrocks/server fixtures:bot-sdk <outDir>`. Traces are
   only ever produced by the TS engine — never by this SDK, and never by hand.
3. **Copy the output over `tests/fixtures/botsdk/`** here, then port the rules
   change into `src/pocketrocks/sim/` (the batch kernel in `batch_engine.py`;
   `constants.py` if a table changed; `ruleset.py` if the ruleset gained a
   field or the constraint envelope moved).
4. **Run the conformance suite:** `uv run pytest tests/sim/test_conformance.py`.
   It gates on version agreement and replays every trace end to end. A failure
   is a rules divergence: fix the engine, never the fixture.
5. **Bump `__version__`** and merge to `develop` — the branch installs and the
   staleness check both target it, so the merge is the release.

Traces carry the rules version they were recorded at, and each slice of the
ruleset space has a minimum version (the table at the top of
`tests/sim/test_conformance.py`). A trace stays a valid oracle from that
version onward: rules version 2 added the payment rule and inline charts
without changing how a first-price fixed-chart game plays, so the version-1
first-price A-E traces still pin that slice. If a change alters first-price
fixed-chart play, raise that slice's minimum to the new version too — every
existing trace then fails until step 2 regenerates it, which is the point.
Second-price and custom-chart slices need traces the exporter recorded with
those fields (version 2 or later).

## Where things go

Read the docs policy in [`docs/README.md`](docs/README.md) before adding any
document. Short version: status, roadmap and debt live in **GitHub issues**,
never in a committed file; design specs and implementation plans stay
**untracked**. CI enforces this.

## Dependencies

Add dependencies to `pyproject.toml`, then:

```bash
uv lock
```

Commit the updated `uv.lock`. Declare the **lowest version you actually support**
— the `floors` CI job resolves runtime dependencies to your declared minimums
and runs `pytest` against them, so an optimistic floor on a runtime dependency,
`pytest`, or `pytest-asyncio` fails the build. `ruff`, `mypy`, and `pre-commit`
are installed at their floors too but never invoked in that job, so an
optimistic floor on those three would not be caught here.

## Review

[`REVIEW.md`](REVIEW.md) is a living checklist of pitfalls we recurrently miss.
Skim it before opening a PR. Found a new one mid-review? File it to the review
inbox issue rather than editing `REVIEW.md` from an unrelated branch.
