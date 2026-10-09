"""What the agent does with the MavOps → Devices "Request logs" and "Restart"
buttons.

Each button sets a one-shot flag on the AgentDevice row; /api/agent/control/
returns it as "ship_logs": true / "restart": true exactly once and clears it.
Until this module the Mac agent read neither key, so both buttons were silent
no-ops for every Mac (the Windows agent has always acted on them).

Restart means exiting so the LaunchAgent (com.mavops.timetracker, KeepAlive)
relaunches us. That only works when launchd is the parent (parent pid 1) — the
same guard restart_if_orphaned uses. Run by hand from a terminal, exiting
would just stop tracking, so the request is refused and logged instead.

Plain Python, no macOS calls: test_remote_control.py drives it directly.
"""
from __future__ import annotations

from typing import NamedTuple, Optional

# Non-zero, so KeepAlive (SuccessfulExit=false or plain true) relaunches.
RESTART_EXIT_CODE = 3


class ControlActions(NamedTuple):
    ship_logs: bool
    # "exit": relaunch via launchd now; "refuse": asked, but not under launchd;
    # None: not asked.
    restart: Optional[str]


def control_actions(data: Optional[dict], ppid: int) -> ControlActions:
    data = data or {}
    restart = None
    if data.get("restart"):
        restart = "exit" if ppid == 1 else "refuse"
    return ControlActions(ship_logs=bool(data.get("ship_logs")), restart=restart)
