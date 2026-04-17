#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TimeTracker macOS Menu Bar GUI - Professional Edition
Features:
- Native macOS menu bar icon
- Sharp, professional UI with refined aesthetics
- Searchable client picker with usage-based ranking
- AI client prompts with confidence indicators
- Today's time viewer with detailed breakdown
- Username display and re-pairing support
"""
import os
import sys
import json
import threading
import multiprocessing
import time as _time
from datetime import datetime
from typing import Optional, List, Dict, Callable


# Required for macOS multiprocessing with frozen apps
if __name__ == '__main__':
    multiprocessing.freeze_support()

# Set spawn method for macOS (required for GUI processes)
try:
    multiprocessing.set_start_method('spawn', force=True)
except RuntimeError:
    pass  # Already set

# Modern UI for dialogs
try:
    import customtkinter as ctk
    MODERN_UI = True
except ImportError:
    MODERN_UI = False
    import tkinter as tk
    from tkinter import ttk, messagebox

# macOS native menu bar
# CRITICAL: Only import rumps/AppKit in the main process.
# Subprocesses (spawn) re-import this module, and rumps/AppKit init
# corrupts NSApplication, causing Tk 9.0 to crash on macOSVersion selector.
# macOS native menu bar
# CRITICAL: Only import rumps/AppKit in the main process.
# Subprocesses (spawn) re-import this module, and rumps/AppKit init
# corrupts NSApplication, causing Tk 9.0 to crash on macOSVersion selector.
# Using env var because multiprocessing.parent_process() is unreliable
# at module import time during spawn bootstrap.
_is_subprocess = os.environ.get('_TT_SUBPROCESS') == '1'

RUMPS_AVAILABLE = False
APPKIT_AVAILABLE = False

if not _is_subprocess:
    try:
        import rumps
        RUMPS_AVAILABLE = True
    except ImportError:
        print("Warning: rumps not available. Install with: pip install rumps")

    if not RUMPS_AVAILABLE:
        try:
            import objc
            from Foundation import NSObject, NSTimer
            from AppKit import (
                NSApplication, NSApp, NSStatusBar, NSMenu, NSMenuItem,
                NSApplicationActivationPolicyAccessory, NSVariableStatusItemLength
            )
            APPKIT_AVAILABLE = True
        except ImportError:
            print("Warning: PyObjC not available. Install with: pip install pyobjc")

    # Mark environment so all spawn children skip rumps/AppKit
    os.environ['_TT_SUBPROCESS'] = '1'

GUI_AVAILABLE = RUMPS_AVAILABLE or APPKIT_AVAILABLE

# Config paths
CONFIG_FILE = os.path.expanduser("~/.timetracker/config.json")
CLIENTS_FILE = os.path.expanduser("~/.timetracker/clients.json")
GUI_STATE_FILE = os.path.expanduser("~/.timetracker/gui_state.json")
CLIENT_USAGE_FILE = os.path.expanduser("~/.timetracker/client_usage.json")

# ============================================================
# VERSION - Keep in sync with TimeTracker.spec
# ============================================================
# Version - updated by build process, shows "dev" for local development
APP_VERSION = "dev"

# ============================================================
# PROFESSIONAL COLOR SCHEME
# ============================================================
COLORS = {
    # Primary brand colors - TimeTracker teal
    "primary": "#14B8A6",           # Teal (matches website)
    "primary_hover": "#0D9488",     # Darker teal
    "primary_muted": "#134E4A",     # Dark teal background
    
    # Semantic colors
    "success": "#14B8A6",           # Same teal for consistency
    "success_hover": "#0D9488",
    "success_muted": "#134E4A",
    
    "danger": "#FF453A",            # Apple red
    "danger_hover": "#E03D33",
    "danger_muted": "#4A1F1C",
    
    "warning": "#FF9F0A",           # Apple orange
    "warning_muted": "#4A3A1C",
    
    # Background hierarchy (dark theme)
    "bg_base": "#0D0D0D",           # Deepest background
    "bg_elevated": "#1A1A1A",       # Cards, elevated surfaces
    "bg_surface": "#242424",        # Interactive surfaces
    "bg_hover": "#2E2E2E",          # Hover states
    "bg_active": "#383838",         # Active/pressed states
    
    # Border colors
    "border": "#333333",            # Subtle borders
    "border_light": "#444444",      # Lighter borders
    "border_focus": "#0A84FF",      # Focus rings
    
    # Text hierarchy
    "text_primary": "#FFFFFF",      # Primary text
    "text_secondary": "#A0A0A0",    # Secondary text
    "text_tertiary": "#6B6B6B",     # Muted text
    "text_disabled": "#4A4A4A",     # Disabled text
    
    # Accent colors for ranking
    "gold": "#FFD60A",
    "silver": "#98989D",
    "bronze": "#BF8B67",
    
    # Gradients (as tuples for CTk)
    "gradient_primary": ("#0A84FF", "#0066CC"),
    "gradient_success": ("#30D158", "#28A745"),
}

# Typography
FONTS = {
    "heading_lg": ("SF Pro Display", 22, "bold"),
    "heading_md": ("SF Pro Display", 18, "bold"),
    "heading_sm": ("SF Pro Display", 15, "bold"),
    "body": ("SF Pro Text", 14, "normal"),
    "body_medium": ("SF Pro Text", 14, "bold"),
    "caption": ("SF Pro Text", 12, "normal"),
    "caption_medium": ("SF Pro Text", 12, "bold"),
    "mono": ("SF Mono", 13, "normal"),
}


# ------------------------------------------------------------
# Client Usage Tracking
# ------------------------------------------------------------
def load_client_usage() -> Dict[int, int]:
    """Load client selection counts"""
    if os.path.exists(CLIENT_USAGE_FILE):
        try:
            with open(CLIENT_USAGE_FILE, 'r') as f:
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except:
            pass
    return {}


def save_client_usage(usage: Dict[int, int]):
    """Save client selection counts"""
    try:
        os.makedirs(os.path.dirname(CLIENT_USAGE_FILE), exist_ok=True)
        with open(CLIENT_USAGE_FILE, 'w') as f:
            json.dump(usage, f)
    except Exception as e:
        print(f"[GUI] Failed to save usage: {e}")


def track_client_selection(client_id: int):
    """Increment selection count for a client"""
    if not client_id:
        return
    usage = load_client_usage()
    usage[client_id] = usage.get(client_id, 0) + 1
    save_client_usage(usage)


def sort_clients_by_usage(clients: List[Dict]) -> List[Dict]:
    """Sort clients by usage frequency (most used first)"""
    usage = load_client_usage()
    return sorted(clients, key=lambda c: usage.get(c.get("id", 0), 0), reverse=True)


# ------------------------------------------------------------
# Client Manager
# ------------------------------------------------------------
class ClientManager:
    """Manages the list of clients"""
    
    def __init__(self):
        self.clients: List[Dict] = []
        self.load()
    
    def clear(self):
        """Clear all client data (for re-pairing)"""
        self.clients = []
        try:
            if os.path.exists(CLIENTS_FILE):
                os.remove(CLIENTS_FILE)
        except Exception:
            pass
    
    def load(self, fetch_callback=None):
        if fetch_callback:
            try:
                backend_clients = fetch_callback()
                if backend_clients and isinstance(backend_clients, list):
                    self.clients = backend_clients
                    self.save()
                    print(f"[GUI] Loaded {len(self.clients)} clients from backend")
                    return
            except Exception as e:
                print(f"[GUI] Failed to fetch clients from backend: {e}")
        
        if os.path.exists(CLIENTS_FILE):
            try:
                with open(CLIENTS_FILE, 'r') as f:
                    self.clients = json.load(f)
                    print(f"[GUI] Loaded {len(self.clients)} clients from cache")
            except Exception as e:
                print(f"[GUI] Failed to load clients: {e}")
                self.clients = []
        else:
            self.clients = []
    
    def save(self):
        try:
            os.makedirs(os.path.dirname(CLIENTS_FILE), exist_ok=True)
            with open(CLIENTS_FILE, 'w') as f:
                json.dump(self.clients, f, indent=2)
        except Exception as e:
            print(f"[GUI] Failed to save clients: {e}")
    
    def get_all(self) -> List[Dict]:
        return self.clients
    
    def get_by_id(self, client_id: int) -> Optional[Dict]:
        for c in self.clients:
            if c.get("id") == client_id:
                return c
        return None
    
    def get_by_name(self, name: str) -> Optional[Dict]:
        name_lower = name.lower()
        for c in self.clients:
            if c.get("name", "").lower() == name_lower:
                return c
        return None


# ------------------------------------------------------------
# GUI State (with username support)
# ------------------------------------------------------------
class GUIState:
    """Manages GUI state including user info"""
    
    def __init__(self):
        self.current_client_id: Optional[int] = None
        self.current_client_name: str = "No Client"
        self.username: Optional[str] = None
        self.org_name: Optional[str] = None
        self.load()
    
    def load(self):
        if os.path.exists(GUI_STATE_FILE):
            try:
                with open(GUI_STATE_FILE, 'r') as f:
                    data = json.load(f)
                    self.current_client_id = data.get("current_client_id")
                    self.current_client_name = data.get("current_client_name", "No Client")
                    self.username = data.get("username")
                    self.org_name = data.get("org_name")
            except Exception:
                pass
        
        # Also try to load username from config if not in state
        if not self.username and os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    cfg = json.load(f)
                    self.username = cfg.get("username")
                    self.org_name = cfg.get("org_name")
            except Exception:
                pass
    
    def save(self):
        try:
            os.makedirs(os.path.dirname(GUI_STATE_FILE), exist_ok=True)
            with open(GUI_STATE_FILE, 'w') as f:
                json.dump({
                    "current_client_id": self.current_client_id,
                    "current_client_name": self.current_client_name,
                    "username": self.username,
                    "org_name": self.org_name,
                }, f, indent=2)
        except Exception as e:
            print(f"[GUI] Failed to save state: {e}")
    
    def set_client(self, client_id: Optional[int], client_name: str):
        self.current_client_id = client_id
        self.current_client_name = client_name
        self.save()
    
    def set_user(self, username: str, org_name: str = None):
        """Store the paired user info"""
        self.username = username
        self.org_name = org_name
        self.save()
        
        # Also save to config file for persistence
        try:
            cfg = {}
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    cfg = json.load(f)
            cfg["username"] = username
            if org_name:
                cfg["org_name"] = org_name
            with open(CONFIG_FILE, 'w') as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            print(f"[GUI] Failed to save username to config: {e}")
    
    def clear_pairing(self):
        """Clear ALL user data for re-linking to new account"""
        self.username = None
        self.org_name = None
        self.current_client_id = None
        self.current_client_name = "No Client"
        self.save()
        
        # Clear config file API key
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    cfg = json.load(f)
                cfg.pop("api_key", None)
                cfg.pop("username", None)
                cfg.pop("org_name", None)
                with open(CONFIG_FILE, 'w') as f:
                    json.dump(cfg, f, indent=2)
        except Exception:
            pass
        
        # Clear cached clients (old user's clients!)
        try:
            if os.path.exists(CLIENTS_FILE):
                os.remove(CLIENTS_FILE)
                print("[GUI] Cleared old clients cache")
        except Exception as e:
            print(f"[GUI] Failed to clear clients cache: {e}")
        
        # Clear client usage history
        try:
            if os.path.exists(CLIENT_USAGE_FILE):
                os.remove(CLIENT_USAGE_FILE)
                print("[GUI] Cleared client usage history")
        except Exception as e:
            print(f"[GUI] Failed to clear usage history: {e}")


# ============================================================
# STYLED COMPONENTS
# ============================================================

class StyledFrame(ctk.CTkFrame):
    """Base styled frame with consistent appearance"""
    
    def __init__(self, parent, variant="default", **kwargs):
        colors = {
            "default": COLORS["bg_elevated"],
            "surface": COLORS["bg_surface"],
            "transparent": "transparent",
            "card": COLORS["bg_elevated"],
        }
        
        defaults = {
            "fg_color": colors.get(variant, COLORS["bg_elevated"]),
            "corner_radius": 12,
        }
        defaults.update(kwargs)
        super().__init__(parent, **defaults)


class StyledButton(ctk.CTkButton):
    """Styled button with variants"""
    
    def __init__(self, parent, variant="primary", **kwargs):
        variants = {
            "primary": {
                "fg_color": COLORS["primary"],
                "hover_color": COLORS["primary_hover"],
                "text_color": COLORS["text_primary"],
            },
            "success": {
                "fg_color": COLORS["success"],
                "hover_color": COLORS["success_hover"],
                "text_color": COLORS["text_primary"],
            },
            "danger": {
                "fg_color": COLORS["danger"],
                "hover_color": COLORS["danger_hover"],
                "text_color": COLORS["text_primary"],
            },
            "ghost": {
                "fg_color": "transparent",
                "hover_color": COLORS["bg_hover"],
                "text_color": COLORS["text_secondary"],
                "border_width": 1,
                "border_color": COLORS["border"],
            },
            "subtle": {
                "fg_color": COLORS["bg_surface"],
                "hover_color": COLORS["bg_hover"],
                "text_color": COLORS["text_primary"],
            },
        }
        
        defaults = {
            "corner_radius": 8,
            "height": 40,
            "font": ctk.CTkFont(family="SF Pro Text", size=14, weight="bold"),
        }
        defaults.update(variants.get(variant, variants["primary"]))
        defaults.update(kwargs)
        super().__init__(parent, **defaults)


class StyledEntry(ctk.CTkEntry):
    """Styled text entry field"""
    
    def __init__(self, parent, **kwargs):
        defaults = {
            "fg_color": COLORS["bg_surface"],
            "border_color": COLORS["border"],
            "border_width": 1,
            "corner_radius": 10,
            "height": 44,
            "font": ctk.CTkFont(family="SF Pro Text", size=14),
            "text_color": COLORS["text_primary"],
            "placeholder_text_color": COLORS["text_tertiary"],
        }
        defaults.update(kwargs)
        super().__init__(parent, **defaults)


class Badge(ctk.CTkLabel):
    """Small badge/pill component"""
    
    def __init__(self, parent, text, variant="default", **kwargs):
        variants = {
            "default": {"fg_color": COLORS["bg_surface"], "text_color": COLORS["text_secondary"]},
            "primary": {"fg_color": COLORS["primary_muted"], "text_color": COLORS["primary"]},
            "success": {"fg_color": COLORS["success_muted"], "text_color": COLORS["success"]},
            "warning": {"fg_color": COLORS["warning_muted"], "text_color": COLORS["warning"]},
            "gold": {"fg_color": "#3D3520", "text_color": COLORS["gold"]},
            "silver": {"fg_color": "#2D2D30", "text_color": COLORS["silver"]},
            "bronze": {"fg_color": "#3D2D20", "text_color": COLORS["bronze"]},
        }
        
        style = variants.get(variant, variants["default"])
        defaults = {
            "text": text,
            "font": ctk.CTkFont(family="SF Pro Text", size=11, weight="bold"),
            "corner_radius": 6,
            "padx": 8,
            "pady": 2,
        }
        defaults.update(style)
        defaults.update(kwargs)
        super().__init__(parent, **defaults)


def _run_ai_prompt_process(client_id: int, client_name: str, confidence: float,
                           clients_json: str, result_queue):
    """Run AI Prompt window in separate process"""
    import json
    import customtkinter as ctk
    
    colors = {
        "primary": "#14B8A6",
        "primary_muted": "#134E4A",
        "success": "#14B8A6",
        "success_hover": "#0D9488",
        "success_muted": "#134E4A",
        "warning": "#FF9F0A",
        "warning_muted": "#4A3A1C",
        "bg_base": "#1C1C1E",
        "bg_elevated": "#2C2C2E",
        "bg_surface": "#2C2C2E",
        "bg_hover": "#3A3A3C",
        "border": "#38383A",
        "text_primary": "#FFFFFF",
        "text_secondary": "#8E8E93",
    }
    
    clients = json.loads(clients_json) if clients_json else []
    result = {"confirmed": False, "client_id": None, "client_name": None}
    
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    root.title("TimeTracker")
    root.geometry("440x280")
    root.resizable(False, False)
    root.configure(fg_color=colors["bg_base"])
    
    # Prevent flash: hide window, position, then show
    root.withdraw()
    root.update_idletasks()
    x = (root.winfo_screenwidth() // 2) - 220
    y = (root.winfo_screenheight() // 2) - 150
    root.geometry(f"+{x}+{y}")
    root.attributes('-topmost', True)
    root.deiconify()
    root.lift()
    root.focus_force()
    
    def on_yes():
        result["confirmed"] = True
        result["client_id"] = client_id
        result["client_name"] = client_name
        root.destroy()
    
    def on_no():
        result["confirmed"] = False
        root.destroy()
    
    def on_select(choice):
        if choice == "Select different client...":
            return
        for c in clients:
            if c.get("name") == choice:
                result["confirmed"] = True
                result["client_id"] = c["id"]
                result["client_name"] = c["name"]
                root.destroy()
                return
    
    container = ctk.CTkFrame(root, fg_color="transparent")
    container.pack(fill="both", padx=24, pady=20)
    
    # Header
    header = ctk.CTkFrame(container, fg_color="transparent")
    header.pack(fill="x", pady=(0, 8))
    
    ai_frame = ctk.CTkFrame(header, fg_color=colors["primary_muted"], corner_radius=20, width=40, height=40)
    ai_frame.pack(side="left")
    ai_frame.pack_propagate(False)
    
    ai_label = ctk.CTkLabel(ai_frame, text="AI", 
                            font=ctk.CTkFont(family="SF Pro Text", size=12, weight="bold"),
                            text_color=colors["primary"])
    ai_label.place(relx=0.5, rely=0.5, anchor="center")
    
    title = ctk.CTkLabel(header, text="Working on this client?",
                         font=ctk.CTkFont(family="SF Pro Display", size=20, weight="bold"),
                         text_color=colors["text_primary"])
    title.pack(side="left", padx=(12, 0))
    
    # Client card
    card = ctk.CTkFrame(container, fg_color=colors["bg_elevated"], corner_radius=12)
    card.pack(fill="x", pady=(0, 16))
    
    card_inner = ctk.CTkFrame(card, fg_color="transparent")
    card_inner.pack(fill="x", padx=16, pady=14)
    
    client_label = ctk.CTkLabel(card_inner, text=client_name,
                                font=ctk.CTkFont(family="SF Pro Display", size=16, weight="bold"),
                                text_color=colors["text_primary"])
    client_label.pack(side="left")
    
    # Confidence badge
    if confidence >= 0.7:
        badge_bg = colors["success_muted"]
        badge_fg = colors["success"]
    else:
        badge_bg = colors["warning_muted"]
        badge_fg = colors["warning"]
    
    conf_badge = ctk.CTkLabel(card_inner, text=f"{int(confidence * 100)}% match",
                              font=ctk.CTkFont(family="SF Pro Text", size=11, weight="bold"),
                              fg_color=badge_bg, text_color=badge_fg,
                              corner_radius=6, padx=8, pady=2)
    conf_badge.pack(side="right")
    
    # Buttons
    btn_frame = ctk.CTkFrame(container, fg_color="transparent", height=60)
    btn_frame.pack(fill="x", pady=(0, 12))
    
    yes_btn = ctk.CTkButton(btn_frame, text="Yes, correct", command=on_yes,
                            fg_color=colors["success"], hover_color=colors["success_hover"],
                            height=44, corner_radius=8,
                            font=ctk.CTkFont(family="SF Pro Text", size=14, weight="bold"))
    yes_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))
    
    no_btn = ctk.CTkButton(btn_frame, text="No", command=on_no,
                           fg_color="transparent", hover_color=colors["bg_hover"],
                           border_width=1, border_color=colors["border"],
                           height=44, corner_radius=8,
                           font=ctk.CTkFont(family="SF Pro Text", size=14, weight="bold"))
    no_btn.pack(side="left", expand=True, fill="x", padx=(6, 0))
    
    # Dropdown
    client_names = [c["name"] for c in clients]
    if client_names:
        dropdown = ctk.CTkOptionMenu(
            container,
            values=["Select different client..."] + client_names,
            command=on_select,
            fg_color=colors["bg_surface"],
            button_color=colors["bg_surface"],
            button_hover_color=colors["bg_hover"],
            dropdown_fg_color=colors["bg_elevated"],
            dropdown_hover_color=colors["bg_hover"],
            corner_radius=8, height=38,
            font=ctk.CTkFont(family="SF Pro Text", size=13)
        )
        dropdown.pack(fill="x")
    
    # Auto-close
    def timeout():
        if root.winfo_exists():
            root.destroy()
    root.after(15000, timeout)
    
    root.mainloop()
    result_queue.put((result["confirmed"], result["client_id"], result["client_name"]))


# ============================================================
# MODERN AI PROMPT DIALOG
# ============================================================

def show_client_prompt_modern(client_id: int, client_name: str, confidence: float,
                              callback: Callable, client_mgr: ClientManager):
    """Show professional AI suggestion dialog (subprocess wrapper)"""
    
    clients = client_mgr.get_all()
    clients_json = json.dumps(clients)
    
    result_queue = multiprocessing.Queue()
    
    p = multiprocessing.Process(
        target=_run_ai_prompt_process,
        args=(client_id, client_name, confidence, clients_json, result_queue)
    )
    p.start()
    p.join()
    
    try:
        confirmed, res_id, res_name = result_queue.get_nowait()
        if confirmed:
            callback(True, res_id, res_name, {})
        else:
            callback(False, None, None, {})
    except:
        callback(False, None, None, {})


# ============================================================
# MULTIPROCESSING HELPERS FOR DIALOG WINDOWS
# ============================================================

def _run_today_time_process(data_json: str):
    """Run Today's Time window in separate process"""
    import json
    from datetime import datetime
    import customtkinter as ctk
    
    # Re-define colors locally for subprocess - TimeTracker teal theme
    colors = {
        "primary": "#14B8A6",
        "primary_muted": "#134E4A",
        "bg_base": "#1C1C1E",
        "bg_surface": "#2C2C2E",
        "bg_hover": "#3A3A3A",
        "border": "#38383A",
        "text_primary": "#FFFFFF",
        "text_tertiary": "#636366",
    }
    
    raw_data = json.loads(data_json) if data_json else {}
    
    # Handle both formats: dict with "clients" key OR direct list
    if isinstance(raw_data, dict):
        clients_data = raw_data.get("clients", [])
        total_hours = raw_data.get("global_hours", 0)
    elif isinstance(raw_data, list):
        clients_data = raw_data
        total_hours = sum(e.get("hours", e.get("total_hours", 0)) for e in clients_data)
    else:
        clients_data = []
        total_hours = 0
    
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    root.title("Today's Time")
    root.geometry("480x500")
    root.resizable(False, False)
    root.configure(fg_color=colors["bg_base"])
    
    # Prevent flash: hide window, position, then show
    root.withdraw()
    root.update_idletasks()
    x = (root.winfo_screenwidth() // 2) - 240
    y = (root.winfo_screenheight() // 2) - 250
    root.geometry(f"+{x}+{y}")
    root.attributes('-topmost', True)
    root.deiconify()
    root.lift()
    root.focus_force()
    
    container = ctk.CTkFrame(root, fg_color="transparent")
    container.pack(fill="both", expand=True, padx=20, pady=20)
    
    # Header
    header = ctk.CTkFrame(container, fg_color="transparent")
    header.pack(fill="x", pady=(0, 8))
    
    date_str = datetime.now().strftime("%A, %B %d")
    date_label = ctk.CTkLabel(header, text=date_str,
                              font=ctk.CTkFont(family="SF Pro Display", size=20, weight="bold"),
                              text_color=colors["text_primary"])
    date_label.pack(side="left")
    
    total_frame = ctk.CTkFrame(header, fg_color=colors["primary_muted"], corner_radius=8)
    total_frame.pack(side="right")
    
    total_label = ctk.CTkLabel(total_frame, text=f"{total_hours:.1f} hrs",
                               font=ctk.CTkFont(family="SF Pro Text", size=15, weight="bold"),
                               text_color=colors["primary"])
    total_label.pack(padx=12, pady=6)
    
    # Divider
    divider = ctk.CTkFrame(container, fg_color=colors["border"], height=1)
    divider.pack(fill="x", pady=(0, 16))
    
    # Entries
    entries_frame = ctk.CTkScrollableFrame(container, fg_color="transparent", 
                                           corner_radius=0, border_width=0)
    entries_frame.pack(fill="both", expand=True, pady=(0, 16))
    
    if not clients_data:
        empty_frame = ctk.CTkFrame(entries_frame, fg_color="transparent")
        empty_frame.pack(fill="both", expand=True, pady=60)
        
        empty_icon = ctk.CTkLabel(empty_frame, text="📊", font=ctk.CTkFont(size=36))
        empty_icon.pack()
        
        empty_label = ctk.CTkLabel(empty_frame, text="No time tracked yet today",
                                   font=ctk.CTkFont(family="SF Pro Text", size=14),
                                   text_color=colors["text_tertiary"])
        empty_label.pack(pady=(8, 0))
    else:
        for entry in clients_data:
            client = entry.get("client", entry.get("client_name", "Unknown"))
            hours = entry.get("total_hours", entry.get("hours", 0))
            
            row = ctk.CTkFrame(entries_frame, fg_color=colors["bg_surface"], corner_radius=10)
            row.pack(fill="x", pady=3, padx=2)
            
            row_inner = ctk.CTkFrame(row, fg_color="transparent")
            row_inner.pack(fill="x", padx=14, pady=12)
            
            client_label = ctk.CTkLabel(row_inner, text=client,
                                        font=ctk.CTkFont(family="SF Pro Text", size=14),
                                        text_color=colors["text_primary"])
            client_label.pack(side="left")
            
            hours_label = ctk.CTkLabel(row_inner, text=f"{hours:.2f} hrs",
                                       font=ctk.CTkFont(family="SF Mono", size=14, weight="bold"),
                                       text_color=colors["primary"])
            hours_label.pack(side="right")
    
    # Close button
    close_btn = ctk.CTkButton(container, text="Close", command=root.destroy,
                              fg_color=colors["bg_surface"], hover_color=colors["bg_hover"],
                              height=42, corner_radius=8,
                              font=ctk.CTkFont(family="SF Pro Text", size=14, weight="bold"))
    close_btn.pack(fill="x")
    
    root.mainloop()


def _run_client_picker_process(clients_json: str, usage_json: str, result_queue):
    """Run Client Picker window in separate process"""
    import json
    import tkinter as tk
    import customtkinter as ctk
    
    # Colors - matching Today's Time style
    colors = {
        "primary": "#14B8A6",
        "primary_hover": "#0D9488",
        "bg_window": "#1C1C1C",
        "bg_card": "#2A2A2A",
        "bg_card_hover": "#333333",
        "bg_card_selected": "#14B8A6",
        "bg_scrollbar": "#3A3A3A",
        "bg_scrollbar_hover": "#4A4A4A",
        "text_primary": "#FFFFFF",
        "text_accent": "#14B8A6",
        "text_secondary": "#888888",
        "text_muted": "#555555",
    }
    
    clients = json.loads(clients_json) if clients_json else []
    usage_data = json.loads(usage_json) if usage_json else {}
    usage_data = {int(k): v for k, v in usage_data.items()}
    
    selected = {"id": None, "name": None}
    confirmed = {"value": False}
    row_widgets = []
    
    def sort_by_usage(client_list):
        return sorted(client_list, key=lambda c: usage_data.get(c.get("id", 0), 0), reverse=True)
    
    # Window setup
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    root.title("Select Client")
    root.geometry("380x520")
    root.minsize(320, 400)
    root.configure(fg_color=colors["bg_window"])
    
    # Make window float on top without stealing app focus
    root.attributes('-topmost', True)
    
    # Center window
    root.withdraw()
    root.update_idletasks()
    x = (root.winfo_screenwidth() // 2) - 190
    y = (root.winfo_screenheight() // 2) - 260
    root.geometry(f"+{x}+{y}")
    root.deiconify()
    root.lift()
    root.focus_force()
    
    def do_confirm():
        confirmed["value"] = True
        root.quit()
    
    def do_cancel():
        selected["id"] = None
        selected["name"] = None
        confirmed["value"] = False
        root.quit()
    
    def do_clear():
        selected["id"] = 0
        selected["name"] = "No Client"
        for row, rid, rn in row_widgets:
            row.configure(fg_color=colors["bg_card"])
        ok_btn.configure(fg_color=colors["primary"])
    
    # Main container
    container = ctk.CTkFrame(root, fg_color="transparent")
    container.pack(fill="both", expand=True, padx=16, pady=12)
    
    # Search section
    search_label = ctk.CTkLabel(container, text="Search",
                                font=ctk.CTkFont(size=12),
                                text_color=colors["text_secondary"], anchor="w")
    search_label.pack(fill="x", pady=(0, 6))
    
    search_var = ctk.StringVar()
    search_entry = ctk.CTkEntry(container, textvariable=search_var,
                                placeholder_text="Type to filter...",
                                fg_color=colors["bg_card"],
                                border_width=0,
                                text_color=colors["text_primary"],
                                placeholder_text_color=colors["text_muted"],
                                height=36, corner_radius=8,
                                font=ctk.CTkFont(size=13))
    search_entry.pack(fill="x", pady=(0, 12))
    
    # Results count
    results_label = ctk.CTkLabel(container, text="",
                                 font=ctk.CTkFont(size=11),
                                 text_color=colors["text_muted"], anchor="w")
    results_label.pack(fill="x", pady=(0, 8))
    
    # === USE CTkScrollableFrame for native macOS trackpad support ===
    scroll_frame = ctk.CTkScrollableFrame(
        container, 
        fg_color="transparent",
        scrollbar_button_color=colors["bg_scrollbar"],
        scrollbar_button_hover_color=colors["bg_scrollbar_hover"],
    )
    scroll_frame.pack(fill="both", expand=True, pady=(0, 12))
    
    # Buttons at bottom
    btn_frame = ctk.CTkFrame(container, fg_color="transparent", height=60)
    btn_frame.pack(fill="x", pady=(0, 0))
    
    clear_btn = ctk.CTkButton(btn_frame, text="Clear", command=do_clear,
                              fg_color="transparent", hover_color=colors["bg_card"],
                              text_color=colors["text_muted"],
                              height=32, width=60, corner_radius=6,
                              font=ctk.CTkFont(size=12))
    clear_btn.pack(side="left")
    
    cancel_btn = ctk.CTkButton(btn_frame, text="Cancel", command=do_cancel,
                               fg_color=colors["bg_card"], hover_color=colors["bg_card_hover"],
                               text_color=colors["text_primary"],
                               height=36, width=80, corner_radius=8,
                               font=ctk.CTkFont(size=13))
    cancel_btn.pack(side="right")
    
    ok_btn = ctk.CTkButton(btn_frame, text="OK", command=do_confirm,
                           fg_color=colors["bg_card"], hover_color=colors["primary_hover"],
                           text_color=colors["text_primary"],
                           height=36, width=80, corner_radius=8,
                           font=ctk.CTkFont(size=13, weight="bold"))
    ok_btn.pack(side="right", padx=(0, 8))
    
    def select_row(cid, cname, card):
        selected["id"] = cid
        selected["name"] = cname
        for row, rid, rn in row_widgets:
            if rid == cid:
                row.configure(fg_color=colors["primary"])
            else:
                row.configure(fg_color=colors["bg_card"])
        ok_btn.configure(fg_color=colors["primary"])
    
    def build_list(query=""):
        nonlocal row_widgets
        row_widgets = []
        
        # Clear existing
        for w in scroll_frame.winfo_children():
            w.destroy()
        
        query_lower = query.lower().strip()
        if query_lower:
            filtered = [c for c in clients 
                       if query_lower in c.get("name", "").lower() 
                       or query_lower in c.get("code", "").lower()]
        else:
            filtered = clients
        
        filtered = sort_by_usage(filtered)
        
        total = len(clients)
        showing = len(filtered)
        results_label.configure(text=f"{showing} of {total}" if query_lower else f"{total} clients")
        
        if not filtered:
            empty = ctk.CTkLabel(scroll_frame, text="No clients found",
                                font=ctk.CTkFont(size=13), text_color=colors["text_muted"])
            empty.pack(pady=30)
            return
        
        for idx, client in enumerate(filtered):
            cid = client.get("id")
            cname = client.get("name", "Unknown")
            ccode = client.get("code", "")
            
            # Card row
            card = ctk.CTkFrame(scroll_frame, fg_color=colors["bg_card"],
                               corner_radius=10)
            card.pack(fill="x", pady=3, padx=2)
            
            row_widgets.append((card, cid, cname))
            
            # Content
            content = ctk.CTkFrame(card, fg_color="transparent")
            content.pack(fill="x", padx=14, pady=12)
            
            # Client name (left)
            name_label = ctk.CTkLabel(content, text=cname,
                                     font=ctk.CTkFont(size=14),
                                     text_color=colors["text_primary"])
            name_label.pack(side="left")
            
            # Client code (right, teal)
            code_label = None
            if ccode:
                code_label = ctk.CTkLabel(content, text=ccode,
                                         font=ctk.CTkFont(size=13),
                                         text_color=colors["text_accent"])
                code_label.pack(side="right")
            
            # Click handlers
            def make_click(c, n, w):
                return lambda e: select_row(c, n, w)
            
            def make_dblclick(c, n, w):
                return lambda e: [select_row(c, n, w), do_confirm()]
            
            click_fn = make_click(cid, cname, card)
            dblclick_fn = make_dblclick(cid, cname, card)
            
            # Bind clicks to all widgets in the card
            for widget in [card, content, name_label] + ([code_label] if code_label else []):
                widget.bind("<Button-1>", click_fn)
                widget.bind("<Double-Button-1>", dblclick_fn)
            
            # Hover effect
            def make_hover(c, cid_val):
                def enter(e):
                    if selected["id"] != cid_val:
                        c.configure(fg_color=colors["bg_card_hover"])
                def leave(e):
                    if selected["id"] != cid_val:
                        c.configure(fg_color=colors["bg_card"])
                return enter, leave
            
            enter_fn, leave_fn = make_hover(card, cid)
            card.bind("<Enter>", enter_fn)
            card.bind("<Leave>", leave_fn)
        
        # Re-highlight if previously selected client is still in list
        if selected["id"] is not None and selected["name"] != "No Client":
            for row, rid, rn in row_widgets:
                if rid == selected["id"]:
                    row.configure(fg_color=colors["primary"])
                    break
    
    def on_search(*args):
        build_list(search_var.get())
    search_var.trace_add("write", on_search)
    
    def on_key_down(e):
        if not row_widgets:
            return
        
        current_idx = -1
        for i, (row, rid, rn) in enumerate(row_widgets):
            if rid == selected["id"]:
                current_idx = i
                break
        
        if e.keysym == "Down":
            new_idx = min(current_idx + 1, len(row_widgets) - 1) if current_idx >= 0 else 0
            row, rid, rn = row_widgets[new_idx]
            select_row(rid, rn, row)
        elif e.keysym == "Up":
            new_idx = max(current_idx - 1, 0) if current_idx > 0 else 0
            row, rid, rn = row_widgets[new_idx]
            select_row(rid, rn, row)
    
    root.bind("<Return>", lambda e: do_confirm() if selected["id"] is not None or selected["name"] == "No Client" else None)
    root.bind("<Escape>", lambda e: do_cancel())
    root.bind("<Down>", on_key_down)
    root.bind("<Up>", on_key_down)
    
    build_list("")
    search_entry.focus_set()
    
    root.mainloop()
    root.destroy()
    
    if confirmed["value"] and (selected["id"] is not None or selected["name"] == "No Client"):
        result_queue.put((selected["id"], selected["name"]))
    else:
        result_queue.put((None, None))
    
# ============================================================
# TODAY'S TIME WINDOW (WRAPPER)
# ============================================================

class TodayTimeWindowModern:
    """Professional window showing today's time breakdown (subprocess wrapper)"""
    
    def __init__(self, api_callback: Callable):
        self.api_callback = api_callback
    
    def show_and_refresh(self):
        """Fetch data and show window in subprocess"""
        data = []
        if self.api_callback:
            try:
                data = self.api_callback() or []
            except Exception as e:
                print(f"[GUI] Failed to fetch today's time: {e}")
        
        # Run in subprocess to avoid Tkinter threading issues
        data_json = json.dumps(data)
        p = multiprocessing.Process(target=_run_today_time_process, args=(data_json,))
        p.start()


# ============================================================
# SEARCHABLE CLIENT PICKER (PROFESSIONAL)
# ============================================================

class ClientPickerWindow:
    """Professional searchable client picker with usage ranking (subprocess wrapper)"""
    
    def __init__(self, client_mgr: ClientManager, on_select: Callable):
        self.client_mgr = client_mgr
        self.on_select = on_select
    
    def show(self):
        """Show picker in subprocess and get result"""
        clients = self.client_mgr.get_all()
        usage_data = load_client_usage()
        
        clients_json = json.dumps(clients)
        usage_json = json.dumps(usage_data)
        
        # Use multiprocessing Queue to get result
        result_queue = multiprocessing.Queue()
        
        p = multiprocessing.Process(
            target=_run_client_picker_process,
            args=(clients_json, usage_json, result_queue)
        )
        p.start()
        p.join(timeout=300)  # 5 min timeout max
        
        if p.is_alive():
            p.terminate()
            print("[GUI] Client picker timed out")
            return

        # Menu bar reactivation is handled by rumps keepalive timer
        # Do NOT call AppKit from this background thread - it causes Trace/BPT trap
        
        # Get result
        try:
            selected_id, selected_name = result_queue.get(timeout=2)
            if selected_id is not None or selected_name == "No Client":
                self.on_select(selected_id if selected_id else 0, selected_name)
                print(f"[GUI] Client selected: {selected_name} (id={selected_id})")
        except Exception as e:
            print(f"[GUI] Client picker - no selection or cancelled")

# ============================================================
# PAIRING WINDOW - with username capture
# ============================================================

def _run_pairing_process(result_queue):
    """Run Pairing window in separate process to avoid tkinter/rumps conflict"""
    import os
    import threading
    import customtkinter as ctk

    # Colors - must redefine in subprocess
    colors = {
        "primary": "#14B8A6",
        "primary_hover": "#0D9488",
        "primary_muted": "#134E4A",
        "success": "#14B8A6",
        "success_hover": "#0D9488",
        "success_muted": "#134E4A",
        "danger": "#FF453A",
        "danger_hover": "#E03D33",
        "warning": "#FF9F0A",
        "bg_base": "#0D0D0D",
        "bg_elevated": "#1A1A1A",
        "bg_surface": "#242424",
        "bg_hover": "#2E2E2E",
        "border": "#333333",
        "text_primary": "#FFFFFF",
        "text_secondary": "#A0A0A0",
        "text_tertiary": "#6B6B6B",
    }

    result = {"api_key": None, "username": None, "org_name": None, "success": False}

    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    root.title("Link Device")
    root.geometry("440x380")  # slightly taller since button moved up
    root.resizable(False, False)
    root.configure(fg_color=colors["bg_base"])

    # Center window
    root.withdraw()
    root.update_idletasks()
    x = (root.winfo_screenwidth() // 2) - 220
    y = (root.winfo_screenheight() // 2) - 200
    root.geometry(f"+{x}+{y}")
    root.attributes('-topmost', True)
    root.deiconify()
    root.lift()
    root.focus_force()

    # Container
    container = ctk.CTkFrame(root, fg_color="transparent")
    container.pack(fill="x", padx=24, pady=20)

    # Header
    header = ctk.CTkFrame(container, fg_color="transparent")
    header.pack(fill="x", pady=(0, 16))

    icon_frame = ctk.CTkFrame(
        header, fg_color=colors["primary_muted"],
        corner_radius=20, width=44, height=44
    )
    icon_frame.pack(side="left")
    icon_frame.pack_propagate(False)

    icon = ctk.CTkLabel(icon_frame, text="🔗", font=ctk.CTkFont(size=20))
    icon.place(relx=0.5, rely=0.5, anchor="center")

    title = ctk.CTkLabel(
        header, text="Link This Device",
        font=ctk.CTkFont(family="SF Pro Display", size=22, weight="bold"),
        text_color=colors["text_primary"]
    )
    title.pack(side="left", padx=(12, 0))

    # Instructions
    instructions = ctk.CTkLabel(
        container,
        text="Enter the pairing code from the TimeTracker web app.\nSettings → Devices → Add Device",
        font=ctk.CTkFont(family="SF Pro Text", size=13),
        text_color=colors["text_secondary"],
        justify="left", anchor="w"
    )
    instructions.pack(fill="x", pady=(0, 20))

    # Code input
    input_frame = ctk.CTkFrame(container, fg_color="transparent")
    input_frame.pack(fill="x", pady=(0, 10))

    code_label = ctk.CTkLabel(
        input_frame, text="Pairing Code",
        font=ctk.CTkFont(family="SF Pro Text", size=13),
        text_color=colors["text_secondary"], anchor="w"
    )
    code_label.pack(fill="x")

    code_var = ctk.StringVar()
    code_entry = ctk.CTkEntry(
        input_frame, textvariable=code_var,
        placeholder_text="e.g. ABC123", height=48,
        fg_color=colors["bg_surface"],
        border_color=colors["border"],
        border_width=1,
        corner_radius=10,
        font=ctk.CTkFont(family="SF Mono", size=18, weight="bold"),
        text_color=colors["text_primary"],
        placeholder_text_color=colors["text_tertiary"]
    )
    code_entry.pack(fill="x", pady=(6, 0))

    # ------------------------------------------------------------
    # Pair button DIRECTLY under entry ✅
    # ------------------------------------------------------------

    # Pair button DIRECTLY under entry
    pair_btn = ctk.CTkButton(
        container,
        text="Pair Device",
        fg_color=colors["primary"],
        hover_color=colors["primary_hover"],
        height=46, corner_radius=8,
        font=ctk.CTkFont(family="SF Pro Text", size=14, weight="bold")
    )
    pair_btn.pack(fill="x", pady=(20, 6))

    # Status label
    status_label = ctk.CTkLabel(
        container, text="",
        font=ctk.CTkFont(family="SF Pro Text", size=13),
        anchor="w"
    )
    status_label.pack(fill="x", pady=0)

    # Reset container (for dynamic reset button)
    reset_container = ctk.CTkFrame(container, fg_color="transparent")
    reset_container.pack(fill="x", pady=0)

    # Optional: cancel below pair button (keeps layout clean)
    def do_cancel():
        result["success"] = False
        root.destroy()

    cancel_btn = ctk.CTkButton(
        container,
        text="Cancel",
        command=do_cancel,
        fg_color="transparent",
        hover_color=colors["bg_hover"],
        border_width=1,
        border_color=colors["border"],
        height=44, corner_radius=8,
        font=ctk.CTkFont(family="SF Pro Text", size=14, weight="bold")
    )
    cancel_btn.pack(fill="x", pady=(0, 6))

    # ------------------------------------------------------------
    # Pairing helpers (unchanged logic, just moved above)
    # ------------------------------------------------------------
    def reset_device_and_retry():
        """Reset device ID and let user try again."""
        device_id_file = os.path.expanduser("~/.mavops_device_id")
        if os.path.exists(device_id_file):
            try:
                os.remove(device_id_file)
                print("[GUI] Device ID reset successfully")
            except Exception as e:
                status_label.configure(text=f"Failed to reset: {e}",
                                       text_color=colors["danger"])
                return

        config_file = os.path.expanduser("~/.timetracker/config.json")
        if os.path.exists(config_file):
            try:
                os.remove(config_file)
            except:
                pass

        status_label.configure(text="Device reset! Enter your pairing code again.",
                               text_color=colors["success"])

        for widget in reset_container.winfo_children():
            widget.destroy()

        code_var.set("")
        code_entry.focus_set()

    def show_success(res):
        """Show success screen"""
        for widget in root.winfo_children():
            widget.destroy()

        success_container = ctk.CTkFrame(root, fg_color="transparent")
        success_container.pack(fill="both", padx=24, pady=20)

        icon_frame = ctk.CTkFrame(success_container, fg_color=colors["success_muted"],
                                  corner_radius=40, width=80, height=80)
        icon_frame.pack(pady=(40, 20))
        icon_frame.pack_propagate(False)

        icon = ctk.CTkLabel(icon_frame, text="✓",
                            font=ctk.CTkFont(size=40, weight="bold"),
                            text_color=colors["success"])
        icon.place(relx=0.5, rely=0.5, anchor="center")

        title = ctk.CTkLabel(success_container, text="Device Paired!",
                             font=ctk.CTkFont(family="SF Pro Display", size=24, weight="bold"),
                             text_color=colors["text_primary"])
        title.pack(pady=(0, 8))

        username = res.get("username", "")
        org = res.get("org_name", "")
        info = f"Signed in as {username}"
        if org:
            info += f" • {org}"

        info_label = ctk.CTkLabel(success_container, text=info,
                                  font=ctk.CTkFont(family="SF Pro Text", size=14),
                                  text_color=colors["text_secondary"])
        info_label.pack(pady=(0, 24))

        instruction = ctk.CTkLabel(
            success_container,
            text="Look for the ⏱ icon in your menu bar\nat the top of your screen.",
            font=ctk.CTkFont(family="SF Pro Text", size=14),
            text_color=colors["text_secondary"],
            justify="center"
        )
        instruction.pack(pady=(0, 24))

        def do_continue():
            result["success"] = True
            result["api_key"] = res.get("api_key")
            result["username"] = res.get("username")
            result["org_name"] = res.get("org_name")
            root.destroy()

        start_btn = ctk.CTkButton(success_container, text="Start TimeTracker",
                                  command=do_continue,
                                  fg_color=colors["success"],
                                  hover_color=colors["success_hover"],
                                  height=46, corner_radius=8,
                                  font=ctk.CTkFont(family="SF Pro Text", size=14, weight="bold"))
        start_btn.pack(fill="x")

    def handle_result(res):
        pair_btn.configure(state="normal")

        if res and res.get("api_key"):
            show_success(res)

        elif res and res.get("error") == "device_belongs_to_another_user":
            status_label.configure(
                text="This device was previously paired to another account.",
                text_color=colors["warning"]
            )

            for widget in reset_container.winfo_children():
                widget.destroy()

            reset_btn = ctk.CTkButton(
                reset_container,
                text="Reset Device & Try Again",
                command=reset_device_and_retry,
                fg_color=colors["danger"],
                hover_color=colors["danger_hover"],
                height=40, corner_radius=8,
                font=ctk.CTkFont(family="SF Pro Text", size=14, weight="bold")
            )
            reset_btn.pack(fill="x")

        else:
            error = res.get("error", "Pairing failed") if res else "Pairing failed"
            status_label.configure(text=error, text_color=colors["danger"])

    def do_pair():
        import platform
        import urllib.request
        import urllib.error

        code = code_var.get().strip().upper()
        if not code:
            status_label.configure(text="Please enter a pairing code",
                                   text_color=colors["warning"])
            return

        status_label.configure(text="Pairing...", text_color=colors["text_secondary"])
        pair_btn.configure(state="disabled")

        for widget in reset_container.winfo_children():
            widget.destroy()

        root.update()

        def do_pair_request():
            try:
                # Read device ID
                device_id_file = os.path.expanduser("~/.mavops_device_id")
                if os.path.exists(device_id_file):
                    with open(device_id_file, 'r') as f:
                        device_id = f.read().strip()
                else:
                    import uuid
                    device_id = str(uuid.uuid4())
                    os.makedirs(os.path.dirname(device_id_file), exist_ok=True)
                    with open(device_id_file, 'w') as f:
                        f.write(device_id)

                hostname = platform.node()

                # Make request
                api_base = os.environ.get("TIMETRACKER_API_BASE", "https://timetracker-api-k375.onrender.com")
                url = f"{api_base}/api/agents/pair/claim/"

                data = json.dumps({
                    "code": code,
                    "hostname": hostname,
                    "device_id": device_id,
                }).encode('utf-8')

                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )

                with urllib.request.urlopen(req, timeout=30) as resp:
                    res = json.loads(resp.read().decode('utf-8'))

                    if res.get("api_key"):
                        # Save config with username
                        cfg_dir = os.path.expanduser("~/.timetracker")
                        cfg_file = os.path.join(cfg_dir, "config.json")
                        os.makedirs(cfg_dir, exist_ok=True)

                        cfg = {}
                        if os.path.exists(cfg_file):
                            try:
                                with open(cfg_file, 'r') as f:
                                    cfg = json.load(f)
                            except:
                                pass

                        cfg["api_key"] = res["api_key"]
                        cfg["api_base"] = "https://timetracker-api-k375.onrender.com/api"
                        cfg["verbose"] = cfg.get("verbose", True)
                        cfg["username"] = res.get("username", "")
                        cfg["org_name"] = res.get("org_name", "")

                        with open(cfg_file, 'w') as f:
                            json.dump(cfg, f, indent=2)

                    root.after(0, lambda: handle_result(res))

            except urllib.error.HTTPError as e:
                try:
                    err_body = json.loads(e.read().decode('utf-8'))
                    root.after(0, lambda body=err_body: handle_result(body))
                except:
                    err_msg = f"HTTP {e.code}"
                    root.after(0, lambda msg=err_msg: handle_result({"error": msg}))
            except Exception as e:
                err_msg = str(e)
                root.after(0, lambda msg=err_msg: handle_result({"error": msg}))

        threading.Thread(target=do_pair_request, daemon=True).start()

    # hook pair button now that do_pair exists
    pair_btn.configure(command=do_pair)

    code_entry.bind("<Return>", lambda e: do_pair())
    code_entry.focus_set()

    root.mainloop()

    # Send result back to parent process (including username!)
    result_queue.put((result["success"], result["api_key"], result["username"], result["org_name"]))


def show_pairing_window(pair_callback: Callable = None) -> Optional[str]:
    """
    Show pairing window in subprocess to avoid tkinter/rumps conflict.
    Returns api_key on success, None otherwise.
    """
    import multiprocessing
    
    result_queue = multiprocessing.Queue()
    
    p = multiprocessing.Process(
        target=_run_pairing_process,
        args=(result_queue,)
    )
    p.start()
    p.join(timeout=300)  # 5 min timeout
    
    if p.is_alive():
        p.terminate()
        print("[GUI] Pairing window timed out")
        return None
    
    # Menu bar reactivation is handled by rumps keepalive timer
    # Do NOT call AppKit from this background thread - it causes Trace/BPT trap
    
    # Get result
    try:
        success, api_key, username, org_name = result_queue.get(timeout=2)
        if success and api_key:
            print(f"✅ Device paired as {username}; key saved.")
            state = GUIState()
            state.set_user(username, org_name)
            return api_key
    except Exception as e:
        print(f"[GUI] Pairing result error: {e}")
    
    return None

# ============================================================
# MENU BAR APP (rumps) - WITH USERNAME AND RE-PAIR
# ============================================================

if RUMPS_AVAILABLE:
    class TimeTrackerMenuBarApp(rumps.App):
        """Professional menu bar app with username display and re-pair option"""
        
        def __init__(self, controller):
            super().__init__("⏱", quit_button=None)
            
            # CRITICAL: Set activation policy to Accessory (menu bar only, no dock icon)
            try:
                from AppKit import NSApp, NSApplication
                NSApplication.sharedApplication()
                NSApp.setActivationPolicy_(1)  # NSApplicationActivationPolicyAccessory
                print("[GUI] Set activation policy to Accessory")
            except Exception as e:
                print(f"[GUI] Failed to set activation policy: {e}")
            
            self.controller = controller
            self._client_callbacks = {}
            self._start_keepalive()
            
            # Set initial title from state
            client_name = self.controller.state.current_client_name
            if client_name and client_name != "No Client":
                display = client_name[:12] if len(client_name) > 12 else client_name; self.title = f"⏱ {display}"
            else:
                self.title = "⏱ None"
            
            self._rebuild_menu()

        def _start_keepalive(self):
            """Periodic keepalive to prevent icon from disappearing"""
            def tick(_):
                try:
                    # FORCE menu bar to stay visible
                    try:
                        from AppKit import NSApp
                        NSApp.unhide_(None)
                        NSApp.setActivationPolicy_(1)  # Accessory
                    except Exception as e:
                        print(f"[GUI] AppKit keepalive error: {e}")
                    
                    # Force refresh the title if empty
                    current = self.title
                    if not current or current == "":
                        print(f"[GUI] ⚠️ Title was empty, restoring...")
                        client_name = self.controller.state.current_client_name
                        if client_name and client_name != "No Client":
                            display = client_name[:12] if len(client_name) > 12 else client_name; self.title = f"⏱ {display}"
                        else:
                            self.title = "⏱ None"
                except Exception as e:
                    print(f"[GUI] Keepalive error: {e}")
            
            # Run every 2 seconds (aggressive)
            rumps.Timer(tick, 2).start()
        
        def _rebuild_menu(self):
            self.menu.clear()
            self._client_callbacks.clear()
            
            # ============================================================
            # USER INFO SECTION (if paired)
            # ============================================================
            username = self.controller.state.username
            org_name = self.controller.state.org_name
            
            if username:
                user_display = f"👤 {username}"
                if org_name:
                    user_display = f"👤 {username} • {org_name}"
                user_item = rumps.MenuItem(user_display)
                user_item.set_callback(None)  # Non-clickable
                self.menu.add(user_item)
                self.menu.add(None)  # Separator
            
            # ============================================================
            # CLIENT CONTROLS
            # ============================================================
            
            # Search clients
            search_item = rumps.MenuItem("Search Clients...    ⌃⌥T")
            search_item.set_callback(self._on_search)
            self.menu.add(search_item)
            
            # Switch client submenu
            switch_menu = rumps.MenuItem("Switch Client")
            
            clear_item = rumps.MenuItem("Clear Client")
            clear_item.set_callback(self._on_clear_client)
            switch_menu.add(clear_item)
            switch_menu.add(None)
            
            clients = sort_clients_by_usage(self.controller.client_mgr.get_all())
            
            for idx, client in enumerate(clients[:15]):
                client_id = client["id"]
                client_name = client["name"]
                is_current = client_id == self.controller.state.current_client_id
                
                prefix = "● " if is_current else ""
                
                callback_key = f"client_{client_id}"
                
                def make_callback(cid, cname):
                    def callback(_):
                        self._switch_client(cid, cname)
                    return callback
                
                self._client_callbacks[callback_key] = make_callback(client_id, client_name)
                
                item = rumps.MenuItem(f"{prefix}{client_name}")
                item.set_callback(self._client_callbacks[callback_key])
                switch_menu.add(item)
            
            if len(clients) > 15:
                more_item = rumps.MenuItem(f"... {len(clients) - 15} more (use Search)")
                more_item.set_callback(None)
                switch_menu.add(more_item)
            
            self.menu.add(switch_menu)
            self.menu.add(None)
            
            # ============================================================
            # TIME & INFO
            # ============================================================
            
            # Today's time
            today_item = rumps.MenuItem("Today's Time...")
            today_item.set_callback(self._on_today_time)
            self.menu.add(today_item)
            
            self.menu.add(None)
            
            # ============================================================
            # DEVICE MANAGEMENT
            # ============================================================
            
            # Re-link device option
            relink_item = rumps.MenuItem("Re-link Device...")
            relink_item.set_callback(self._on_relink_device)
            self.menu.add(relink_item)
            
            # Version info
            version_item = rumps.MenuItem(f"Version {APP_VERSION}")
            version_item.set_callback(None)
            self.menu.add(version_item)
            
            self.menu.add(None)
            
            # ============================================================
            # QUIT
            # ============================================================
            quit_item = rumps.MenuItem("Quit TimeTracker")
            quit_item.set_callback(rumps.quit_application)
            self.menu.add(quit_item)
        
        def _on_search(self, _):
            """Open the searchable client picker window"""
            if self.controller.fetch_clients_callback:
                try:
                    self.controller.client_mgr.load(self.controller.fetch_clients_callback)
                except Exception as e:
                    print(f"[GUI] Failed to refresh clients: {e}")
            
            def show_picker():
                picker = ClientPickerWindow(self.controller.client_mgr, self._switch_client)
                picker.show()
                
                # Rebuild menu on main rumps thread (safe)
                try:
                    self._rebuild_menu()
                except Exception as e:
                    print(f"[GUI] Error after picker close: {e}")
            
            threading.Thread(target=show_picker, daemon=True).start()
        
        
        def _show_client_picker(self):
            if self.controller.fetch_clients_callback:
                try:
                    self.controller.client_mgr.load(self.controller.fetch_clients_callback)
                except Exception as e:
                    print(f"[GUI] Failed to refresh clients: {e}")
            
            picker = ClientPickerWindow(self.controller.client_mgr, self._switch_client)
            picker.show()
        
        def _show_today_time(self):
            window = TodayTimeWindowModern(self.controller.get_today_time_callback)
            window.show_and_refresh()
        
        def _on_clear_client(self, _):
            self._switch_client(0, "No Client")
        
        def _switch_client(self, client_id: int, client_name: str):
            if client_id and client_id > 0:
                track_client_selection(client_id)
            
            if client_id == 0:
                self.controller.state.set_client(None, "No Client")
                self.title = "⏱ None"
                print(f"[GUI] Client cleared")
            else:
                self.controller.state.set_client(client_id, client_name)
                display = client_name[:12] if len(client_name) > 12 else client_name; self.title = f"⏱ {display}"
                print(f"[GUI] Switched to: {client_name}")
            
            if self.controller.set_current_client_callback:
                try:
                    self.controller.set_current_client_callback(client_id if client_id else 0)
                    print(f"[GUI] Synced to backend ✓")
                except Exception as e:
                    print(f"[GUI] Sync failed: {e}")
            
            self._rebuild_menu()
        
        def _on_today_time(self, _):
            """Show today's time summary"""
            try:
                if self.controller.get_today_time_callback:
                    data = self.controller.get_today_time_callback()
                    if data:
                        total = sum(entry.get('hours', 0) for entry in data)
                        lines = [f"• {entry.get('client', 'Unknown')}: {entry.get('hours', 0):.1f}h" for entry in data[:5]]
                        message = "\n".join(lines) + f"\n\nTotal: {total:.1f} hours"
                        rumps.alert(title="Today's Time", message=message, ok="Open Dashboard", cancel="Close")
                    else:
                        rumps.alert(title="Today's Time", message="No time tracked yet today")
            except Exception as e:
                print(f"[GUI] Today's time error: {e}")
                # Fallback to browser
                import webbrowser
                webbrowser.open("https://timetracker.mavops.ai/daily")
                
        
        def _on_relink_device(self, _):
            """Show re-pairing dialog and restart app after success"""
            def do_relink():
                # Clear existing pairing AND all cached data
                self.controller.state.clear_pairing()
                
                # Clear in-memory client list too!
                self.controller.client_mgr.clear()
                
                # Show pairing window
                api_key = show_pairing_window()
                
                if api_key:
                    print(f"[GUI] Re-paired successfully, restarting app...")
                    
                    # Restart the app to fully reinitialize with new credentials
                    self._restart_app()
                else:
                    print("[GUI] Re-pairing cancelled")
        
            threading.Thread(target=do_relink, daemon=True).start()
        
        def _restart_app(self):
            """Restart the application to apply new pairing"""
            import subprocess
            import sys
            import time
            
            # Small delay to let pairing window close
            time.sleep(0.5)
            
            if getattr(sys, 'frozen', False):
                # Running as compiled .app bundle
                # Find the .app bundle path
                app_path = sys.executable
                bundle_path = app_path
                while bundle_path and not bundle_path.endswith('.app'):
                    bundle_path = os.path.dirname(bundle_path)
                
                if bundle_path.endswith('.app'):
                    print(f"[GUI] Relaunching {bundle_path}")
                    subprocess.Popen(['open', '-n', bundle_path])
                else:
                    # Fallback: try /Applications
                    subprocess.Popen(['open', '-n', '/Applications/TimeTracker.app'])
            else:
                # Running from python main.py (dev mode)
                print("[GUI] Dev mode: please restart manually")
                # Could do: subprocess.Popen([sys.executable] + sys.argv)
            
            # Quit current instance
            rumps.quit_application()


# ============================================================
# MAIN CONTROLLER
# ============================================================

class TimeTrackerSystemTray:
    """Main system tray controller"""
    
    def __init__(self):
        self.client_mgr = ClientManager()
        self.state = GUIState()
        
        self.on_client_confirmed_callback = None
        self.on_client_rejected_callback = None
        self.get_today_time_callback = None
        self.get_ai_guess_callback = None
        self.fetch_clients_callback = None
        self.set_current_client_callback = None
        self.get_current_client_callback = None
        
        self.app = None
        self._start_ai_timer()
    
    def _start_ai_timer(self):
        def ai_tick():
            while True:
                _time.sleep(15)
                try:
                    if self.get_ai_guess_callback:
                        guess = self.get_ai_guess_callback()
                        if guess and guess.get("client_id"):
                            self._maybe_show_prompt(guess)
                except Exception as e:
                    print(f"[AI] Error: {e}")
        
        threading.Thread(target=ai_tick, daemon=True).start()
    
    def _maybe_show_prompt(self, guess: dict):
        client_id = guess.get("client_id")
        client_name = guess.get("client_name")
        confidence = float(guess.get("confidence", 0))
        
        if not client_id or confidence < 0.45:
            return
        if confidence >= 0.80:
            return
        if self.state.current_client_id == client_id:
            return
        
        def show():
            if MODERN_UI:
                show_client_prompt_modern(
                    client_id, client_name, confidence,
                    self._on_prompt_response,
                    self.client_mgr
                )
        
        threading.Thread(target=show, daemon=True).start()
    
    def _on_prompt_response(self, confirmed: bool, client_id: Optional[int],
                           client_name: Optional[str], prompt_data: dict):
        if confirmed and client_id and client_name:
            self.state.set_client(client_id, client_name)
            print(f"[GUI] Confirmed: {client_name}")
            
            if self.set_current_client_callback:
                self.set_current_client_callback(client_id)
            
            if self.on_client_confirmed_callback:
                self.on_client_confirmed_callback(client_id, client_name, prompt_data)
            
            if self.app and hasattr(self.app, '_rebuild_menu'):
                self.app._rebuild_menu()
        else:
            print(f"[GUI] Rejected")
            if self.on_client_rejected_callback:
                self.on_client_rejected_callback(prompt_data)
    
    def refresh_client_menu(self, clients):
        self.client_mgr.clients = clients
        self.client_mgr.save()
        print(f"[GUI] Updated client cache ({len(clients)} clients)")

        # Rebuild the actual NSMenu so (a) new clients from the web app appear,
        # and (b) the ● selected marker follows the current client.
        # Must run on the rumps main thread — schedule via rumps.Timer.
        if self.app and hasattr(self.app, '_rebuild_menu'):
            try:
                import rumps

                # Hold a strong reference on the controller so the timer isn't
                # garbage-collected before it fires. Previous local-variable
                # version was being reaped intermittently, causing the bullet
                # to stay stale.
                def _rebuild_once(timer):
                    try:
                        self.app._rebuild_menu()
                    except Exception as e:
                        print(f"[GUI] _rebuild_menu error: {e}")
                    finally:
                        try:
                            timer.stop()
                        except Exception:
                            pass
                        # Drop the strong ref now that the timer is done
                        self._pending_rebuild_timer = None

                self._pending_rebuild_timer = rumps.Timer(_rebuild_once, 0.05)
                self._pending_rebuild_timer.start()
            except Exception as e:
                print(f"[GUI] Failed to schedule menu rebuild: {e}")
    
    def run(self):
        if RUMPS_AVAILABLE:
            self.app = TimeTrackerMenuBarApp(self)
            print("[GUI] Menu bar started")
            self.app.run()
        else:
            print("[GUI] Menu bar not available")


# ============================================================
# PUBLIC API
# ============================================================


def run_gui_app(on_client_confirmed: Callable,
                on_client_rejected: Callable,
                get_today_time: Callable,
                get_ai_guess: Callable = None,
                fetch_clients: Callable = None,
                set_current_client: Callable = None,
                get_current_client: Callable = None,
                repair_callback: Callable = None,
                cpa_tools_data: dict = None,
                sync=None):
    """Start the GUI menu bar app."""
    if not GUI_AVAILABLE:
        print("[GUI] GUI components not available")
        return None
    
    tray = TimeTrackerSystemTray()
    tray.on_client_confirmed_callback = on_client_confirmed
    tray.on_client_rejected_callback = on_client_rejected
    tray.get_today_time_callback = get_today_time
    tray.get_ai_guess_callback = get_ai_guess
    tray.fetch_clients_callback = fetch_clients
    tray.set_current_client_callback = set_current_client
    tray.get_current_client_callback = get_current_client
    
    if fetch_clients:
        try:
            tray.client_mgr.load(fetch_clients)
        except Exception as e:
            print(f"[GUI] Failed to load clients: {e}")
    
    if get_current_client:
        try:
            current = get_current_client()
            if current and current.get("client_id"):
                tray.state.set_client(current["client_id"], current["client_name"])
                print(f"[GUI] Restored: {current['client_name']}")
        except Exception as e:
            print(f"[GUI] Failed to restore state: {e}")
    
    if sync:
        sync.gui_menu_bar = tray
        print("[GUI] Registered with sync")
    
    return tray


if __name__ == "__main__":
    def test_confirmed(cid, cname, data):
        print(f"Confirmed: {cname}")
    
    def test_rejected(data):
        print("Rejected")
    
    def test_today():
        return [
            {"client": "Acme Corp", "hours": 3.5},
            {"client": "Beta Industries", "hours": 2.0},
            {"client": "Gamma Holdings", "hours": 1.25},
        ]
    
    def test_pair(code):
        print(f"Pairing: {code}")
        _time.sleep(1)
        if code == "TEST123":
            return {"api_key": "test-key-123", "username": "testuser", "org_name": "Test Org"}
        return {"error": "Invalid code"}
    
    print("Testing pairing...")
    result = show_pairing_window(test_pair)
    print(f"Result: {result}")
    
    if result:
        tray = run_gui_app(test_confirmed, test_rejected, test_today)
        if tray:
            tray.run()