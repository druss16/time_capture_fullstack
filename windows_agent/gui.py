#!/usr/bin/env python3
"""
TimeTracker Configuration GUI - Cross-Platform Version

Beautiful, modern UI using CustomTkinter for Windows and macOS
"""

import os
import json
import subprocess
import sys
import webbrowser
import platform
import uuid

# Platform detection
IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"
PLATFORM_NAME = "Windows" if IS_WINDOWS else "macOS" if IS_MACOS else "Linux"

# Paths - MUST match main.py exactly!
# Config is always in ~/.timetracker/ (same as main.py)
CONFIG_DIR = os.path.expanduser("~/.timetracker")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# Platform-specific paths for other files
if IS_WINDOWS:
    APPDATA = os.environ.get("APPDATA", os.path.expanduser("~"))
    LOG_DIR = os.path.join(APPDATA, "TimeTracker", "Logs")
    PID_FILE = os.path.join(APPDATA, "TimeTracker", "agent.pid")
    PLIST = None  # Not used on Windows
else:
    LOG_DIR = os.path.expanduser("~/Library/Logs/TimeTracker")
    PID_FILE = os.path.expanduser("~/.timetracker/agent.pid")
    PLIST = os.path.expanduser("~/Library/LaunchAgents/com.mavops.timetracker.plist")

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

# Try to import version from auto-generated file
try:
    from version import APP_VERSION
except ImportError:
    APP_VERSION = "dev"

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

def get_agent_script_path():
    """Get path to agent - either main.py (dev) or TimeTrackerAgent.exe (packaged)"""
    if getattr(sys, 'frozen', False):
        # Running as packaged exe
        base_dir = os.path.dirname(sys.executable)
        
        # Look for TimeTrackerAgent.exe first (packaged)
        agent_exe = os.path.join(base_dir, "TimeTrackerAgent.exe")
        if os.path.exists(agent_exe):
            return agent_exe
    else:
        # Running as script
        base_dir = os.path.dirname(__file__)
    
    # Look for main.py (development)
    agent_py = os.path.join(base_dir, "main.py")
    if os.path.exists(agent_py):
        return agent_py
    
    # Try parent directory
    parent_dir = os.path.dirname(base_dir)
    agent_py = os.path.join(parent_dir, "main.py")
    if os.path.exists(agent_py):
        return agent_py
    
    return None


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


def launchctl(args):
    """Run launchctl command (macOS only)"""
    if IS_WINDOWS:
        return 1, "", "Not supported on Windows"
    try:
        out = subprocess.run(["/bin/launchctl"] + args, capture_output=True, text=True)
        return out.returncode, out.stdout, out.stderr
    except Exception as e:
        return 1, "", str(e)


def is_agent_running():
    """Check if agent is running - cross-platform"""
    if IS_WINDOWS:
        # Windows: First check the PID file (most reliable)
        pid_files_to_check = [
            PID_FILE,  # %APPDATA%\TimeTracker\agent.pid
            os.path.expanduser("~/.timetracker/agent.pid"),  # Alternative location
        ]
        
        for pid_file in pid_files_to_check:
            if os.path.exists(pid_file):
                print(f"[GUI] Found PID file: {pid_file}")
                try:
                    with open(pid_file) as f:
                        pid = int(f.read().strip())
                    print(f"[GUI] PID from file: {pid}")
                    
                    # Verify the process is actually running using psutil
                    try:
                        import psutil
                        proc = psutil.Process(pid)
                        # Check if it's a python process (not something else that reused the PID)
                        if proc.is_running() and 'python' in proc.name().lower():
                            print(f"[GUI] Process {pid} is running (psutil)")
                            return True
                    except ImportError:
                        # Fallback: use ctypes if psutil not available
                        import ctypes
                        kernel32 = ctypes.windll.kernel32
                        SYNCHRONIZE = 0x00100000
                        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
                        if handle:
                            kernel32.CloseHandle(handle)
                            print(f"[GUI] Process {pid} is running (ctypes)")
                            return True
                    except Exception as e:
                        print(f"[GUI] Error checking PID {pid}: {e}")
                except (OSError, ValueError, Exception) as e:
                    print(f"[GUI] Error reading PID file: {e}")
        
        # Fallback: scan all processes for main.py
        print("[GUI] No valid PID file, scanning processes...")
        try:
            import psutil
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    name = (proc.info.get('name') or '').lower()
                    if 'python' not in name:
                        continue
                    
                    cmdline = proc.info.get('cmdline') or []
                    cmdline_str = ' '.join(str(arg) for arg in cmdline).lower()
                    
                    # Look for main.py but exclude gui.py
                    if 'main.py' in cmdline_str and 'gui.py' not in cmdline_str:
                        print(f"[GUI] Found agent process: PID {proc.info['pid']}")
                        return True
                    # Also check for compiled exe
                    if 'timetracker' in cmdline_str and 'gui' not in cmdline_str:
                        print(f"[GUI] Found timetracker process: PID {proc.info['pid']}")
                        return True
                        
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
        except ImportError:
            print("[WARN] psutil not installed - install with: pip install psutil")
        
        print("[GUI] Agent not detected")
        return False
    
    else:
        # macOS: Check launchctl first
        code, _, _ = launchctl(["print", f"gui/{os.getuid()}/com.mavops.timetracker"])
        if code == 0:
            return True
        
        # Fallback to PID file check
        if os.path.exists(PID_FILE):
            try:
                with open(PID_FILE) as f:
                    pid = int(f.read().strip())
                # Check if process exists
                os.kill(pid, 0)
                return True
            except (OSError, ValueError):
                pass
        
        return False


class ModernConfigGUI:
    def __init__(self):
        # Setup CustomTkinter
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        
        self.root = ctk.CTk()
        self.root.title("TimeTracker")
        self.root.geometry("500x620")
        self.root.resizable(False, True)  # Allow vertical resize
        
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
        main_frame.pack(fill="both", expand=True, padx=24, pady=16)
        
        # ===== Header =====
        header_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 15))
        
        # Logo/Title
        title_label = ctk.CTkLabel(
            header_frame, 
            text="⏱ TimeTracker",
            font=ctk.CTkFont(size=24, weight="bold")
        )
        title_label.pack(side="left")
        
        # Version badge
        version_label = ctk.CTkLabel(
            header_frame,
            text=f"v{APP_VERSION}",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_muted"]
        )
        version_label.pack(side="right", pady=8)
        
        # Platform badge
        os_label = ctk.CTkLabel(
            header_frame,
            text=PLATFORM_NAME,
            font=ctk.CTkFont(size=10),
            text_color=COLORS["text_muted"],
            fg_color=COLORS["bg_card"],
            corner_radius=4,
            padx=6,
            pady=2
        )
        os_label.pack(side="right", padx=(0, 8), pady=8)
        
        # ===== Status Card =====
        status_card = ctk.CTkFrame(main_frame, corner_radius=10)
        status_card.pack(fill="x", pady=(0, 15))
        
        status_inner = ctk.CTkFrame(status_card, fg_color="transparent")
        status_inner.pack(fill="x", padx=16, pady=16)
        
        # Status indicator
        status_row = ctk.CTkFrame(status_inner, fg_color="transparent")
        status_row.pack(fill="x", pady=(0, 12))
        
        self.status_dot = ctk.CTkLabel(
            status_row,
            text="●",
            font=ctk.CTkFont(size=16),
            text_color=COLORS["danger"]
        )
        self.status_dot.pack(side="left")
        
        self.status_label = ctk.CTkLabel(
            status_row,
            text="Agent Stopped",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.status_label.pack(side="left", padx=(6, 0))
        
        # Control buttons
        btn_frame = ctk.CTkFrame(status_inner, fg_color="transparent")
        btn_frame.pack(fill="x")
        
        self.start_btn = ctk.CTkButton(
            btn_frame,
            text="▶  Start Agent",
            command=self._start_agent,
            fg_color=COLORS["success"],
            hover_color=COLORS["success_hover"],
            height=36,
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 5))
        
        self.stop_btn = ctk.CTkButton(
            btn_frame,
            text="■  Stop Agent",
            command=self._stop_agent,
            fg_color=COLORS["danger"],
            hover_color=COLORS["danger_hover"],
            height=36,
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.stop_btn.pack(side="left", expand=True, fill="x", padx=(5, 0))
        
        # ===== Configuration Card =====
        config_card = ctk.CTkFrame(main_frame, corner_radius=10)
        config_card.pack(fill="x", pady=(0, 15))
        
        config_inner = ctk.CTkFrame(config_card, fg_color="transparent")
        config_inner.pack(fill="x", padx=16, pady=16)
        
        config_title = ctk.CTkLabel(
            config_inner,
            text="Configuration",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        config_title.pack(anchor="w", pady=(0, 12))
        
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
        
        self.advanced_toggle_btn = ctk.CTkButton(
            config_inner,
            text="▶ Advanced Settings",
            command=self._toggle_advanced,
            fg_color="transparent",
            hover_color=COLORS["bg_card"],
            text_color=COLORS["text_muted"],
            anchor="w",
            height=30
        )
        self.advanced_toggle_btn.pack(fill="x", pady=(10, 0))
        
        self.advanced_frame = ctk.CTkFrame(config_inner, fg_color="transparent")
        # Don't pack yet - hidden by default
        
        # API URL - create inside advanced_frame
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
        
        # Reset Device button
        reset_btn = ctk.CTkButton(
            self.advanced_frame,
            text="🔄 Reset Device ID",
            command=self._reset_device,
            fg_color=COLORS["danger"],
            hover_color=COLORS["danger_hover"],
            height=32,
            font=ctk.CTkFont(size=11)
        )
        reset_btn.pack(fill="x", pady=(12, 0))
        
        reset_help = ctk.CTkLabel(
            self.advanced_frame,
            text="Use if you see 'device belongs to another user' error",
            font=ctk.CTkFont(size=10),
            text_color=COLORS["text_muted"],
            anchor="w"
        )
        reset_help.pack(fill="x", pady=(2, 0))
        
        # Save button
        save_btn = ctk.CTkButton(
            config_inner,
            text="💾  Save & Pair",
            command=self._save_config,
            fg_color=COLORS["primary"],
            hover_color=COLORS["primary_hover"],
            height=40,
            font=ctk.CTkFont(size=13, weight="bold")
        )
        save_btn.pack(fill="x", pady=(15, 0))
        
        # ===== Quick Actions =====
        actions_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        actions_frame.pack(fill="x")
        
        logs_btn = ctk.CTkButton(
            actions_frame,
            text="📁 Logs",
            command=self._open_logs,
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_dark"],
            width=80,
            height=30
        )
        logs_btn.pack(side="left", padx=(0, 8))
        
        help_btn = ctk.CTkButton(
            actions_frame,
            text="❓ Help",
            command=self._show_help,
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_dark"],
            width=80,
            height=30
        )
        help_btn.pack(side="left")
        
        # Update available label (hidden by default)
        self.update_label = ctk.CTkLabel(
            actions_frame,
            text="🔄 Update available!",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["warning"],
            cursor="hand2"
        )
        self.update_label.pack(side="right")
        self.update_label.pack_forget()  # Hide initially

    def _show_paired_success(self):
        """Show success message pointing to system tray, then close GUI"""
        try:
            from CTkMessagebox import CTkMessagebox
            CTkMessagebox(
                title="Device Paired!",
                message=(
                    "TimeTracker is now running!\n\n"
                    "Look for the ⏱ icon in your system tray\n"
                    "(bottom-right corner of your taskbar).\n\n"
                    "Right-click it to switch clients."
                ),
                icon="check",
                option_1="Got it!"
            )
        except Exception:
            messagebox.showinfo(
                "Device Paired!",
                "TimeTracker is now running!\n\n"
                "Look for the icon in your system tray (bottom-right corner).\n"
                "Right-click it to switch clients."
            )
        self.root.destroy()
    
    def _create_input_field(self, parent, label, var_name, default="", placeholder="", help_text="", show=None):
        """Create a styled input field"""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=(0, 8))
        
        lbl = ctk.CTkLabel(
            frame,
            text=label,
            font=ctk.CTkFont(size=11),
            anchor="w"
        )
        lbl.pack(fill="x")
        
        # Get value from config, handling both old and new key names
        config_key = var_name.replace("_var", "")
        value = self.config.get(config_key, "")
        if not value and config_key == "api_url":
            value = self.config.get("api_base", default)
        if not value:
            value = default
            
        var = ctk.StringVar(value=value)
        setattr(self, f"{var_name}_var", var)
        
        entry = ctk.CTkEntry(
            frame,
            textvariable=var,
            placeholder_text=placeholder,
            height=34,
            font=ctk.CTkFont(size=11),
            show=show if show else ""
        )
        entry.pack(fill="x", pady=(4, 0))
        
        if help_text:
            help_lbl = ctk.CTkLabel(
                frame,
                text=help_text,
                font=ctk.CTkFont(size=10),
                text_color=COLORS["text_muted"],
                anchor="w"
            )
            help_lbl.pack(fill="x", pady=(2, 0))
    
    def _toggle_advanced(self):
        print(f"[GUI] Toggle advanced - current state: {self.show_advanced.get()}")
        if self.show_advanced.get():
            # Currently shown, hide it
            self.advanced_frame.pack_forget()
            self.show_advanced.set(False)
            self.advanced_toggle_btn.configure(text="▶ Advanced Settings")
            self.root.geometry("500x620")  # Shrink window
            print("[GUI] Advanced settings hidden")
        else:
            # Currently hidden, show it
            self.advanced_frame.pack(fill="x", pady=(8, 0))
            self.show_advanced.set(True)
            self.advanced_toggle_btn.configure(text="▼ Advanced Settings")
            self.root.geometry("500x780")  # Expand window
            print("[GUI] Advanced settings shown")
    
    def _start_auto_refresh(self):
        """Auto-refresh status every 3 seconds"""
        self._update_status()
        self.root.after(3000, self._start_auto_refresh)
    
    def _update_status(self):
        """Update agent status display"""
        running = is_agent_running()
        print(f"[GUI] Status check - agent running: {running}")
        
        if running:
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
        """Start the agent - cross-platform"""
        try:
            if IS_WINDOWS:
                agent_path = get_agent_script_path()
                print(f"[GUI] Agent path: {agent_path}")
                
                if not agent_path:
                    self._show_toast("Error", "Agent not found", "error")
                    return
                
                if not os.path.exists(agent_path):
                    self._show_toast("Error", f"Agent not found at: {agent_path}", "error")
                    return
                
                print(f"[GUI] Starting agent: {agent_path}")
                
                # Check if it's an exe or py file
                if agent_path.endswith('.exe'):
                    # Run exe directly
                    try:
                        CREATE_NEW_PROCESS_GROUP = 0x00000200
                        DETACHED_PROCESS = 0x00000008
                        
                        proc = subprocess.Popen(
                            [agent_path, "start"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL,
                            creationflags=CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS,
                        )
                        print(f"[GUI] Agent started with PID: {proc.pid}")
                        self.root.after(2500, self._update_status)
                        self._show_toast("Success", "Agent started successfully!", "success")
                        return
                    except Exception as e:
                        print(f"[GUI] Failed to start exe: {e}")
                        self._show_toast("Error", f"Failed to start agent: {e}", "error")
                else:
                    # Run Python script
                    try:
                        cmd = f'start /b "" "{sys.executable}" "{agent_path}" start'
                        print(f"[GUI] Running: {cmd}")
                        subprocess.Popen(cmd, shell=True)
                        
                        self.root.after(2500, self._update_status)
                        self._show_toast("Success", "Agent started successfully!", "success")
                        return
                    except Exception as e:
                        print(f"[GUI] Failed to start script: {e}")
                        self._show_toast("Error", f"Failed to start agent: {e}", "error")
            
            else:
                # macOS: Try launchctl first
                if PLIST and os.path.exists(PLIST):
                    code, _, stderr = launchctl(["load", "-w", PLIST])
                    if code == 0:
                        self.root.after(1000, self._update_status)
                        self._show_toast("Success", "Agent started successfully!", "success")
                        return
                
                # Fallback to direct script execution
                agent_path = get_agent_script_path()
                if agent_path:
                    subprocess.Popen(
                        [sys.executable, agent_path, "start"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True
                    )
                    self.root.after(1000, self._update_status)
                    self._show_toast("Success", "Agent started successfully!", "success")
                else:
                    self._show_toast("Error", "Agent script not found", "error")
        
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._show_toast("Error", f"Failed to start agent: {e}", "error")
    
    def _stop_agent(self):
        """Stop the agent - cross-platform"""
        try:
            if IS_WINDOWS:
                # Windows: Find and terminate process
                try:
                    import psutil
                    for proc in psutil.process_iter(['name', 'cmdline', 'pid']):
                        try:
                            cmdline = proc.info.get('cmdline') or []
                            for arg in cmdline:
                                if arg and ('main.py' in arg or 'timetracker' in arg.lower()):
                                    if 'gui.py' not in str(cmdline):
                                        proc.terminate()
                                        print(f"[GUI] Terminated process {proc.info['pid']}")
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                except ImportError:
                    pass
                
                # Also try PID file
                if os.path.exists(PID_FILE):
                    try:
                        with open(PID_FILE) as f:
                            pid = int(f.read().strip())
                        import signal
                        os.kill(pid, signal.SIGTERM)
                    except Exception:
                        pass
                    try:
                        os.remove(PID_FILE)
                    except Exception:
                        pass
            
            else:
                # macOS: Try launchctl first
                if PLIST and os.path.exists(PLIST):
                    launchctl(["unload", PLIST])
                
                # Also try to stop via PID
                if os.path.exists(PID_FILE):
                    try:
                        with open(PID_FILE) as f:
                            pid = int(f.read().strip())
                        os.kill(pid, 15)  # SIGTERM
                    except Exception:
                        pass
            
            self.root.after(500, self._update_status)
            self._show_toast("Success", "Agent stopped successfully!", "success")
        
        except Exception as e:
            self._show_toast("Error", f"Failed to stop agent: {e}", "error")
    
    def _stop_agent_silent(self):
        """Stop the agent without showing toast (used during re-pair)"""
        try:
            if IS_WINDOWS:
                try:
                    import psutil
                    for proc in psutil.process_iter(['name', 'cmdline', 'pid']):
                        try:
                            cmdline = proc.info.get('cmdline') or []
                            for arg in cmdline:
                                if arg and ('main.py' in arg or 'timetracker' in arg.lower()):
                                    if 'gui.py' not in str(cmdline):
                                        proc.terminate()
                                        print(f"[GUI] Terminated agent process {proc.info['pid']}")
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                except ImportError:
                    pass
                
                # Also clean up PID files
                for pid_file in [PID_FILE, os.path.expanduser("~/.timetracker/agent.pid")]:
                    if os.path.exists(pid_file):
                        try:
                            os.remove(pid_file)
                        except:
                            pass
            else:
                # macOS
                if PLIST and os.path.exists(PLIST):
                    launchctl(["unload", PLIST])
                
                if os.path.exists(PID_FILE):
                    try:
                        with open(PID_FILE) as f:
                            pid = int(f.read().strip())
                        os.kill(pid, 15)
                    except:
                        pass
            
            # Wait a moment for process to stop
            import time
            time.sleep(1)
            self._update_status()
            
        except Exception as e:
            print(f"[GUI] Error stopping agent: {e}")
    
    def _reset_device(self):
        """Reset device ID to allow fresh pairing"""
        try:
            from CTkMessagebox import CTkMessagebox
            confirm = CTkMessagebox(
                title="Reset Device?",
                message="This will clear your device pairing and allow you to pair again.\n\nContinue?",
                icon="warning",
                option_1="Cancel",
                option_2="Reset"
            )
            
            if confirm.get() != "Reset":
                return
            
            # Stop agent if running
            if is_agent_running():
                self._stop_agent_silent()
            
            # Delete device ID file
            device_id_file = os.path.join(CONFIG_DIR, '.device_id')
            if os.path.exists(device_id_file):
                os.remove(device_id_file)
            
            # Clear config
            self.config = {}
            save_config(self.config)
            
            # Clear the UI fields
            if hasattr(self, 'api_key_var'):
                self.api_key_var.set("")
            if hasattr(self, 'pair_code_var'):
                self.pair_code_var.set("")
            
            self._show_toast("Reset Complete", "Device ID cleared. Enter a new pairing code.", "success")
            
        except Exception as e:
            self._show_toast("Error", f"Failed to reset: {e}", "error")
    
    def _try_pair(self, api_base, code):
        """Attempt to pair with the backend"""
        import urllib.request
        import urllib.error
        
        url = api_base.rstrip('/') + '/agents/pair/claim/'
        
        device_id_file = os.path.join(CONFIG_DIR, '.device_id')
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
            'platform': PLATFORM_NAME,
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
                
                # Provide helpful message for common errors
                if 'device_belongs_to_another_user' in error_msg:
                    self._show_toast(
                        "Device Already Paired", 
                        "This device was previously paired. Go to Advanced Settings and click 'Reset Device ID', then try again.",
                        "warning"
                    )
                else:
                    self._show_toast("Pairing Failed", error_msg, "error")
            except:
                self._show_toast("Pairing Failed", error_body, "error")
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
            
            print(f"[GUI] Save config - api_base: {api_base}")
            print(f"[GUI] Save config - api_key exists: {bool(api_key)}")
            print(f"[GUI] Save config - pair_code: {pair_code}")
            
            server_device_id = self.config.get("server_device_id")
            
            # If pairing code provided, stop running agent first so it picks up new config
            if pair_code:
                if is_agent_running():
                    print("[GUI] Stopping running agent before re-pairing...")
                    self._stop_agent_silent()
                
                print(f"[GUI] Attempting to pair with code: {pair_code}")
                new_api_key, new_device_id = self._try_pair(api_base, pair_code)
                if new_api_key:
                    api_key = new_api_key
                    server_device_id = new_device_id
                    if hasattr(self, 'api_key_var'):
                        self.api_key_var.set(api_key)
                    # Clear the pairing code field after successful pairing
                    self.pair_code_var.set("")

                    # Save config immediately so agent can read it
                    config = {
                        "api_base": api_base,
                        "api_key": api_key,
                    }
                    if server_device_id:
                        config["server_device_id"] = server_device_id
                    save_config(config)
                    self.config = config
                    
                    # Auto-start the agent
                    self._start_agent()
                    
                    # Show success pointing to system tray, then close
                    self._show_paired_success()
                    return
                else:
                    return
            
            config = {
                "api_base": api_base,
                "api_key": api_key,
            }
            
            if server_device_id:
                config["server_device_id"] = server_device_id
            
            print(f"[GUI] Saving config: {config}")
            save_config(config)
            self.config = config
            
            if not pair_code:
                self._show_toast("Saved", "Configuration saved!", "success")
        
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._show_toast("Error", f"Failed to save: {e}", "error")
    
    def _open_logs(self):
        """Open logs folder - cross-platform"""
        if not os.path.exists(LOG_DIR):
            os.makedirs(LOG_DIR, exist_ok=True)
        
        try:
            if IS_WINDOWS:
                os.startfile(LOG_DIR)
            elif IS_MACOS:
                subprocess.run(["open", LOG_DIR])
            else:
                subprocess.run(["xdg-open", LOG_DIR])
        except Exception as e:
            self._show_toast("Error", f"Failed to open logs: {e}", "error")
    
    def _show_help(self):
        """Show help dialog"""
        help_window = ctk.CTkToplevel(self.root)
        help_window.title("Help")
        help_window.geometry("420x360")
        help_window.transient(self.root)
        help_window.grab_set()
        
        # Center
        help_window.update_idletasks()
        x = self.root.winfo_x() + 40
        y = self.root.winfo_y() + 100
        help_window.geometry(f"+{x}+{y}")
        
        content = ctk.CTkFrame(help_window, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=16, pady=16)
        
        title = ctk.CTkLabel(
            content,
            text="Getting Started",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        title.pack(anchor="w", pady=(0, 12))
        
        # Platform-specific instructions
        if IS_WINDOWS:
            tray_text = "Look for the TT icon in your system tray"
        else:
            tray_text = "Look for the TT icon in your menu bar"
        
        steps = [
            ("1️⃣", "Get your pairing code from the web app\n    Settings → Devices → Generate Code"),
            ("2️⃣", "Enter the code above and click Save & Pair"),
            ("3️⃣", "Click Start Agent to begin tracking"),
            ("4️⃣", tray_text),
        ]
        
        for emoji, text in steps:
            step_frame = ctk.CTkFrame(content, fg_color="transparent")
            step_frame.pack(fill="x", pady=4)
            
            ctk.CTkLabel(
                step_frame,
                text=emoji,
                font=ctk.CTkFont(size=14)
            ).pack(side="left", padx=(0, 8))
            
            ctk.CTkLabel(
                step_frame,
                text=text,
                font=ctk.CTkFont(size=11),
                justify="left",
                anchor="w"
            ).pack(side="left", fill="x", expand=True)
        
        close_btn = ctk.CTkButton(
            content,
            text="Got it!",
            command=help_window.destroy,
            height=36
        )
        close_btn.pack(fill="x", pady=(16, 0))
    
    def _show_toast(self, title, message, type="info"):
        """Show a toast notification"""
        try:
            from CTkMessagebox import CTkMessagebox
            icon = "check" if type == "success" else "cancel" if type == "error" else "warning" if type == "warning" else "info"
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
        # Fallback to original tkinter version
        print("CustomTkinter not installed. Run: pip install customtkinter CTkMessagebox")
        if IS_WINDOWS:
            print("Also install: pip install psutil")
        sys.exit(1)


if __name__ == "__main__":
    main()