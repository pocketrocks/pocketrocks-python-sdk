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
you push gets a free pass — you just find out later. Run the gate by hand any
time:

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
or `gitleaks` you do or don't have on `PATH`. CI runs the identical check on
every push, so there's no path where it quietly gets skipped.

## Commits and PR titles

This repo uses [Conventional Commits](https://www.conventionalcommits.org/).
Because PRs are **squash-merged**, the **PR title** is what lands on `develop` —
a CI check blocks non-conforming titles.

Allowed types: `feat`, `fix`, `chore`, `docs`, `refactor`, `perf`, `test`,
`build`, `ci`, `revert`, `style`. Scope optional.

```
feat(sim): add deterministic replay seeds
fix: guard against a missing legal_max_amount
docs(readme): document POCKETROCKS_SKIP_VERSION_CHECK
```

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
— the `floors` CI job resolves to your declared minimums and runs the suite
against them, so an optimistic floor fails the build.

## Review

[`REVIEW.md`](REVIEW.md) is a living checklist of pitfalls we recurrently miss.
Skim it before opening a PR. Found a new one mid-review? File it to the review
inbox issue rather than editing `REVIEW.md` from an unrelated branch.
