#!/usr/bin/env python3
import json, os, subprocess, sys, tkinter as tk
from tkinter import ttk, messagebox, filedialog

CFG_DIR = os.path.expanduser("~/.timetracker")
CFG = os.path.join(CFG_DIR, "config.json")
PLIST = os.path.expanduser("~/Library/LaunchAgents/com.mavops.activityagent.plist")

def load_cfg():
    try:
        with open(CFG) as f:
            return json.load(f)
    except Exception:
        return {}

def save_cfg(data):
    os.makedirs(CFG_DIR, exist_ok=True)
    with open(CFG, "w") as f:
        json.dump(data, f, indent=2)

def launchctl(args):
    try:
        out = subprocess.run(["/bin/launchctl"] + args, capture_output=True, text=True)
        return out.returncode, out.stdout, out.stderr
    except Exception as e:
        return 1, "", str(e)

def is_loaded():
    code, _, _ = launchctl(["print", f"gui/{os.getuid()}/com.mavops.activityagent"])
    return code == 0

def load_agent():
    if not os.path.exists(PLIST):
        messagebox.showerror("Missing", "LaunchAgent not installed. Run launchd/install.sh first.")
        return
    launchctl(["load", "-w", PLIST])

def unload_agent():
    launchctl(["unload", PLIST])

def reload_agent():
    unload_agent()
    load_agent()

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TimeTracker Agent")
        self.geometry("520x300")
        self.resizable(False, False)
        self.cfg = load_cfg()

        frm = ttk.Frame(self, padding=14)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="API URL").grid(row=0, column=0, sticky="w")
        self.api_url = tk.StringVar(value=self.cfg.get("api_url", "http://localhost:7123/api/raw-events/"))
        ttk.Entry(frm, textvariable=self.api_url, width=60).grid(row=0, column=1, sticky="we")

        ttk.Label(frm, text="Agent Key").grid(row=1, column=0, sticky="w")
        self.api_key = tk.StringVar(value=self.cfg.get("api_key", ""))
        ttk.Entry(frm, textvariable=self.api_key, width=60).grid(row=1, column=1, sticky="we")

        ttk.Label(frm, text="Poll seconds").grid(row=2, column=0, sticky="w")
        self.poll = tk.IntVar(value=int(self.cfg.get("poll_seconds", 5)))
        ttk.Entry(frm, textvariable=self.poll, width=8).grid(row=2, column=1, sticky="w")

        ttk.Label(frm, text="Min dwell seconds").grid(row=3, column=0, sticky="w")
        self.dwell = tk.IntVar(value=int(self.cfg.get("min_dwell_seconds", 15)))
        ttk.Entry(frm, textvariable=self.dwell, width=8).grid(row=3, column=1, sticky="w")

        self.verbose = tk.BooleanVar(value=bool(self.cfg.get("verbose", True)))
        ttk.Checkbutton(frm, text="Verbose logging", variable=self.verbose).grid(row=4, column=1, sticky="w")

        btns = ttk.Frame(frm)
        btns.grid(row=5, column=0, columnspan=2, pady=(14,0))
        ttk.Button(btns, text="Save", command=self.on_save).grid(row=0, column=0, padx=6)
        ttk.Button(btns, text="Start", command=self.on_start).grid(row=0, column=1, padx=6)
        ttk.Button(btns, text="Stop", command=self.on_stop).grid(row=0, column=2, padx=6)
        ttk.Button(btns, text="Status", command=self.on_status).grid(row=0, column=3, padx=6)
        ttk.Button(btns, text="Open Logs", command=self.open_logs).grid(row=0, column=4, padx=6)

        self.status_lbl = ttk.Label(frm, text="")
        self.status_lbl.grid(row=6, column=0, columnspan=2, sticky="w", pady=(10,0))
        self.refresh_status()

        for i in range(2):
            frm.columnconfigure(i, weight=1)

    def on_save(self):
        data = load_cfg()
        data["api_url"] = self.api_url.get().strip()
        data["api_key"] = self.api_key.get().strip()
        data["poll_seconds"] = int(self.poll.get())
        data["min_dwell_seconds"] = int(self.dwell.get())
        data["verbose"] = bool(self.verbose.get())
        save_cfg(data)
        messagebox.showinfo("Saved", "Configuration saved.\nReloading agent to pick up env…")
        reload_agent()
        self.refresh_status()

    def on_start(self):
        load_agent()
        self.refresh_status()

    def on_stop(self):
        unload_agent()
        self.refresh_status()

    def on_status(self):
        self.refresh_status()

    def refresh_status(self):
        self.status_lbl.config(text=("Agent: RUNNING" if is_loaded() else "Agent: STOPPED"))

    def open_logs(self):
        logdir = os.path.expanduser("~/Library/Logs/ActivityAgent")
        subprocess.Popen(["open", logdir])

if __name__ == "__main__":
    App().mainloop()