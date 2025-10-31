#!/usr/bin/env python3
import os, subprocess, rumps, pathlib, time

APP_NAME = "TimeTracker Agent"
BIN = os.path.expanduser("~/.timetracker/bin/TimeTrackerAgent")
LOG_DIR = os.path.expanduser("~/Library/Logs/ActivityAgent")
PID_FILE = os.path.expanduser("~/Library/ActivityAgent/agent.pid")

def _running():
    if not os.path.exists(PID_FILE): return False
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except Exception:
        return False

def _start():
    # start in background
    return subprocess.Popen([BIN, "start-bg"])

def _stop():
    if os.path.exists(BIN):
        subprocess.call([BIN, "stop"])

def _tail_log(n=200):
    p = os.path.join(LOG_DIR, "stdout.log")
    if not os.path.exists(p): return "(no log yet)"
    try:
        out = subprocess.check_output(["tail", f"-n{n}", p], text=True)
        return out
    except Exception:
        return "(unable to read log)"

class MenuApp(rumps.App):
    def __init__(self):
        super(MenuApp, self).__init__(APP_NAME, icon=None, quit_button=None)
        self.menu = [
            rumps.MenuItem("Start Agent", callback=self.start_agent),
            rumps.MenuItem("Stop Agent", callback=self.stop_agent),
            None,
            rumps.MenuItem("Status", callback=self.show_status),
            rumps.MenuItem("View Log", callback=self.view_log),
            None,
            rumps.MenuItem("Quit Controller", callback=self.quit_controller),
        ]
        rumps.debug_mode(False)

    def start_agent(self, _):
        if _running():
            rumps.notification(APP_NAME, "", "Already running.")
            return
        os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
        _start()
        time.sleep(0.6)
        rumps.notification(APP_NAME, "", "Agent started.")

    def stop_agent(self, _):
        if not _running():
            rumps.notification(APP_NAME, "", "Not running.")
            return
        _stop()
        time.sleep(0.6)
        rumps.notification(APP_NAME, "", "Agent stopped.")

    def show_status(self, _):
        msg = "Running" if _running() else "Stopped"
        rumps.alert(f"Agent status: {msg}")

    def view_log(self, _):
        with rumps.Window(_tail_log(), title="ActivityAgent Log", default_text="", dimensions=(600, 400)).alert():
            pass

    def quit_controller(self, _):
        rumps.quit_application()

if __name__ == "__main__":
    MenuApp().run()