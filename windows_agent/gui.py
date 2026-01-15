#!/usr/bin/env python3
"""
TimeTracker Configuration GUI

Simple Tkinter GUI for configuring and managing the TimeTracker agent.
"""

import os
import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import sys

CONFIG_DIR = os.path.expanduser("~/.timetracker")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
APPDATA = os.environ.get("APPDATA", os.path.expanduser("~"))
PID_FILE = os.path.join(APPDATA, "TimeTracker", "agent.pid")

def get_agent_exe_path():
    """Get path to TimeTrackerAgent.exe"""
    # When running as PyInstaller bundle, look in same directory as this exe
    if getattr(sys, 'frozen', False):
        # Running as compiled exe
        base_dir = os.path.dirname(sys.executable)
    else:
        # Running as script (development)
        base_dir = os.path.dirname(__file__)
    
    agent_exe = os.path.join(base_dir, "TimeTrackerAgent.exe")
    
    # Fallback to main.py for development
    if not os.path.exists(agent_exe):
        agent_py = os.path.join(base_dir, "main.py")
        if os.path.exists(agent_py):
            return (sys.executable, agent_py)  # Return tuple for subprocess
    
    return agent_exe

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_config(config):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

def is_agent_running():
    """Check if agent is running via PID file"""
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        # Try to check if process exists (Windows)
        import ctypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_INFORMATION = 0x0400
        handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, 0, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:
        return False

class ConfigGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("TimeTracker Agent Configuration")
        self.root.geometry("600x500")
        self.root.resizable(False, False)
        
        self.config = load_config()
        
        self._setup_ui()
        self._update_status()       
        self._start_auto_refresh()
    
    def _setup_ui(self):
        # Title
        title = tk.Label(self.root, text="TimeTracker Agent", font=("Arial", 16, "bold"))
        title.pack(pady=10)
        
        # Status frame
        status_frame = tk.LabelFrame(self.root, text="Status", padx=10, pady=10)
        status_frame.pack(fill=tk.X, padx=20, pady=10)
        
        self.status_label = tk.Label(status_frame, text="Agent: STOPPED", 
                                     font=("Arial", 11, "bold"), fg="red")
        self.status_label.pack()
        
        # Control buttons
        btn_frame = tk.Frame(status_frame)
        btn_frame.pack(pady=10)
        
        self.start_btn = tk.Button(btn_frame, text="Start Agent", command=self._start_agent,
                                   width=12, bg="#4CAF50", fg="white")
        self.start_btn.pack(side=tk.LEFT, padx=5)
        
        self.stop_btn = tk.Button(btn_frame, text="Stop Agent", command=self._stop_agent,
                                  width=12, bg="#f44336", fg="white")
        self.stop_btn.pack(side=tk.LEFT, padx=5)
        
        refresh_btn = tk.Button(btn_frame, text="Refresh", command=self._update_status,
                               width=12)
        refresh_btn.pack(side=tk.LEFT, padx=5)
        
        # Configuration frame
        config_frame = tk.LabelFrame(self.root, text="Configuration", padx=10, pady=10)
        config_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # API URL
        tk.Label(config_frame, text="API URL:").grid(row=0, column=0, sticky="w", pady=5)
        self.api_url_var = tk.StringVar(value=self.config.get("api_base", "https://timetracker-api-k375.onrender.com/api"))
        api_entry = tk.Entry(config_frame, textvariable=self.api_url_var, width=50)
        api_entry.grid(row=0, column=1, pady=5, padx=5)
        
        # API Key
        tk.Label(config_frame, text="API Key:").grid(row=1, column=0, sticky="w", pady=5)
        self.api_key_var = tk.StringVar(value=self.config.get("api_key", ""))
        api_key_entry = tk.Entry(config_frame, textvariable=self.api_key_var, width=50, show="*")
        api_key_entry.grid(row=1, column=1, pady=5, padx=5)
        
        # Show/Hide API key
        def toggle_key():
            if api_key_entry["show"] == "*":
                api_key_entry["show"] = ""
                show_btn.config(text="Hide")
            else:
                api_key_entry["show"] = "*"
                show_btn.config(text="Show")
        
        show_btn = tk.Button(config_frame, text="Show", command=toggle_key, width=6)
        show_btn.grid(row=1, column=2, padx=5)
        
        # Pairing code (optional)
        tk.Label(config_frame, text="Pairing Code:").grid(row=2, column=0, sticky="w", pady=5)
        self.pair_code_var = tk.StringVar(value=self.config.get("pair_code", ""))
        pair_entry = tk.Entry(config_frame, textvariable=self.pair_code_var, width=50)
        pair_entry.grid(row=2, column=1, pady=5, padx=5)
        
        tk.Label(config_frame, text="(Leave blank if already paired)", 
                font=("Arial", 8), fg="gray").grid(row=3, column=1, sticky="w")
        
        # Poll seconds
        tk.Label(config_frame, text="Poll Seconds:").grid(row=4, column=0, sticky="w", pady=5)
        self.poll_var = tk.IntVar(value=int(self.config.get("poll_seconds", 5)))
        poll_spin = tk.Spinbox(config_frame, from_=1, to=30, textvariable=self.poll_var, width=10)
        poll_spin.grid(row=4, column=1, sticky="w", pady=5, padx=5)
        
        # Min dwell seconds
        tk.Label(config_frame, text="Min Dwell Seconds:").grid(row=5, column=0, sticky="w", pady=5)
        self.dwell_var = tk.IntVar(value=int(self.config.get("min_dwell_seconds", 15)))
        dwell_spin = tk.Spinbox(config_frame, from_=5, to=120, textvariable=self.dwell_var, width=10)
        dwell_spin.grid(row=5, column=1, sticky="w", pady=5, padx=5)
        
        # Verbose logging
        self.verbose_var = tk.BooleanVar(value=bool(self.config.get("verbose", True)))
        verbose_check = tk.Checkbutton(config_frame, text="Verbose Logging", 
                                       variable=self.verbose_var)
        verbose_check.grid(row=6, column=1, sticky="w", pady=5)
        
        # Save button
        save_btn = tk.Button(config_frame, text="Save Configuration", command=self._save_config,
                            width=20, bg="#2196F3", fg="white", font=("Arial", 10, "bold"))
        save_btn.grid(row=7, column=0, columnspan=3, pady=15)
        
        # Bottom buttons
        bottom_frame = tk.Frame(self.root)
        bottom_frame.pack(fill=tk.X, padx=20, pady=10)
        
        logs_btn = tk.Button(bottom_frame, text="Open Logs Folder", command=self._open_logs)
        logs_btn.pack(side=tk.LEFT, padx=5)
        
        test_btn = tk.Button(bottom_frame, text="Test System", command=self._test_system)
        test_btn.pack(side=tk.LEFT, padx=5)
        
        help_btn = tk.Button(bottom_frame, text="Help", command=self._show_help)
        help_btn.pack(side=tk.RIGHT, padx=5)


    def _start_auto_refresh(self):
        """Auto-refresh status every 3 seconds"""
        self._update_status()
        self.root.after(3000, self._start_auto_refresh)

    def _update_status(self):
        """Update agent status display"""
        if is_agent_running():
            self.status_label.config(text="Agent: RUNNING", fg="green")
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
        else:
            self.status_label.config(text="Agent: STOPPED", fg="red")
            self.start_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
    
    def _start_agent(self):
        """Start the agent"""
        try:
            agent_path = get_agent_exe_path()
            
            # Handle both exe and (python, script) tuple
            if isinstance(agent_path, tuple):
                # Development mode: (python_exe, script_path)
                cmd = list(agent_path) + ["start"]
            else:
                # Production mode: TimeTrackerAgent.exe
                cmd = [agent_path, "start"]
            
            # Start in background without console window
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            
            subprocess.Popen(
                cmd,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            
            # Wait a bit and refresh
            self.root.after(1000, self._update_status)
            messagebox.showinfo("Success", "Agent started successfully!")
        
        except Exception as e:
            messagebox.showerror("Error", f"Failed to start agent: {e}")
    
    def _stop_agent(self):
        """Stop the agent"""
        try:
            agent_path = get_agent_exe_path()
            
            # Handle both exe and (python, script) tuple
            if isinstance(agent_path, tuple):
                cmd = list(agent_path) + ["stop"]
            else:
                cmd = [agent_path, "stop"]
            
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            
            self.root.after(500, self._update_status)
            messagebox.showinfo("Success", "Agent stopped successfully!")
        
        except Exception as e:
            messagebox.showerror("Error", f"Failed to stop agent: {e}")
    
    def _try_pair(self, api_base, code):
        """Attempt to pair with the backend and return (api_key, server_device_id) or (None, None)"""
        import urllib.request
        import urllib.error
        import uuid
        import platform
        
        url = api_base.rstrip('/') + '/agents/pair/claim/'
        
        # Get or create device_id
        device_id_file = os.path.join(APPDATA, 'TimeTracker', '.device_id')
        try:
            if os.path.exists(device_id_file):
                with open(device_id_file) as f:
                    device_id = f.read().strip()
            else:
                device_id = str(uuid.uuid4())
                os.makedirs(os.path.dirname(device_id_file), exist_ok=True)
                with open(device_id_file, 'w') as f:
                    f.write(device_id)
        except:
            device_id = str(uuid.uuid4())
        
        payload = {
            'code': code.strip().upper(),
            'hostname': platform.node(),
            'platform': 'Windows',
            'version': '1.0.0',
            'device_id': device_id
        }
        
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode(), method='POST')
            req.add_header('Content-Type', 'application/json')
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if data.get('ok') and data.get('api_key'):
                    return data.get('api_key'), data.get('device_id')
                return None, None
        except urllib.error.HTTPError as e:
            error_body = e.read().decode()
            try:
                error_data = json.loads(error_body)
                error_msg = error_data.get('error', 'Unknown error')
            except:
                error_msg = error_body
            messagebox.showerror('Pairing Failed', f'Could not pair device:\n{error_msg}\n\nPlease generate a new pairing code and try again.')
            return None, None
        except Exception as e:
            messagebox.showerror('Pairing Failed', f'Connection error:\n{e}')
            return None, None

    def _save_config(self):
        """Save configuration - handles pairing if needed"""
        try:
            api_base = self.api_url_var.get().strip().rstrip("/")
            api_key = self.api_key_var.get().strip()
            pair_code = self.pair_code_var.get().strip()
            
            # If pair_code provided and no api_key, attempt pairing now
            if pair_code and not api_key:
                api_key, server_device_id = self._try_pair(api_base, pair_code)
                if api_key:
                    self.api_key_var.set(api_key)
                    messagebox.showinfo("Pairing Successful", "Device paired successfully!")
                else:
                    return  # Error already shown by _try_pair
            
            config = {
                "api_base": api_base,
                "api_key": api_key,
                "poll_seconds": self.poll_var.get(),
                "min_dwell_seconds": self.dwell_var.get(),
                "verbose": self.verbose_var.get(),
            }
            
            # Save server_device_id if we just paired
            if pair_code and api_key:
                try:
                    config["server_device_id"] = server_device_id
                except:
                    pass
            
            save_config(config)
            messagebox.showinfo("Success", "Configuration saved!\n\nClick 'Start Agent' to begin tracking.")
        
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save configuration: {e}")
    
    def _open_logs(self):
        """Open logs folder"""
        log_dir = os.path.join(APPDATA, "TimeTracker", "logs")
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        try:
            os.startfile(log_dir)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open logs folder: {e}")
    
    def _test_system(self):
        """Test system dependencies"""
        try:
            # Look for test_system.py or TestSystem.exe
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
                test_exe = os.path.join(base_dir, "TestSystem.exe")
                if os.path.exists(test_exe):
                    subprocess.Popen([test_exe], creationflags=subprocess.CREATE_NEW_CONSOLE)
                    return
            
            test_py = os.path.join(os.path.dirname(__file__), "test_system.py")
            if os.path.exists(test_py):
                subprocess.Popen([sys.executable, test_py], creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                messagebox.showwarning("Not Found", "test_system.py not found")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to run test: {e}")
    
    def _show_help(self):
        """Show help information"""
        help_text = """TimeTracker Agent - Quick Help

1. First Time Setup:
   - Enter your API URL (or use default localhost)
   - Enter pairing code from web app
   - Click "Save Configuration"
   - Click "Start Agent"

2. Daily Use:
   - Agent runs in system tray (look for TT icon)
   - Right-click icon to switch clients
   - View today's time from tray menu

3. Troubleshooting:
   - Check "Test System" for diagnostics
   - View logs via "Open Logs Folder"
   - Ensure Python and pywin32 are installed

4. Configuration:
   - API URL: Backend server address
   - API Key: Obtained after pairing
   - Poll Seconds: How often to check windows (5s default)
   - Min Dwell: Minimum time in window to record (15s default)

For more help, see README.md"""
        
        messagebox.showinfo("Help", help_text)

def main():
    root = tk.Tk()
    app = ConfigGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()

