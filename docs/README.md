# PocketRocks Python SDK — Documentation Hub

This is the single front door for contributor documentation. Root `CLAUDE.md` and
`AGENTS.md` point here. Bot authors want the root [README](../README.md) instead.

## Docs Policy

One fact, one home:

| Knowledge | Single home |
|---|---|
| Bot-author quickstart, API surface, env vars | root `README.md` |
| Type reference | `docs/TYPES.md` |
| Protocol / action-id mappings | `docs/MAPPINGS.md` |
| How to contribute: setup, gate, conventions | `CONTRIBUTING.md` |
| Navigation, policy, invariants, agent rules | this file |
| Why a cross-cutting decision was made | `docs/adr/*.md` |
| How a subsystem works | thin `README.md` next to the code |
| Domain vocabulary (glossary only) | root `CONTEXT.md` |
| Recurring review pitfalls | root `REVIEW.md` |
| Status, roadmap, debt, current intent | GitHub issues — never a committed doc |
| Design specs, implementation plans, handoffs | untracked (scratchpad / gitignored) |

A CI guard (`scripts/check-docs-policy.sh`) enforces this. It rejects
`*HANDOFF*.md` and `TECH_DEBT`/`ROADMAP`/`STATUS`-style documents anywhere in the
tree, and inside `docs/` allows only the canonical files above plus the flat
`adr/` subdirectory.

Why status docs are banned: a committed roadmap is stale the day after it merges
and there is no reviewer whose job is to notice. An issue has an assignee, a
state, and a close event.

## Read order

Before changing behavior:

1. This file.
2. [`../README.md`](../README.md) — what bot authors are promised.
3. [`TYPES.md`](TYPES.md) — the public type surface.
4. [`MAPPINGS.md`](MAPPINGS.md) — action ids, suits, objectives, payouts.
5. [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — the gate your change must pass.

Then open the source files you plan to modify.

## Source-of-truth map

| Concern | Code |
|---|---|
| Public exports | `src/pocketrocks/__init__.py` |
| Bot base class | `src/pocketrocks/bot.py` |
| Live runtime / game loop | `src/pocketrocks/runtime.py` |
| Wire protocol framing | `src/pocketrocks/protocol.py` |
| Transport | `src/pocketrocks/transport.py` |
| Reconnect policy | `src/pocketrocks/reconnect.py` |
| Configuration and env vars | `src/pocketrocks/config.py` |
| Public reference data | `src/pocketrocks/reference.py` |
| SDK + rules version | `src/pocketrocks/_version.py` |
| Staleness advisory | `src/pocketrocks/_update_check.py` |
| Local simulation | `src/pocketrocks/sim/` |
| Test kit for bot authors | `src/pocketrocks/testing/` |

## High-risk invariants

- `_version.py` is the single source of truth for `__version__` and
  `RULES_VERSION`. The staleness check fetches it from `develop`, so an
  unbumped version means every existing install is silently stale.
- `RULES_VERSION` increments whenever canonical game rules change, because a
  rules mismatch makes local simulation results diverge from the live server.
- The update check is advisory only: it never blocks, never raises, runs at most
  once per process, and is fully disabled by `POCKETROCKS_SKIP_VERSION_CHECK`.
- The bot-wire protocol version must match the server's; a mismatch is rejected
  at connect time.
- `develop` is the distribution branch. Its tip is what `pip install
  git+https://...` gives a user.

## Branch and release model

There is no package index release. The repo *is* the distribution channel:
users install with `pip install git+https://github.com/jaiparera/pocketrocks-python-sdk.git`,
which resolves to the tip of `develop`. Consequently:

- Branch off `develop`, open PRs into `develop`.
- Merging to `develop` publishes. Treat it that way.
- PRs are squash-merged, so the **PR title** is the commit message that lands.

## Engineering practices

### Undirected work selection

When asked to pick something up with **no specific issue named**, choose from
GitHub issues by this rule (a named issue always overrides it).

**Eligible** = an open issue that is all of:

- **Unassigned** — an assignee means someone has already claimed it.
- **Unblocked** — no open blocker.
- **Priority-labeled** — carries one of `priority:p0`–`priority:p3`.

**Order:** highest priority first (`p0` → `p3`); ties broken by lowest issue
number.

**Claim before starting:** `gh issue edit <n> --add-assignee @me` as the first
action, so concurrent agents don't collide.

Priority ladder: `p0` drop-everything · `p1` important, next · `p2` normal ·
`p3` someday.

### Verification matrix

`uv run pre-commit run --all-files` is not optional for any change class — it is
cheap, and it is the only local enforcement of formatting, secret scanning and
several lint rules.

| Change class | Run |
|---|---|
| Runtime / protocol / transport | `uv run pytest`, `uv run mypy src tests`, `uv run pre-commit run --all-files` |
| Simulation or rules | `uv run pytest tests/sim`, then the full `uv run pytest` (golden traces), plus a `RULES_VERSION` bump |
| Docs only | `uv run pre-commit run --all-files`, `sh scripts/check-docs-policy.sh` |
| Examples / starter | execute the changed script end to end, then `uv run pre-commit run --all-files` |

Note the inverse of the `per-file-ignores` in `pyproject.toml`: `S101` is off
under `tests/`, `examples/`, `starter/` and `benchmarks/`, so a green lint run is
not evidence for that rule there. Check it by eye in those trees.
