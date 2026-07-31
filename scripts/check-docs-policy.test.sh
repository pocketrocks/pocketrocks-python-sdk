#!/usr/bin/env bash
# Tests for check-docs-policy.sh. Runs the guard against synthetic trees in a
# temp directory so it never depends on the real repo's current contents.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GUARD="$SCRIPT_DIR/check-docs-policy.sh"
FAILURES=0

run_case() {
  local name="$1" expected="$2"; shift 2
  local tmp; tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  mkdir -p "$tmp/docs" "$tmp/src/pocketrocks" "$tmp/scripts"
  # Files every valid tree has.
  touch "$tmp/README.md" "$tmp/CONTRIBUTING.md" "$tmp/REVIEW.md" \
        "$tmp/docs/README.md" "$tmp/docs/TYPES.md" "$tmp/docs/MAPPINGS.md"
  for f in "$@"; do mkdir -p "$tmp/$(dirname "$f")"; touch "$tmp/$f"; done

  local actual=0
  ( cd "$tmp" && sh "$GUARD" >/dev/null 2>&1 ) || actual=$?

  if [ "$expected" -eq 0 ] && [ "$actual" -eq 0 ]; then
    echo "ok   — $name"
  elif [ "$expected" -ne 0 ] && [ "$actual" -ne 0 ]; then
    echo "ok   — $name"
  else
    echo "FAIL — $name (expected exit $expected, got $actual)"
    FAILURES=$((FAILURES + 1))
  fi
}

run_case "canonical tree passes"                       0
run_case "adr files allowed"                           0 "docs/adr/2026-07-31-example.md"
run_case "subsystem README next to code allowed"       0 "src/pocketrocks/sim/README.md"
run_case "examples README allowed"                     0 "examples/README.md"
run_case "handoff doc rejected"                        1 "docs/SESSION_HANDOFF.md"
run_case "handoff doc rejected at root"                1 "HANDOFF.md"
run_case "roadmap rejected"                            1 "docs/ROADMAP.md"
run_case "tech debt rejected"                          1 "docs/TECH_DEBT.md"
run_case "status doc rejected"                         1 "STATUS.md"
run_case "uncanonical docs/ file rejected"             1 "docs/RANDOM_NOTES.md"
run_case "nested dir under docs rejected"              1 "docs/design/thing.md"

if [ "$FAILURES" -ne 0 ]; then
  echo "$FAILURES test(s) failed."
  exit 1
fi
echo "All docs-policy tests passed."
