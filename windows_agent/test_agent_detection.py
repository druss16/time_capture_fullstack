#!/usr/bin/env python3
"""
Does the GUI recognise a *packaged* agent, and does the window still open?

Why this file exists. is_agent_running() identified the agent by looking for
"python" in the process name:

    if proc.is_running() and 'python' in proc.name().lower():

That is true in development, where the agent is `python main.py`. It is false
for every real install, where build.bat ships the agent as
TimeTrackerAgent.exe. So on a paired machine the GUI believed the agent was
never running, no matter how healthy it was. The fallback process scan had the
same flaw one level deeper: its `if 'python' not in name: continue` guard sat
above the branch that looked for the compiled exe, making that branch
unreachable.

On its own that is a wrong status light. Combined with main(), it silently
broke the app: once config.json held an api_key, main() spawned an agent and
returned *without ever creating a window*, on the assumption ("Either way,
agent is running") that the spawn had worked. So after pairing succeeded, the
desktop icon did nothing visible, forever, while quietly stacking up another
agent process on every double-click.

The autostart path is TimeTrackerAgent.exe directly (installer.iss [Run] and
startup_task.py), so nothing except a user double-clicking the icon runs
gui.main() — it should always show the window.

gui.py is imported here via AST rather than `import gui`, so the test needs
neither Tk nor customtkinter.

Run:
    python3 test_agent_detection.py

Exits non-zero if any assertion fails.
"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GUI_SRC = open(os.path.join(HERE, "gui.py"), encoding="utf-8").read()

_passed = _failed = 0


def check(label, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}")


def load(*names):
    """Pull top-level defs/assignments out of gui.py without importing it."""
    tree = ast.parse(GUI_SRC)
    ns = {}
    wanted = set(names)
    keep = [
        n for n in tree.body
        if (isinstance(n, (ast.FunctionDef,)) and n.name in wanted)
        or (isinstance(n, ast.Assign)
            and any(getattr(t, "id", None) in wanted for t in n.targets))
    ]
    exec(compile(ast.Module(keep, []), "gui-extract", "exec"), ns)
    return ns


ns = load("_is_agent_process", "AGENT_EXE_NAMES")
is_agent = ns["_is_agent_process"]

print("agent process detection:")

# The whole point: build.bat names the agent TimeTrackerAgent.exe.
check("packaged agent is recognised",
      is_agent("TimeTrackerAgent.exe", []))
check("...case-insensitively",
      is_agent("timetrackeragent.exe", None))
check("dev agent (python main.py) still recognised",
      is_agent("python.exe", ["python.exe", "main.py", "start"]))
check("...including a full path and pythonw",
      is_agent("pythonw.exe", ["pythonw.exe", r"C:\tt\main.py", "start"]))

# Must not mistake the GUI, the watchdog, or a stranger for the agent —
# a false positive means the agent never gets started.
check("the GUI itself is not the agent",
      not is_agent("TimeTracker.exe", []))
check("...nor the dev GUI",
      not is_agent("python.exe", ["python.exe", "gui.py"]))
check("the watchdog is not the agent",
      not is_agent("tt_watchdog.exe", []))
check("an unrelated process is not the agent",
      not is_agent("chrome.exe", []))
check("a missing process name is handled",
      not is_agent(None, None))

print("\nno dead branches left in the scan:")
check("the scan no longer skips non-python processes",
      "if 'python' not in name:" not in GUI_SRC)
check("the PID-file check no longer demands a python name",
      "'python' in proc.name().lower()" not in GUI_SRC)

print("\nthe window opens:")
main_src = GUI_SRC[GUI_SRC.index("def main():"):GUI_SRC.index('if __name__ == "__main__":')]
check("main() no longer returns before building the window",
      "ModernConfigGUI()" in main_src and "\n        return\n" not in main_src)
check("main() reaches app.run() for a paired device",
      "app.run()" in main_src)
check("a failed start is surfaced, not assumed to have worked",
      "start_error" in main_src and "spawn_agent_detached()" in main_src)
check("the status line re-checks on a timer, so it self-corrects",
      "self.root.after(3000, self._start_auto_refresh)" in GUI_SRC)
start_src = GUI_SRC[GUI_SRC.index("    def _start_agent(self):"):
                    GUI_SRC.index("    def _stop_agent(self):")]
check("starting the agent never blocks the UI thread",
      "time.sleep" not in start_src and "wait_for_agent" not in start_src)
check("the old 'Either way, agent is running' assumption is gone",
      "Either way, agent is running" not in GUI_SRC)

print("\npairing keeps the rest of config.json:")
check("save_config merges instead of rebuilding the dict",
      GUI_SRC.count("config = dict(self.config or {})") == 2)
check("...so no pairing path rebuilds it from scratch",
      '''config = {
                        "api_base": api_base,''' not in GUI_SRC)
check("success is only claimed when the agent really started",
      "def _show_paired_success(self, started=True):" in GUI_SRC
      and "started = self._start_agent()" in GUI_SRC)

print(f"\n  {_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
