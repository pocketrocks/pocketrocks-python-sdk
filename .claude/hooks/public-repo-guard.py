#!/usr/bin/env python3
"""Public-repo guard for pocketrocks-python-sdk (committed; runs in cloud and local sessions).

This repository is PUBLIC. The guard reminds agents of that, and blocks writes carrying the
private-code marker. It holds no private data: only the generic marker prefix and its pattern.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from collections.abc import Iterable
from typing import Any, TextIO

MARKER_RE = re.compile("PRIVATE-DO-NOT-PUBLISH" + r":[0-9a-f-]{36}")
_READ = re.compile(r"(read|list|get|search)", re.I)
# mark_all_notifications_read *mutates* read-state despite matching _READ by name; any other
# tool the fixture in tests/fixtures/github_mcp_tools.json reveals as misclassified goes here too.
_WRITE_OVERRIDES = frozenset({"mark_all_notifications_read"})

_GIT_COMMIT_OR_PUSH = re.compile(r"\bgit\b[^;&|]*\b(commit|push)\b")
_GH_MENTION = re.compile(r"\bgh\b")
# `gh <group> <sub>`: a write unless the subcommand is one of these non-mutating verbs. `gh api`
# is excluded here and handled on its own below, since its second token is a URL path, not a
# subcommand drawn from this vocabulary.
_GH_READ_SUBS = frozenset(
    {
        "view",
        "list",
        "status",
        "diff",
        "checks",
        "search",
        "browse",
        "clone",
        "checkout",
        "watch",
        "download",
    }
)
# gh's own global flags that take a value as a separate token, so they (and that value) must be
# skipped before the group/subcommand pair can be read off the token stream.
_GH_VALUE_FLAGS = frozenset({"-R", "--repo", "--hostname"})
# Belt-and-braces: if the group/sub parse above is defeated by some flag shape we didn't
# anticipate, still catch a write if any of these mutating verbs shows up anywhere in the
# tokenized command. Over-detection here only produces a REMINDER, never a deny — deny still
# requires an actual marker hit — so a false positive is cheap and a false negative is not.
_GH_FAILSAFE_WRITE_VERBS = frozenset(
    {
        "create",
        "comment",
        "edit",
        "merge",
        "close",
        "delete",
        "review",
        "upload",
        "set",
        "run",
        "transfer",
        "fork",
        "sync",
    }
)
_GH_API = re.compile(r"\bgh\s+api\b", re.I)
# A write HTTP method or a flag that attaches a request body.
_WRITE_METHOD_OR_DATA = re.compile(
    r"-X\s*(?:POST|PUT|PATCH|DELETE)\b|--data(?:-\w+)?\b|-d\b|-F\b|--json\b", re.I
)
_GITHUB_API_HOST = re.compile(r"\b(?:api|uploads)\.github\.com\b")
REMINDER = (
    "This repository is PUBLIC. It must stay strategy-free: no tuned constants, no strong or "
    "ranked bots, no benchmark results, nothing learned from private research. If a task needs "
    "private knowledge, stop and ask the maintainer instead of inferring it."
)


def is_write_tool(name: str) -> bool:
    if not name.startswith("mcp__github__"):
        return False
    tool = name.split("__")[-1]
    if tool in _WRITE_OVERRIDES:
        return True
    return not _READ.search(tool)


def _tokenize(command: str) -> tuple[list[str], bool]:
    """Split into shell words. Returns (tokens, parse_failed) — an unbalanced-quote command
    falls back to a plain whitespace split, and the caller must treat that as a write: we can no
    longer trust the token boundaries enough to conclude it's safe."""
    try:
        return shlex.split(command), False
    except ValueError:
        return command.split(), True


def _gh_group_sub(tokens: list[str]) -> tuple[str, str] | None:
    try:
        i = tokens.index("gh") + 1
    except ValueError:
        return None
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        if tok in _GH_VALUE_FLAGS:
            i += 2  # flag + its value, e.g. -R owner/repo, --hostname host
            continue
        if tok.startswith("--") and "=" in tok:
            i += 1  # --repo=owner/repo
            continue
        if tok.startswith("-"):
            i += 1  # any other global flag token
            continue
        break
    if i + 1 < n:
        return tokens[i].lower(), tokens[i + 1].lower()
    return None


def _is_gh_write(command: str) -> bool:
    if not _GH_MENTION.search(command):
        return False
    tokens, parse_failed = _tokenize(command)
    if parse_failed:
        return True
    pair = _gh_group_sub(tokens)
    if pair is not None:
        group, sub = pair
        if group != "api" and sub not in _GH_READ_SUBS:
            return True
    if _GH_API.search(command) and _WRITE_METHOD_OR_DATA.search(command):
        return True
    lowered_tokens = {t.lower() for t in tokens}
    return bool(lowered_tokens & _GH_FAILSAFE_WRITE_VERBS)


def is_bash_write(command: str) -> bool:
    if _GIT_COMMIT_OR_PUSH.search(command):
        return True
    if _is_gh_write(command):
        return True
    return bool(_GITHUB_API_HOST.search(command) and _WRITE_METHOD_OR_DATA.search(command))


def text_hits(text: str) -> list[str]:
    return [m.group(0)[:23] for m in MARKER_RE.finditer(text)]


def _strings(obj: Any) -> Iterable[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def _git(*args: str) -> str:
    # Fixed argv, no shell, git resolved from PATH: expected in any session this hook runs in.
    cmd = ["git", *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout  # noqa: S603


def _bash_texts(command: str) -> list[str]:
    texts = [command]
    if re.search(r"\bgit\b[^;&|]*\bcommit\b", command):
        texts.append(_git("diff", "--cached"))
    if re.search(r"\bgit\b[^;&|]*\bpush\b", command):
        texts.append(_git("log", "-p", "--all", "--not", "--remotes"))
    for m in re.finditer(r"(?:--body-file|-F|--input)\s+@?(\S+)", command):
        try:
            with open(m.group(1)) as f:
                texts.append(f.read())
        except OSError:
            pass
    return texts


def _out(stdout: TextIO, event: str, **kw: Any) -> None:
    stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": event, **kw}}))


def main(stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout, argv: list[str] = sys.argv) -> int:
    event = argv[1] if len(argv) > 1 else "PreToolUse"
    if event == "SessionStart":
        _out(
            stdout,
            "SessionStart",
            additionalContext=REMINDER
            + " The SDK ships toy sample bots and simple, untuned primitives only.",
        )
        return 0
    try:
        payload = json.load(stdin)
        tool, tin = payload.get("tool_name", ""), payload.get("tool_input", {}) or {}
        if tool == "Bash":
            if not is_bash_write(tin.get("command", "")):
                return 0
            texts = _bash_texts(tin.get("command", ""))
        elif is_write_tool(tool):
            texts = list(_strings(tin))
        else:
            return 0
        hits = [h for t in texts for h in text_hits(t)]
        if hits:
            _out(
                stdout,
                "PreToolUse",
                permissionDecision="deny",
                permissionDecisionReason=(
                    "[public-repo-guard] private-code marker found; this repo is public."
                ),
            )
        else:
            _out(stdout, "PreToolUse", additionalContext=REMINDER)
    except Exception as e:  # noqa: BLE001 — fail closed on any guard error, per policy
        _out(
            stdout,
            "PreToolUse",
            permissionDecision="deny",
            permissionDecisionReason=(
                f"[public-repo-guard] guard error, failing closed: {type(e).__name__}"
            ),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
