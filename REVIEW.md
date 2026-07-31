# Review Checklist

A living list of pitfalls we recurrently miss. Skim before opening a PR; skim
before approving one. It lives at the repo root by design — it is a pre-push
tool, not reference documentation.

**Adding to it:** a pitfall caught mid-review gets filed to the review-inbox
issue, *not* edited in from an unrelated branch. Entries are batched in once
enough accumulate. An entry earns its place by having been missed at least
twice.

<!-- The review-inbox issue does not exist yet — it is created via `gh issue
     create` (see the task brief), an outward-facing action outside this
     commit's scope. Link it here once it exists. -->

## Async

- [ ] No blocking call inside an `async def` — `time.sleep`, `requests`, sync
      file I/O, `urllib`. This SDK's users copy our examples into their own
      event loops.
- [ ] Every coroutine is awaited. An unawaited coroutine fails silently with a
      `RuntimeWarning` most users have suppressed.
- [ ] Tasks created with `asyncio.create_task` are retained and cancelled on
      shutdown, not garbage-collected mid-flight.
- [ ] Anything network-facing has a timeout.

## Python correctness

- [ ] No mutable default argument (`def f(x=[])`).
- [ ] No bare `except:` or unexplained `except Exception:` — if it is genuinely
      catch-all, say why in a comment, as `_update_check.py` does.
- [ ] Every `# noqa` carries a rule code *and* a reason. `RUF100` catches
      codeless ones; only review catches reasonless ones.
- [ ] Every `# type: ignore` carries a reason.

## SDK contract

- [ ] Changed anything under `src/pocketrocks/**`? `__version__` is bumped.
      Users are told to upgrade by comparing against this and nothing else.
- [ ] Changed rules behavior or golden traces? `RULES_VERSION` is bumped too.
- [ ] Changed a public export, type, or env var? The root `README.md`,
      `docs/TYPES.md` and `docs/MAPPINGS.md` agree with the code.
- [ ] New env var? It appears in `.env.example`, `config.py`, and the README
      table — all three.
- [ ] Error messages name the fix, not just the fault. Bot authors are often
      new to Python.

## Repo hygiene

- [ ] The PR title is a Conventional Commit — it is the message that lands.
- [ ] No status/roadmap/debt document added. That is a GitHub issue.
- [ ] `uv.lock` is committed alongside any `pyproject.toml` dependency change.
- [ ] A new dependency's declared floor is the lowest version actually tested,
      because the `floors` CI job resolves to it.
- [ ] Examples and `starter/` still run if the API they demonstrate changed.
