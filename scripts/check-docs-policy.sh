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
# Matched anywhere in the filename, case-insensitively: a file named
# *_STATUS.md is a status document just as much as STATUS.md is.
BANNED="$(
  find . \
    \( -name .git -o -name .venv -o -name node_modules -o -name .beads \) -prune -o \
    -type f -iname '*.md' -print \
  | grep -Ei '(HANDOFF|ROADMAP|TECH[_-]?DEBT|STATUS)[^/]*\.md$' || true
)"
if [ -n "$BANNED" ]; then
  # Fed via heredoc (not a pipe) so the loop runs in this shell and `fail`
  # can set STATUS for the parent to see.
  while IFS= read -r f; do
    fail "$f — status/roadmap/debt/handoff docs belong in GitHub issues, not the repo."
  done <<EOF
$BANNED
EOF
fi

# Rule 2 — docs/ allowlist. Every entry under docs/, not just *.md files: the
# policy has no markdown qualifier, so docs/notes.txt and docs/README.md.bak
# must also be rejected. Symlinks are included (git tracks them as repo
# entries too), so a symlink standing in for a non-canonical file can't
# bypass the allowlist.
if [ -d docs ]; then
  DOCS_FILES="$(find docs \( -type f -o -type l \))"
  if [ -n "$DOCS_FILES" ]; then
    while IFS= read -r f; do
      case "$f" in
        docs/README.md|docs/TYPES.md|docs/MAPPINGS.md) ;;
        docs/adr/*/*) fail "$f — docs/adr/ is flat; no nested directories." ;;
        docs/adr/*.md) ;;
        *) fail "$f — not a canonical docs/ file. See the policy table in docs/README.md." ;;
      esac
    done <<EOF
$DOCS_FILES
EOF
  fi
fi

if [ "$STATUS" -ne 0 ]; then
  echo "" >&2
  echo "Docs policy violated. The policy table lives in docs/README.md." >&2
  exit 1
fi

echo "docs-policy: ok"
