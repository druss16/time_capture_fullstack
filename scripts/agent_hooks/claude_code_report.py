#!/usr/bin/env python3
"""
Claude Code hook: report this session's agent work to TimeTracker.

The desktop agent cannot see an AI agent working — it tracks the foreground
window and keyboard/mouse input, and a background agent has neither. So the
agent reports itself. Claude Code runs this on Stop (every turn end) and
SessionEnd; it reads the session transcript, builds a SNAPSHOT of the whole
session so far, and posts it to /api/agent-work/report/. Snapshots are
idempotent server-side, so re-posting is always safe.

Install (in ~/.claude/settings.json, or a project's .claude/settings.json):

    "hooks": {
      "Stop":       [{"hooks": [{"type": "command", "command": "python3 /path/to/claude_code_report.py"}]}],
      "SessionEnd": [{"hooks": [{"type": "command", "command": "python3 /path/to/claude_code_report.py"}]}]
    }

Auth is the paired desktop agent's device key from ~/.timetracker/config.json,
so the session is credited to whoever's machine ran it. Override with
TIMETRACKER_API_KEY / TIMETRACKER_API_BASE.

Client: put the client's exact TimeTracker name (or code) on the first line of
a `.timetracker-client` file in the project folder or any parent, or set
TIMETRACKER_CLIENT. Nothing is guessed from folder names.

Never blocks Claude Code: every failure is logged to ~/.timetracker/
agent_hook.log and the hook exits 0. Prompt and response text is never sent —
only timestamps, counts and token usage.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

DEFAULT_API_BASE = "https://timetracker-api-k375.onrender.com/api"
CONFIG_FILE = os.path.expanduser("~/.timetracker/config.json")
LOG_FILE = os.path.expanduser("~/.timetracker/agent_hook.log")
CLIENT_FILE = ".timetracker-client"

# A gap longer than this between two steps inside a turn is the agent waiting
# on the human (an approval prompt left open over lunch), not the agent
# working. Ten minutes leaves room for a long test run or build.
MAX_WORK_GAP_S = 600


def _ts(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def _is_human_prompt(entry) -> bool:
    """A user-typed prompt, as opposed to a tool result fed back to the model."""
    if entry.get("type") != "user" or entry.get("isMeta"):
        return False
    origin = entry.get("origin")
    if isinstance(origin, dict) and origin.get("kind"):
        return origin["kind"] == "human"
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, list):
        return not any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content)
    return isinstance(content, str)


def snapshot_from_transcript(lines) -> dict | None:
    """The session's running totals from its JSONL transcript lines."""
    steps = []          # (timestamp, is_human_prompt) on the main thread
    usage_by_msg = {}   # message id -> usage; one response spans several lines
    model = ""
    for line in lines:
        try:
            entry = json.loads(line)
        except (TypeError, ValueError):
            continue
        if entry.get("type") not in ("user", "assistant"):
            continue
        msg = entry.get("message") or {}
        if entry["type"] == "assistant":
            # Subagent (sidechain) usage still counts: it is real spend.
            if msg.get("id") and isinstance(msg.get("usage"), dict):
                usage_by_msg[msg["id"]] = msg["usage"]
            if msg.get("model") and not str(msg["model"]).startswith("<"):
                model = msg["model"]
        if entry.get("isSidechain"):
            continue
        ts = _ts(entry.get("timestamp"))
        if ts:
            steps.append((ts, _is_human_prompt(entry)))

    if not steps:
        return None
    steps.sort(key=lambda s: s[0])

    active = 0.0
    turns = 0
    for (prev_ts, _), (ts, is_prompt) in zip([(None, False)] + steps[:-1], steps):
        if is_prompt:
            turns += 1          # the gap before a prompt is the human's time
            continue
        if prev_ts is None:
            continue
        gap = (ts - prev_ts).total_seconds()
        if 0 < gap <= MAX_WORK_GAP_S:
            active += gap

    def total(key):
        return sum(int(u.get(key) or 0) for u in usage_by_msg.values())

    return {
        "started_at": steps[0][0].astimezone(timezone.utc).isoformat(),
        "last_activity_at": steps[-1][0].astimezone(timezone.utc).isoformat(),
        "active_seconds": int(active),
        "turns": turns,
        "model": model,
        "tokens": {
            "input": total("input_tokens"),
            "output": total("output_tokens"),
            "cache_read": total("cache_read_input_tokens"),
            "cache_write": total("cache_creation_input_tokens"),
        },
    }


def client_hint(cwd: str) -> str:
    env = os.environ.get("TIMETRACKER_CLIENT", "").strip()
    if env:
        return env
    path = os.path.abspath(cwd or os.getcwd())
    while True:
        candidate = os.path.join(path, CLIENT_FILE)
        if os.path.isfile(candidate):
            try:
                with open(candidate, encoding="utf-8") as f:
                    for line in f:
                        if line.strip() and not line.lstrip().startswith("#"):
                            return line.strip()
            except OSError:
                pass
            return ""
        parent = os.path.dirname(path)
        if parent == path:
            return ""
        path = parent


def _credentials():
    config = {}
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, ValueError):
        pass
    key = os.environ.get("TIMETRACKER_API_KEY") or config.get("api_key") or ""
    base = os.environ.get("TIMETRACKER_API_BASE") or config.get("api_base") or DEFAULT_API_BASE
    return key, base.rstrip("/")


def _log(msg: str) -> None:
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {msg}\n")
    except OSError:
        pass


def main() -> None:
    hook = json.load(sys.stdin)
    session_id = hook.get("session_id") or ""
    transcript = hook.get("transcript_path") or ""
    if not session_id or not os.path.isfile(transcript):
        return
    with open(transcript, encoding="utf-8") as f:
        snap = snapshot_from_transcript(f)
    if not snap:
        return

    key, base = _credentials()
    if not key:
        _log("no device key — is the TimeTracker desktop agent paired on this machine?")
        return

    cwd = hook.get("cwd") or ""
    payload = dict(
        snap,
        agent_kind="claude_code",
        session_id=session_id,
        ended=hook.get("hook_event_name") == "SessionEnd",
        project_path=cwd,
        client=client_hint(cwd),
    )
    req = urllib.request.Request(
        f"{base}/agent-work/report/",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Agent-Key": key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        if resp.status >= 300:
            _log(f"report {session_id[:8]} -> HTTP {resp.status}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never break the user's Claude Code session
        _log(f"error: {type(e).__name__}: {e}")
    sys.exit(0)
