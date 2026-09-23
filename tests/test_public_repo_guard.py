from __future__ import annotations

import importlib.util
import io
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("prg", ROOT / ".claude/hooks/public-repo-guard.py")
assert _spec is not None
assert _spec.loader is not None
prg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prg)
MARK = "PRIVATE-DO-NOT-PUBLISH" + ":" + "deadbeef-cafe-4bad-8bad-decafbad0000"


def run(event: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    out = io.StringIO()
    assert prg.main(io.StringIO(json.dumps(payload)), out, ["x", event]) == 0
    result: dict[str, Any] | None = json.loads(out.getvalue()) if out.getvalue() else None
    return result


def test_session_start_warns_public() -> None:
    result = run("SessionStart", {})
    assert result is not None
    ctx = result["hookSpecificOutput"]["additionalContext"]
    assert "PUBLIC" in ctx
    assert "strategy" in ctx.lower()


def test_mcp_write_with_marker_denied_and_reads_allowed() -> None:
    write_input = {"tool_name": "mcp__github__issue_write", "tool_input": {"body": f"x {MARK}"}}
    res = run("PreToolUse", write_input)
    assert res is not None
    assert res["hookSpecificOutput"]["permissionDecision"] == "deny"
    read_input = {"tool_name": "mcp__github__issue_read", "tool_input": {"body": MARK}}
    assert run("PreToolUse", read_input) is None


def test_clean_write_gets_reminder_not_deny() -> None:
    clean_input = {
        "tool_name": "mcp__github__create_pull_request",
        "tool_input": {"body": "fine"},
    }
    res = run("PreToolUse", clean_input)
    assert res is not None
    assert "permissionDecision" not in res["hookSpecificOutput"]
    assert "strategy" in res["hookSpecificOutput"]["additionalContext"].lower()


def test_every_pinned_mcp_tool_classifies() -> None:
    tools = json.loads((ROOT / "tests/fixtures/github_mcp_tools.json").read_text())
    for name in tools["reads"]:
        assert not prg.is_write_tool(f"mcp__github__{name}"), name
    for name in tools["writes"]:
        assert prg.is_write_tool(f"mcp__github__{name}"), name


def test_exception_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prg, "text_hits", lambda t: 1 / 0)
    res = run("PreToolUse", {"tool_name": "mcp__github__issue_write", "tool_input": {"body": "x"}})
    assert res is not None
    assert res["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_gh_group_subcommand_writes_are_detected() -> None:
    for cmd in [
        "gh gist create notes.txt",
        "gh repo create my-new-repo --public",
        "gh label create bug --color FF0000",
        "gh workflow run ci.yml",
    ]:
        assert prg.is_bash_write(cmd), cmd


def test_gh_read_subcommand_is_not_a_write() -> None:
    assert not prg.is_bash_write("gh pr view 123")
    assert not prg.is_bash_write("gh issue list --json number,title")
    assert not prg.is_bash_write("gh repo clone octocat/hello-world")


def test_gh_api_needs_write_method_or_data_flag() -> None:
    assert not prg.is_bash_write("gh api repos/foo/bar/pulls/1/comments")
    assert prg.is_bash_write("gh api repos/foo/bar/issues -X POST -f title=x")
    assert prg.is_bash_write("gh api repos/foo/bar/issues --data '{}'")
    assert prg.is_bash_write("gh api -F title=x repos/foo/bar/issues")


def test_github_api_host_needs_write_method_or_data_flag() -> None:
    assert not prg.is_bash_write("curl https://api.github.com/repos/foo/bar")
    assert prg.is_bash_write("curl -X POST https://api.github.com/repos/foo/bar/issues")
    assert prg.is_bash_write(
        "curl --data '{}' https://uploads.github.com/repos/foo/bar/releases/1/assets"
    )


def test_bash_gh_write_end_to_end_is_scanned_not_noop() -> None:
    cmd = {"tool_name": "Bash", "tool_input": {"command": "gh repo create demo --public"}}
    res = run("PreToolUse", cmd)
    assert res is not None
    assert "strategy" in res["hookSpecificOutput"]["additionalContext"].lower()


def test_bash_gh_read_end_to_end_is_noop() -> None:
    cmd = {"tool_name": "Bash", "tool_input": {"command": "gh pr view 123"}}
    assert run("PreToolUse", cmd) is None


def test_source_contains_no_full_marker() -> None:
    src = (ROOT / ".claude/hooks/public-repo-guard.py").read_text()
    assert not prg.MARKER_RE.search(src)


def _hook_commands() -> tuple[str, str]:
    settings = json.loads((ROOT / ".claude/settings.json").read_text())
    pre: str = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    start: str = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
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


def test_pretooluse_command_is_fail_closed_at_exit_2() -> None:
    pre, _ = _hook_commands()
    assert pre.rstrip().endswith("|| exit 2")
    broken = _with_missing_interpreter(pre)
    proc = _run_sh(broken)
    assert proc.returncode == 2


def test_sessionstart_command_is_fail_closed_with_warning() -> None:
    _, start = _hook_commands()
    assert "|| echo" in start
    broken = _with_missing_interpreter(start)
    proc = _run_sh(broken)
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "PUBLIC" in payload["hookSpecificOutput"]["additionalContext"]
