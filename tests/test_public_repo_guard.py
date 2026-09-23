from __future__ import annotations

import importlib.util
import io
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prg", ROOT / ".claude/hooks/public-repo-guard.py")
prg = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(prg)
MARK = "PRIVATE-DO-NOT-PUBLISH" + ":" + "deadbeef-cafe-4bad-8bad-decafbad0000"


def run(event, payload):
    out = io.StringIO()
    assert prg.main(io.StringIO(json.dumps(payload)), out, ["x", event]) == 0
    return json.loads(out.getvalue()) if out.getvalue() else None


def test_session_start_warns_public():
    ctx = run("SessionStart", {})["hookSpecificOutput"]["additionalContext"]
    assert "PUBLIC" in ctx
    assert "strategy" in ctx.lower()


def test_mcp_write_with_marker_denied_and_reads_allowed():
    write_input = {"tool_name": "mcp__github__issue_write", "tool_input": {"body": f"x {MARK}"}}
    res = run("PreToolUse", write_input)
    assert res["hookSpecificOutput"]["permissionDecision"] == "deny"
    read_input = {"tool_name": "mcp__github__issue_read", "tool_input": {"body": MARK}}
    assert run("PreToolUse", read_input) is None


def test_clean_write_gets_reminder_not_deny():
    clean_input = {
        "tool_name": "mcp__github__create_pull_request",
        "tool_input": {"body": "fine"},
    }
    res = run("PreToolUse", clean_input)
    assert "permissionDecision" not in res["hookSpecificOutput"]
    assert "strategy" in res["hookSpecificOutput"]["additionalContext"].lower()


def test_every_pinned_mcp_tool_classifies():
    tools = json.loads((ROOT / "tests/fixtures/github_mcp_tools.json").read_text())
    for name in tools["reads"]:
        assert not prg.is_write_tool(f"mcp__github__{name}"), name
    for name in tools["writes"]:
        assert prg.is_write_tool(f"mcp__github__{name}"), name


def test_exception_fails_closed(monkeypatch):
    monkeypatch.setattr(prg, "text_hits", lambda t: 1 / 0)
    res = run("PreToolUse", {"tool_name": "mcp__github__issue_write", "tool_input": {"body": "x"}})
    assert res["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_source_contains_no_full_marker():
    src = (ROOT / ".claude/hooks/public-repo-guard.py").read_text()
    assert not prg.MARKER_RE.search(src)


def _hook_commands():
    settings = json.loads((ROOT / ".claude/settings.json").read_text())
    pre = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    start = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    return pre, start


def _with_missing_interpreter(command: str) -> str:
    assert command.startswith("python3 ")
    return "/opt/nonexistent_interpreter_path/python3 " + command[len("python3 ") :]


def _run_sh(command: str) -> subprocess.CompletedProcess[str]:
    # Fixed argv built from our own settings.json, not untrusted input; "sh" is resolved from
    # PATH deliberately, matching how Claude Code invokes hook commands.
    cmd = ["sh", "-c", command]
    return subprocess.run(  # noqa: S603
        cmd, capture_output=True, text=True, env={"CLAUDE_PROJECT_DIR": str(ROOT)}
    )


def test_pretooluse_command_is_fail_closed_at_exit_2():
    pre, _ = _hook_commands()
    assert pre.rstrip().endswith("|| exit 2")
    broken = _with_missing_interpreter(pre)
    proc = _run_sh(broken)
    assert proc.returncode == 2


def test_sessionstart_command_is_fail_closed_with_warning():
    _, start = _hook_commands()
    assert "|| echo" in start
    broken = _with_missing_interpreter(start)
    proc = _run_sh(broken)
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "PUBLIC" in payload["hookSpecificOutput"]["additionalContext"]
