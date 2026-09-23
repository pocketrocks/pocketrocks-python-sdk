#!/usr/bin/env python3
"""Public-repo guard for pocketrocks-python-sdk (committed; runs in cloud and local sessions).

This repository is PUBLIC. The guard reminds agents of that, and blocks writes carrying the
private-code marker. It holds no private data: only the generic marker prefix and its pattern.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Iterable
from typing import Any, TextIO

MARKER_RE = re.compile("PRIVATE-DO-NOT-PUBLISH" + r":[0-9a-f-]{36}")
_READ = re.compile(r"(read|list|get|search)", re.I)
_GIT_WRITE = re.compile(
    r"\bgit\b[^;&|]*\b(commit|push)\b|\bgh\b[^;&|]*\b(pr|issue|release|api)\b|"
    r"(api|uploads)\.github\.com"
)
REMINDER = (
    "This repository is PUBLIC. It must stay strategy-free: no tuned constants, no strong or "
    "ranked bots, no benchmark results, nothing learned from private research. If a task needs "
    "private knowledge, stop and ask the maintainer instead of inferring it."
)


def is_write_tool(name: str) -> bool:
    return name.startswith("mcp__github__") and not _READ.search(name.split("__")[-1])


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
            if not _GIT_WRITE.search(tin.get("command", "")):
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
