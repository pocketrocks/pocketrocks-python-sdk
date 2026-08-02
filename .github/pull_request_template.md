<!-- The PR *title* becomes the squash-merge commit on develop.
     It must be a Conventional Commit — CI blocks it otherwise. -->

## What and why

<!-- One paragraph. Link the issue: Closes #123 -->

## Verification

<!-- What you actually ran, with results. Not a plan — evidence. -->

- [ ] `uv run pre-commit run --all-files`
- [ ] `uv run mypy src tests`
- [ ] `uv run pytest`

## Checklist

- [ ] Bumped `__version__` if anything under `src/pocketrocks/**` changed
- [ ] Bumped `RULES_VERSION` if rules behavior or golden traces changed
- [ ] Updated `README.md` / `docs/TYPES.md` / `docs/MAPPINGS.md` if the public
      surface changed
- [ ] Committed `uv.lock` if dependencies changed
- [ ] Skimmed [REVIEW.md](../REVIEW.md)
