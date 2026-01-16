#!/usr/bin/env python3
"""
TimeTracker Configuration GUI - Modern Version

Beautiful, modern UI using CustomTkinter
"""

import os
import json
import subprocess
import sys
import webbrowser

try:
    import customtkinter as ctk
    from CTkMessagebox import CTkMessagebox
    MODERN_UI = True
except ImportError:
    MODERN_UI = False
    print("Install modern UI: pip install customtkinter CTkMessagebox")

# Fallback to standard tkinter
import tkinter as tk
from tkinter import messagebox

CONFIG_DIR = os.path.expanduser("~/.timetracker")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
APPDATA = os.environ.get("APPDATA", os.path.expanduser("~"))
PID_FILE = os.path.join(APPDATA, "TimeTracker", "agent.pid")

APP_VERSION = "1.0.0"
GITHUB_REPO = "druss16/timetracker-releases"

# Color scheme
COLORS = {
    "primary": "#3B82F6",      # Blue
    "primary_hover": "#2563EB",
    "success": "#10B981",      # Green
    "success_hover": "#059669",
    "danger": "#EF4444",       # Red
    "danger_hover": "#DC2626",
    "warning": "#F59E0B",      # Amber
    "bg_dark": "#1F2937",      # Dark gray
    "bg_card": "#374151",      # Card background
    "text": "#F9FAFB",         # Light text
    "text_muted": "#9CA3AF",   # Muted text
}


def get_agent_exe_path():
    """Get path to TimeTrackerAgent.exe"""
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(__file__)
    
    agent_exe = os.path.join(base_dir, "TimeTrackerAgent.exe")
    
    if not os.path.exists(agent_exe):
        agent_py = os.path.join(base_dir, "main.py")
        if os.path.exists(agent_py):
            return (sys.executable, agent_py)
    
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


class ModernConfigGUI:
    def __init__(self):
        # Setup CustomTkinter
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        
        self.root = ctk.CTk()
        self.root.title("TimeTracker")
        self.root.geometry("500x680")
        self.root.resizable(False, False)
        
        # Center window
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - 250
        y = (self.root.winfo_screenheight() // 2) - 340
        self.root.geometry(f"+{x}+{y}")
        
        self.config = load_config()
        
        self._setup_ui()
        self._update_status()
        self._start_auto_refresh()
        self._check_for_updates()
    
    def _setup_ui(self):
        # Main container with padding
        main_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=30, pady=20)
        
        # ===== Header =====
        header_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 20))
        
        # Logo/Title
        title_label = ctk.CTkLabel(
            header_frame, 
            text="⏱ TimeTracker",
            font=ctk.CTkFont(size=28, weight="bold")
        )
        title_label.pack(side="left")
        
        # Version badge
        version_label = ctk.CTkLabel(
            header_frame,
            text=f"v{APP_VERSION}",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_muted"]
        )
        version_label.pack(side="right", pady=10)
        
        # ===== Status Card =====
        status_card = ctk.CTkFrame(main_frame, corner_radius=12)
        status_card.pack(fill="x", pady=(0, 20))
        
        status_inner = ctk.CTkFrame(status_card, fg_color="transparent")
        status_inner.pack(fill="x", padx=20, pady=20)
        
        # Status indicator
        status_row = ctk.CTkFrame(status_inner, fg_color="transparent")
        status_row.pack(fill="x", pady=(0, 15))
        
        self.status_dot = ctk.CTkLabel(
            status_row,
            text="●",
            font=ctk.CTkFont(size=20),
            text_color=COLORS["danger"]
        )
        self.status_dot.pack(side="left")
        
        self.status_label = ctk.CTkLabel(
            status_row,
            text="Agent Stopped",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.status_label.pack(side="left", padx=(8, 0))
        
        # Control buttons
        btn_frame = ctk.CTkFrame(status_inner, fg_color="transparent")
        btn_frame.pack(fill="x")
        
        self.start_btn = ctk.CTkButton(
            btn_frame,
            text="▶  Start Agent",
            command=self._start_agent,
            fg_color=COLORS["success"],
            hover_color=COLORS["success_hover"],
            height=40,
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 5))
        
        self.stop_btn = ctk.CTkButton(
            btn_frame,
            text="■  Stop Agent",
            command=self._stop_agent,
            fg_color=COLORS["danger"],
            hover_color=COLORS["danger_hover"],
            height=40,
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.stop_btn.pack(side="left", expand=True, fill="x", padx=(5, 0))
        
        # ===== Configuration Card =====
        config_card = ctk.CTkFrame(main_frame, corner_radius=12)
        config_card.pack(fill="x", pady=(0, 20))
        
        config_inner = ctk.CTkFrame(config_card, fg_color="transparent")
        config_inner.pack(fill="x", padx=20, pady=20)
        
        config_title = ctk.CTkLabel(
            config_inner,
            text="Configuration",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        config_title.pack(anchor="w", pady=(0, 15))
        
        # Pairing Code (most important for new users)
        self._create_input_field(
            config_inner,
            "Pairing Code",
            "pair_code",
            placeholder="Enter 6-digit code from web app",
            help_text="Get this from Settings → Devices in the web app"
        )
        
        # API URL (collapsed by default for simplicity)
        self.show_advanced = ctk.BooleanVar(value=False)
        
        advanced_toggle = ctk.CTkButton(
            config_inner,
            text="▼ Advanced Settings",
            command=self._toggle_advanced,
            fg_color="transparent",
            hover_color=COLORS["bg_card"],
            text_color=COLORS["text_muted"],
            anchor="w",
            height=30
        )
        advanced_toggle.pack(fill="x", pady=(10, 0))
        
        self.advanced_frame = ctk.CTkFrame(config_inner, fg_color="transparent")
        # Hidden by default
        
        # API URL
        self._create_input_field(
            self.advanced_frame,
            "API URL",
            "api_url",
            default="https://timetracker-api-k375.onrender.com/api"
        )
        
        # API Key (read-only, populated after pairing)
        self._create_input_field(
            self.advanced_frame,
            "API Key",
            "api_key",
            show="*",
            help_text="Auto-populated after pairing"
        )
        
        # Save button
        save_btn = ctk.CTkButton(
            config_inner,
            text="💾  Save & Pair",
            command=self._save_config,
            fg_color=COLORS["primary"],
            hover_color=COLORS["primary_hover"],
            height=45,
            font=ctk.CTkFont(size=15, weight="bold")
        )
        save_btn.pack(fill="x", pady=(20, 0))
        
        # ===== Quick Actions =====
        actions_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        actions_frame.pack(fill="x")
        
        logs_btn = ctk.CTkButton(
            actions_frame,
            text="📁 Logs",
            command=self._open_logs,
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_dark"],
            width=100,
            height=35
        )
        logs_btn.pack(side="left", padx=(0, 10))
        
        help_btn = ctk.CTkButton(
            actions_frame,
            text="❓ Help",
            command=self._show_help,
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_dark"],
            width=100,
            height=35
        )
        help_btn.pack(side="left")
        
        # Update available label (hidden by default)
        self.update_label = ctk.CTkLabel(
            actions_frame,
            text="🔄 Update available!",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["warning"],
            cursor="hand2"
        )
        self.update_label.pack(side="right")
        self.update_label.pack_forget()  # Hide initially
    
    def _create_input_field(self, parent, label, var_name, default="", placeholder="", help_text="", show=None):
        """Create a styled input field"""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=(0, 10))
        
        lbl = ctk.CTkLabel(
            frame,
            text=label,
            font=ctk.CTkFont(size=13),
            anchor="w"
        )
        lbl.pack(fill="x")
        
        var = ctk.StringVar(value=self.config.get(var_name.replace("_var", ""), default))
        setattr(self, f"{var_name}_var", var)
        
        entry = ctk.CTkEntry(
            frame,
            textvariable=var,
            placeholder_text=placeholder,
            height=40,
            show=show if show else ""
        )
        entry.pack(fill="x", pady=(5, 0))
        
        if help_text:
            help_lbl = ctk.CTkLabel(
                frame,
                text=help_text,
                font=ctk.CTkFont(size=11),
                text_color=COLORS["text_muted"],
                anchor="w"
            )
            help_lbl.pack(fill="x", pady=(2, 0))
    
    def _toggle_advanced(self):
        if self.show_advanced.get():
            self.advanced_frame.pack_forget()
            self.show_advanced.set(False)
        else:
            self.advanced_frame.pack(fill="x", pady=(10, 0))
            self.show_advanced.set(True)
    
    def _start_auto_refresh(self):
        """Auto-refresh status every 3 seconds"""
        self._update_status()
        self.root.after(3000, self._start_auto_refresh)
    
    def _update_status(self):
        """Update agent status display"""
        if is_agent_running():
            self.status_dot.configure(text_color=COLORS["success"])
            self.status_label.configure(text="Agent Running")
            self.start_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal")
        else:
            self.status_dot.configure(text_color=COLORS["danger"])
            self.status_label.configure(text="Agent Stopped")
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
    
    def _start_agent(self):
        """Start the agent"""
        try:
            agent_path = get_agent_exe_path()
            
            if isinstance(agent_path, tuple):
                cmd = list(agent_path) + ["start"]
            else:
                cmd = [agent_path, "start"]
            
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            
            subprocess.Popen(
                cmd,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )
            
            self.root.after(1000, self._update_status)
            self._show_toast("Success", "Agent started successfully!", "success")
        
        except Exception as e:
            self._show_toast("Error", f"Failed to start agent: {e}", "error")
    
    def _stop_agent(self):
        """Stop the agent"""
        try:
            agent_path = get_agent_exe_path()
            
            if isinstance(agent_path, tuple):
                cmd = list(agent_path) + ["stop"]
            else:
                cmd = [agent_path, "stop"]
            
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            
            self.root.after(500, self._update_status)
            self._show_toast("Success", "Agent stopped successfully!", "success")
        
        except Exception as e:
            self._show_toast("Error", f"Failed to stop agent: {e}", "error")
    
    def _try_pair(self, api_base, code):
        """Attempt to pair with the backend"""
        import urllib.request
        import urllib.error
        import uuid
        import platform
        
        url = api_base.rstrip('/') + '/agents/pair/claim/'
        
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
            'version': APP_VERSION,
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
            self._show_toast("Pairing Failed", error_msg, "error")
            return None, None
        except Exception as e:
            self._show_toast("Connection Error", str(e), "error")
            return None, None
    
    def _save_config(self):
        """Save configuration - handles pairing if needed"""
        try:
            api_base = getattr(self, 'api_url_var', ctk.StringVar(value="https://timetracker-api-k375.onrender.com/api")).get().strip().rstrip("/")
            api_key = getattr(self, 'api_key_var', ctk.StringVar()).get().strip()
            pair_code = self.pair_code_var.get().strip()
            
            if pair_code and not api_key:
                api_key, server_device_id = self._try_pair(api_base, pair_code)
                if api_key:
                    if hasattr(self, 'api_key_var'):
                        self.api_key_var.set(api_key)
                    self._show_toast("Paired!", "Device paired successfully. Click Start Agent to begin.", "success")
                else:
                    return
            
            config = {
                "api_base": api_base,
                "api_key": api_key,
            }
            
            if pair_code and api_key:
                try:
                    config["server_device_id"] = server_device_id
                except:
                    pass
            
            save_config(config)
            self.config = config
            
            if not pair_code:
                self._show_toast("Saved", "Configuration saved!", "success")
        
        except Exception as e:
            self._show_toast("Error", f"Failed to save: {e}", "error")
    
    def _open_logs(self):
        """Open logs folder"""
        log_dir = os.path.join(APPDATA, "TimeTracker", "logs")
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        
        try:
            os.startfile(log_dir)
        except Exception as e:
            self._show_toast("Error", f"Failed to open logs: {e}", "error")
    
    def _show_help(self):
        """Show help dialog"""
        help_window = ctk.CTkToplevel(self.root)
        help_window.title("Help")
        help_window.geometry("450x400")
        help_window.transient(self.root)
        help_window.grab_set()
        
        # Center
        help_window.update_idletasks()
        x = self.root.winfo_x() + 25
        y = self.root.winfo_y() + 100
        help_window.geometry(f"+{x}+{y}")
        
        content = ctk.CTkFrame(help_window, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=20)
        
        title = ctk.CTkLabel(
            content,
            text="Getting Started",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        title.pack(anchor="w", pady=(0, 15))
        
        steps = [
            ("1️⃣", "Get your pairing code from the web app\n    Settings → Devices → Generate Code"),
            ("2️⃣", "Enter the code above and click Save & Pair"),
            ("3️⃣", "Click Start Agent to begin tracking"),
            ("4️⃣", "Look for the TT icon in your system tray"),
        ]
        
        for emoji, text in steps:
            step_frame = ctk.CTkFrame(content, fg_color="transparent")
            step_frame.pack(fill="x", pady=5)
            
            ctk.CTkLabel(
                step_frame,
                text=emoji,
                font=ctk.CTkFont(size=16)
            ).pack(side="left", padx=(0, 10))
            
            ctk.CTkLabel(
                step_frame,
                text=text,
                font=ctk.CTkFont(size=13),
                justify="left",
                anchor="w"
            ).pack(side="left", fill="x", expand=True)
        
        close_btn = ctk.CTkButton(
            content,
            text="Got it!",
            command=help_window.destroy,
            height=40
        )
        close_btn.pack(fill="x", pady=(20, 0))
    
    def _show_toast(self, title, message, type="info"):
        """Show a toast notification"""
        try:
            from CTkMessagebox import CTkMessagebox
            icon = "check" if type == "success" else "cancel" if type == "error" else "info"
            CTkMessagebox(title=title, message=message, icon=icon)
        except:
            messagebox.showinfo(title, message)
    
    def _check_for_updates(self):
        """Check GitHub for newer release"""
        def check():
            try:
                import urllib.request
                url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
                req = urllib.request.Request(url)
                req.add_header("Accept", "application/vnd.github.v3+json")
                
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read())
                    latest = data["tag_name"].lstrip("v")
                    
                    if latest > APP_VERSION:
                        self.update_label.pack(side="right")
                        self.update_label.bind("<Button-1>", lambda e: webbrowser.open(data["html_url"]))
            except Exception:
                pass
        
        import threading
        threading.Thread(target=check, daemon=True).start()
    
    def run(self):
        self.root.mainloop()


def main():
    if MODERN_UI:
        app = ModernConfigGUI()
        app.run()
    else:
        # Fallback to original
        print("CustomTkinter not installed. Run: pip install customtkinter CTkMessagebox")
        from gui import ConfigGUI
        root = tk.Tk()
        app = ConfigGUI(root)
        root.mainloop()


if __name__ == "__main__":
    main()