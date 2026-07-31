#!/usr/bin/env sh
# Enforces the docs policy in docs/README.md: one fact, one home.
#
# Two rules:
#   1. Status-shaped documents (HANDOFF / ROADMAP / TECH_DEBT / STATUS) are
#      banned anywhere in the tree. They go stale silently because no reviewer
#      owns them; GitHub issues have an assignee, a state, and a close event.
#   2. Inside docs/, only the canonical files are allowed, plus the flat adr/
#      subdirectory. Anything else means a fact grew a second home.
#
# Subsystem READMEs next to code are explicitly fine — that is where "how this
# works" belongs.
set -eu

STATUS=0
fail() { echo "docs-policy: $1" >&2; STATUS=1; }

# Rule 1 — banned document shapes, anywhere except vendored/ignored trees.
BANNED="$(
  find . \
    \( -name .git -o -name .venv -o -name node_modules -o -name .beads \) -prune -o \
    -type f -name '*.md' -print \
  | grep -Ei '(HANDOFF|ROADMAP|TECH[_-]?DEBT|(^|/)STATUS)[^/]*\.md$' || true
)"
if [ -n "$BANNED" ]; then
  while read -r f; do
    fail "$f — status/roadmap/debt/handoff docs belong in GitHub issues, not the repo."
  done <<EOF
$BANNED
EOF
fi

# Rule 2 — docs/ allowlist.
if [ -d docs ]; then
  for f in $(find docs -type f -name '*.md' | sed 's|^\./||'); do
    case "$f" in
      docs/README.md|docs/TYPES.md|docs/MAPPINGS.md) ;;
      docs/adr/*/*) fail "$f — docs/adr/ is flat; no nested directories." ;;
      docs/adr/*.md) ;;
      *) fail "$f — not a canonical docs/ file. See the policy table in docs/README.md." ;;
    esac
  done
fi

if [ "$STATUS" -ne 0 ]; then
  echo "" >&2
  echo "Docs policy violated. The policy table lives in docs/README.md." >&2
  exit 1
fi

echo "docs-policy: ok"
