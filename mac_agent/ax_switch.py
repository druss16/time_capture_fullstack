"""Remote Accessibility switch: MavOps turns `disable_ax` off (or back on)
for one Mac, and the agent rolls itself back if Accessibility freezes it.

`disable_ax` in ~/.timetracker/config.json was the field workaround for the
macOS 26 permission-check hang (#675). Clearing it used to need someone at
the Mac in Terminal. Now:

  1. MavOps sets AgentDevice.ax_switch; /api/agent/control/ (polled every
     10s) sends {"ax_capture": "on"|"off", "ax_capture_id": "<id>"}.
  2. apply_remote() acts once per id: it edits the config and says whether
     to restart, since DISABLE_AX is read once at import.
  3. Turning it on starts a TRIAL. Every launch inside it is counted by
     on_launch(); the switch's own restart is launch 1. A freeze anywhere
     (startup watchdog, tracking-loop watchdog) exits for a launchd
     relaunch, so a 3rd launch within TRIAL_S means it froze twice: put
     `disable_ax` back and record `ax_rolled_back`, which the hello2
     report carries to MavOps. The same id is never re-applied, so a
     rollback sticks until someone clicks again (a new id).

Pure functions on the config dict; main.py loads and saves it.
"""
from __future__ import annotations

TRIAL_S = 600
MAX_TRIAL_LAUNCHES = 3   # the switch's own restart + two freezes


def apply_remote(cfg: dict, state, switch_id, now: float) -> bool:
    """Apply a MavOps instruction. Returns True if the agent must restart
    for it to take effect (DISABLE_AX is fixed for the life of a process)."""
    if state not in ("on", "off") or not isinstance(switch_id, str) or not switch_id:
        return False
    if cfg.get("ax_switch_applied") == switch_id:
        return False
    cfg["ax_switch_applied"] = switch_id
    was_disabled = bool(cfg.get("disable_ax"))
    cfg.pop("ax_rolled_back", None)
    if state == "on":
        cfg.pop("disable_ax", None)
        if not was_disabled:
            return False
        cfg["ax_trial"] = {"started": now, "launches": 0}
        return True
    cfg["disable_ax"] = True
    cfg.pop("ax_trial", None)
    return not was_disabled


def on_launch(cfg: dict, now: float) -> str:
    """Count this launch against a running trial. Call before DISABLE_AX is
    read. Returns 'none', 'trial', 'passed' or 'rolled_back'; anything but
    'none' changed cfg and must be saved."""
    trial = cfg.get("ax_trial")
    if trial is None:
        return "none"
    started = trial.get("started") if isinstance(trial, dict) else None
    if cfg.get("disable_ax") or not isinstance(started, (int, float)):
        cfg.pop("ax_trial", None)
        return "passed"
    if now - started > TRIAL_S:
        cfg.pop("ax_trial", None)
        return "passed"
    launches = int(trial.get("launches") or 0) + 1
    if launches >= MAX_TRIAL_LAUNCHES:
        cfg.pop("ax_trial", None)
        cfg["disable_ax"] = True
        cfg["ax_rolled_back"] = now
        return "rolled_back"
    cfg["ax_trial"] = {"started": started, "launches": launches}
    return "trial"


def finish_trial(cfg: dict, now: float) -> bool:
    """The agent ran TRIAL_S without freezing twice: end the trial. True if
    cfg changed."""
    trial = cfg.get("ax_trial")
    if not isinstance(trial, dict):
        return False
    started = trial.get("started")
    if isinstance(started, (int, float)) and now - started <= TRIAL_S:
        return False
    cfg.pop("ax_trial", None)
    return True
