#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TimeTracker Windows System Tray GUI - Modern Version

Features:
- Beautiful system tray icon
- Modern dialogs with CustomTkinter
- Client switching with ROBUST WINDOWS FOCUS
- AI client prompts
- Today's time viewer
- Clean menu without duplicates
- Dark themed compact tray menu
- User name display in menu
- Repair device option
"""

import os
import json
import threading
import time as _time
import ctypes
from datetime import datetime
from typing import Optional, List, Dict, Callable

# Modern UI
try:
    import customtkinter as ctk
    MODERN_UI = True
except ImportError:
    MODERN_UI = False
    import tkinter as tk
    from tkinter import ttk, messagebox

# System tray
try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
    from pystray import MenuItem as Item, Menu
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False
    print("Warning: pystray not available. Install with: pip install pystray pillow")

# Notifications
try:
    from win10toast import ToastNotifier
    TOAST_AVAILABLE = True
except ImportError:
    TOAST_AVAILABLE = False

try:
    from floating_widget import FloatingClientWidget, create_floating_widget, WIDGET_AVAILABLE
except ImportError:
    WIDGET_AVAILABLE = False

GUI_AVAILABLE = TRAY_AVAILABLE

# Config paths
CLIENTS_FILE = os.path.expanduser("~/.timetracker/clients.json")
GUI_STATE_FILE = os.path.expanduser("~/.timetracker/gui_state.json")
CLIENT_USAGE_FILE = os.path.expanduser("~/.timetracker/client_usage.json")

# ============================================================
# COLOR SCHEME - GREEN/TEAL theme matching website
# ============================================================
COLORS = {
    "primary": "#14B8A6",
    "primary_hover": "#0D9488",
    "primary_light": "#5EEAD4",
    "success": "#10B981",
    "success_hover": "#059669",
    "danger": "#EF4444",
    "danger_hover": "#DC2626",
    "warning": "#F59E0B",
    "bg_dark": "#1A1A1A",
    "bg_card": "#252525",
    "bg_input": "#2A2A2A",
    "bg_item": "#252525",
    "bg_item_hover": "#333333",
    "bg_item_selected": "#14B8A6",
    "border": "#3A3A3A",
    "text": "#FFFFFF",
    "text_primary": "#FFFFFF",
    "text_secondary": "#888888",
    "text_muted": "#666666",
    "accent": "#14B8A6",
    "tray_bg": "#14B8A6",
    "bg_window": "#1A1A1A",
}


# ============================================================
# ROBUST WINDOWS FOCUS HANDLING
# ============================================================
def get_hwnd_by_title(title):
    """Find window handle by exact title"""
    try:
        return ctypes.windll.user32.FindWindowW(None, title)
    except:
        return None


def force_window_to_foreground(hwnd):
    """Aggressively force a window to foreground on Windows"""
    if not hwnd:
        return False
    
    try:
        user32 = ctypes.windll.user32
        
        foreground_hwnd = user32.GetForegroundWindow()
        foreground_thread = user32.GetWindowThreadProcessId(foreground_hwnd, None)
        current_thread = user32.GetCurrentThreadId()
        
        if foreground_thread != current_thread:
            user32.AttachThreadInput(foreground_thread, current_thread, True)
        
        user32.ShowWindow(hwnd, 9)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
        
        if foreground_thread != current_thread:
            user32.AttachThreadInput(foreground_thread, current_thread, False)
        
        return True
    except Exception as e:
        print(f"[Focus] Error: {e}")
        return False


def release_hotkeys():
    """Release any held hotkey keys before showing picker"""
    try:
        import keyboard
        keyboard.release('alt')
        keyboard.release('shift')
        keyboard.release('t')
        keyboard.release('ctrl')
    except:
        pass
    _time.sleep(0.05)


def allow_set_foreground():
    """Allow this process to set foreground window"""
    try:
        ctypes.windll.user32.AllowSetForegroundWindow(-1)
    except:
        pass


# ============================================================
# Client Usage Tracking
# ============================================================
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


# ============================================================
# Client Manager
# ============================================================
class ClientManager:
    """Manages the list of clients"""
    
    def __init__(self):
        self.clients: List[Dict] = []
        self.load()
    
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


# ============================================================
# GUI State
# ============================================================
class GUIState:
    """Manages GUI state"""
    
    def __init__(self):
        self.current_client_id: Optional[int] = None
        self.current_client_name: str = "No Client"
        self.load()
    
    def load(self):
        if os.path.exists(GUI_STATE_FILE):
            try:
                with open(GUI_STATE_FILE, 'r') as f:
                    data = json.load(f)
                    self.current_client_id = data.get("current_client_id")
                    self.current_client_name = data.get("current_client_name", "No Client")
            except Exception:
                pass
    
    def save(self):
        try:
            os.makedirs(os.path.dirname(GUI_STATE_FILE), exist_ok=True)
            with open(GUI_STATE_FILE, 'w') as f:
                json.dump({
                    "current_client_id": self.current_client_id,
                    "current_client_name": self.current_client_name,
                }, f, indent=2)
        except Exception as e:
            print(f"[GUI] Failed to save state: {e}")
    
    def set_client(self, client_id: Optional[int], client_name: str):
        self.current_client_id = client_id
        self.current_client_name = client_name
        self.save()


# ============================================================
# Modern Client Picker with ROBUST FOCUS
# ============================================================
class ClientPickerWindow:
    """Searchable client picker popup with robust Windows focus"""
    
    WINDOW_TITLE = "Switch Client"
    
    def __init__(self, client_mgr: ClientManager, on_select: Callable, current_id: int = None, parent_root=None):
        self.client_mgr = client_mgr
        self.on_select = on_select
        self.current_id = current_id
        self.all_clients = client_mgr.get_all()
        self.usage_data = load_client_usage()
        
        self._selected_id = None
        self._selected_name = None
        self.current_index = 0
        self.visible_clients = []
        self.item_widgets = []
        self.shutting_down = False
        self.after_ids = []

        
        self.WIDTH = 450
        self.MAX_HEIGHT = 550
        self.ITEM_HEIGHT = 48
        self.INPUT_HEIGHT = 50
        self.PADDING = 12
        
        release_hotkeys()
        allow_set_foreground()
        
        self._setup_window(parent_root)

        self._setup_ui()
        self._filter_clients("")
    

    def _setup_window(self, parent_root=None):
        ctk.set_appearance_mode("dark")
        if parent_root:
            self.root = ctk.CTkToplevel(parent_root)
        else:
            self.root = ctk.CTk()
        
        # Common setup for both cases
        self.root.title(self.WINDOW_TITLE)
        self.root.attributes('-topmost', True)
        
        try:
            self.root.attributes('-alpha', 0.98)
        except:
            pass
        
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        self.x = (screen_w // 2) - (self.WIDTH // 2)
        self.y = (screen_h // 3)
        
        self.root.geometry(f"{self.WIDTH}x{self.INPUT_HEIGHT + self.PADDING * 2}+{self.x}+{self.y}")
        self.root.configure(fg_color=COLORS["bg_window"])
    
    def _setup_ui(self):
        container = ctk.CTkFrame(self.root, fg_color=COLORS["bg_window"], corner_radius=12)
        container.pack(fill="both", expand=True, padx=1, pady=1)
        
        header_frame = ctk.CTkFrame(container, fg_color="transparent")
        header_frame.pack(fill="x", padx=self.PADDING, pady=(self.PADDING, 8))
        
        header_label = ctk.CTkLabel(
            header_frame,
            text="Switch Client",
            font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
            text_color=COLORS["text_primary"]
        )
        header_label.pack(side="left")
        
        close_btn = ctk.CTkButton(
            header_frame,
            text="✕",
            width=30,
            height=30,
            corner_radius=15,
            fg_color=COLORS["bg_item"],
            hover_color=COLORS["bg_item_hover"],
            text_color=COLORS["text_secondary"],
            command=self._cancel
        )
        close_btn.pack(side="right")
        
        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", self._on_search)
        
        search_frame = ctk.CTkFrame(container, fg_color="transparent")
        search_frame.pack(fill="x", padx=self.PADDING, pady=(0, 8))
        
        self.search_entry = ctk.CTkEntry(
            search_frame,
            textvariable=self.search_var,
            placeholder_text="Type to search...",
            font=ctk.CTkFont(family="Segoe UI", size=15),
            fg_color=COLORS["bg_input"],
            border_color=COLORS["accent"],
            border_width=2,
            text_color=COLORS["text_primary"],
            placeholder_text_color=COLORS["text_muted"],
            height=self.INPUT_HEIGHT - 5,
            corner_radius=10
        )
        self.search_entry.pack(fill="x")
        
        self.results_frame = ctk.CTkScrollableFrame(container, fg_color="transparent")
        self.results_frame.pack(fill="both", expand=True, padx=4, pady=(0, 8))
        
        clear_btn = ctk.CTkButton(
            container,
            text="Clear Client",
            command=self._clear_client,
            fg_color=COLORS["bg_item"],
            hover_color=COLORS["bg_item_hover"],
            text_color=COLORS["text_secondary"],
            height=35,
            corner_radius=8
        )
        clear_btn.pack(fill="x", padx=self.PADDING, pady=(0, self.PADDING))
        
        self.search_entry.bind("<Escape>", lambda e: self._cancel())
        self.search_entry.bind("<Return>", lambda e: self._confirm_selection())
        self.search_entry.bind("<Down>", lambda e: [self._update_selection(self.current_index + 1), "break"][1])
        self.search_entry.bind("<Up>", lambda e: [self._update_selection(self.current_index - 1), "break"][1])
        
        self.root.bind("<Escape>", lambda e: self._cancel())
        self.root.bind("<Return>", lambda e: self._confirm_selection())
        self.root.bind("<Down>", lambda e: self._update_selection(self.current_index + 1))
        self.root.bind("<Up>", lambda e: self._update_selection(self.current_index - 1))
    
    def _fuzzy_match(self, query, text):
        if not query:
            return True, 0
        query = query.lower()
        text = text.lower()
        if query in text:
            if text.startswith(query):
                return True, 1000 + (100 - len(text))
            return True, 500 + (100 - text.index(query))
        qi = 0
        score = 0
        for i, char in enumerate(text):
            if qi < len(query) and char == query[qi]:
                score += 5
                qi += 1
        if qi == len(query):
            return True, score
        return False, 0
    
    def _on_search(self, *args):
        if self.shutting_down:
            return
        query = self.search_var.get()
        self._filter_clients(query)
    
    def _filter_clients(self, query: str):
        for widget in self.results_frame.winfo_children():
            widget.destroy()
        self.item_widgets = []
        
        query = query.strip()
        
        if query:
            scored = []
            for client in self.all_clients:
                name = client.get("name", "")
                code = client.get("code", "")
                match_name, score_name = self._fuzzy_match(query, name)
                match_code, score_code = self._fuzzy_match(query, code)
                if match_name or match_code:
                    usage_bonus = min(self.usage_data.get(client.get("id", 0), 0) * 2, 200)
                    total_score = max(score_name, score_code) + usage_bonus
                    scored.append((client, total_score))
            scored.sort(key=lambda x: x[1], reverse=True)
            self.visible_clients = [c for c, _ in scored][:15]
        else:
            self.visible_clients = sort_clients_by_usage(self.all_clients)[:15]
        
        if not self.visible_clients:
            no_results = ctk.CTkLabel(
                self.results_frame,
                text="No clients found",
                font=ctk.CTkFont(size=13),
                text_color=COLORS["text_muted"]
            )
            no_results.pack(pady=20)
            self._resize_window(1)
            return
        
        for i, client in enumerate(self.visible_clients):
            cid = client.get("id")
            cname = client.get("name", "Unknown")
            ccode = client.get("code", "")
            is_current = cid == self.current_id
            
            item_frame = ctk.CTkFrame(
                self.results_frame,
                fg_color=COLORS["bg_item_selected"] if i == 0 else COLORS["bg_item"],
                corner_radius=8,
                height=self.ITEM_HEIGHT
            )
            item_frame.pack(fill="x", pady=2, padx=4)
            item_frame.pack_propagate(False)
            
            inner = ctk.CTkFrame(item_frame, fg_color="transparent")
            inner.pack(fill="both", expand=True, padx=12, pady=8)
            
            # Simple prefix - just bullet for current, no medals
            display_name = f"● {cname}" if is_current else cname
            name_label = ctk.CTkLabel(
                inner,
                text=display_name,
                font=ctk.CTkFont(family="Segoe UI", size=14),
                text_color=COLORS["text_primary"],
                anchor="w"
            )
            name_label.pack(side="left", fill="x", expand=True)
            
            code_label = None
            if ccode:
                code_label = ctk.CTkLabel(
                    inner,
                    text=ccode,
                    font=ctk.CTkFont(family="Segoe UI", size=11),
                    text_color=COLORS["accent"]
                )
                code_label.pack(side="right")
            
            self.item_widgets.append((item_frame, name_label, code_label))
            
            def make_click(idx):
                def handler(e):
                    self._update_selection(idx)
                return handler
            
            def make_dblclick(idx):
                def handler(e):
                    self._update_selection(idx)
                    self._confirm_selection()
                return handler
            
            for widget in [item_frame, inner, name_label] + ([code_label] if code_label else []):
                widget.bind("<Button-1>", make_click(i))
                widget.bind("<Double-Button-1>", make_dblclick(i))
            
            def make_hover(frame, idx):
                def enter(e):
                    if self.current_index != idx:
                        frame.configure(fg_color=COLORS["bg_item_hover"])
                def leave(e):
                    if self.current_index != idx:
                        frame.configure(fg_color=COLORS["bg_item"])
                return enter, leave
            
            enter_fn, leave_fn = make_hover(item_frame, i)
            item_frame.bind("<Enter>", enter_fn)
            item_frame.bind("<Leave>", leave_fn)
        
        self.current_index = 0
        self._resize_window(len(self.visible_clients))
    
    def _resize_window(self, num_items):
        num_items = max(1, min(num_items, 12))
        content_height = self.INPUT_HEIGHT + self.PADDING * 2 + (num_items * (self.ITEM_HEIGHT + 4)) + 100
        content_height = min(content_height, self.MAX_HEIGHT)
        self.root.geometry(f"{self.WIDTH}x{content_height}+{self.x}+{self.y}")
    
    def _update_selection(self, new_index):
        if not self.visible_clients:
            return
        new_index = max(0, min(new_index, len(self.visible_clients) - 1))
        self.current_index = new_index
        for i, (frame, name_lbl, code_lbl) in enumerate(self.item_widgets):
            if i == new_index:
                frame.configure(fg_color=COLORS["bg_item_selected"])
            else:
                frame.configure(fg_color=COLORS["bg_item"])
    
    def _confirm_selection(self):
        if self.visible_clients and 0 <= self.current_index < len(self.visible_clients):
            client = self.visible_clients[self.current_index]
            self._selected_id = client.get("id")
            self._selected_name = client.get("name")
        self._close()
    
    def _cancel(self):
        self._selected_id = None
        self._selected_name = None
        self._close()
    
    def _clear_client(self):
        self._selected_id = 0
        self._selected_name = "No Client"
        self._close()
    
    def _close(self):
        self.shutting_down = True
        for after_id in self.after_ids:
            try:
                self.root.after_cancel(after_id)
            except:
                pass
        self.after_ids.clear()
        if isinstance(self.root, ctk.CTkToplevel):
            self.root.grab_release()
            self.root.destroy()
        else:
            self.root.quit()
    
    def _force_focus(self):
        """ROBUST focus handling for Windows"""
        if self.shutting_down:
            return
        try:
            self.root.deiconify()
            self.root.state('normal')
            self.root.lift()
            self.root.attributes('-topmost', True)
            self.root.update()
            
            hwnd = get_hwnd_by_title(self.WINDOW_TITLE)
            if hwnd:
                force_window_to_foreground(hwnd)
            
            self.root.focus_force()
            
            if hasattr(self.search_entry, '_entry'):
                self.search_entry._entry.focus_set()
                self.search_entry._entry.focus_force()
                self.search_entry._entry.icursor('end')
            else:
                self.search_entry.focus_set()
            
        except Exception as e:
            print(f"[Picker] Focus error: {e}")
    
    def _stay_on_top(self):
        """Keep window on top"""
        if self.shutting_down:
            return
        try:
            if self.root.winfo_exists():
                self.root.lift()
                self.root.attributes('-topmost', True)
                after_id = self.root.after(300, self._stay_on_top)
                self.after_ids.append(after_id)
        except:
            pass
    
    def show(self):
        """Show the picker with robust focus"""
        for delay in [10, 50, 100, 150, 200, 300, 400, 500]:
            self.after_ids.append(self.root.after(delay, self._force_focus))
        
        self.after_ids.append(self.root.after(100, self._stay_on_top))
        
        # If Toplevel, wait for it to close; if standalone CTk, use mainloop
        if isinstance(self.root, ctk.CTkToplevel):
            self.root.grab_set()
            self.root.wait_window()
        else:
            self.root.mainloop()
            try:
                self.root.destroy()
            except:
                pass
        
        if self._selected_id is not None or self._selected_name == "No Client":
            self.on_select(self._selected_id or 0, self._selected_name)


# ============================================================
# Modern AI Prompt Dialog
# ============================================================
def show_client_prompt_modern(client_id: int, client_name: str, confidence: float,
                              callback: Callable, client_mgr: ClientManager):
    """Show beautiful AI suggestion dialog"""
    
    result = {"confirmed": False, "client_id": None, "client_name": None}
    
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    root.title("TimeTracker")
    root.geometry("420x280")
    root.resizable(False, False)
    root.attributes('-topmost', True)
    
    root.update_idletasks()
    x = (root.winfo_screenwidth() // 2) - 210
    y = (root.winfo_screenheight() // 2) - 140
    root.geometry(f"+{x}+{y}")
    
    def on_yes():
        result["confirmed"] = True
        result["client_id"] = client_id
        result["client_name"] = client_name
        root.destroy()
    
    def on_no():
        result["confirmed"] = False
        root.destroy()
    
    def on_select(choice):
        client = client_mgr.get_by_name(choice)
        if client:
            result["confirmed"] = True
            result["client_id"] = client["id"]
            result["client_name"] = client["name"]
        root.destroy()
    
    content = ctk.CTkFrame(root, fg_color="transparent")
    content.pack(fill="both", expand=True, padx=25, pady=20)
    
    header = ctk.CTkFrame(content, fg_color="transparent")
    header.pack(fill="x", pady=(0, 15))
    
    icon_label = ctk.CTkLabel(
        header,
        text="🤖",
        font=ctk.CTkFont(size=32)
    )
    icon_label.pack(side="left")
    
    question = ctk.CTkLabel(
        header,
        text="Working on this client?",
        font=ctk.CTkFont(size=18, weight="bold"),
        anchor="w"
    )
    question.pack(side="left", padx=(15, 0))
    
    client_card = ctk.CTkFrame(content, corner_radius=10)
    client_card.pack(fill="x", pady=(0, 15))
    
    card_inner = ctk.CTkFrame(client_card, fg_color="transparent")
    card_inner.pack(fill="x", padx=15, pady=12)
    
    client_label = ctk.CTkLabel(
        card_inner,
        text=client_name,
        font=ctk.CTkFont(size=16, weight="bold")
    )
    client_label.pack(side="left")
    
    conf_color = COLORS["primary"] if confidence >= 0.7 else COLORS["warning"]
    conf_badge = ctk.CTkLabel(
        card_inner,
        text=f"{int(confidence * 100)}%",
        font=ctk.CTkFont(size=12, weight="bold"),
        fg_color=conf_color,
        corner_radius=5,
        padx=8,
        pady=2
    )
    conf_badge.pack(side="right")
    
    btn_frame = ctk.CTkFrame(content, fg_color="transparent")
    btn_frame.pack(fill="x", pady=(0, 10))
    
    yes_btn = ctk.CTkButton(
        btn_frame,
        text="✓  Yes",
        command=on_yes,
        fg_color=COLORS["primary"],
        hover_color=COLORS["primary_hover"],
        height=42,
        font=ctk.CTkFont(size=14, weight="bold")
    )
    yes_btn.pack(side="left", expand=True, fill="x", padx=(0, 5))
    
    no_btn = ctk.CTkButton(
        btn_frame,
        text="✗  No",
        command=on_no,
        fg_color=COLORS["danger"],
        hover_color=COLORS["danger_hover"],
        height=42,
        font=ctk.CTkFont(size=14, weight="bold")
    )
    no_btn.pack(side="left", expand=True, fill="x", padx=(5, 0))
    
    client_names = [c["name"] for c in client_mgr.get_all()]
    if client_names:
        dropdown = ctk.CTkOptionMenu(
            content,
            values=["Select different client..."] + client_names,
            command=lambda c: on_select(c) if c != "Select different client..." else None,
            fg_color=COLORS["bg_card"],
            button_color=COLORS["bg_card"],
            button_hover_color=COLORS["bg_dark"],
            height=35
        )
        dropdown.pack(fill="x")
    
    def timeout():
        if root.winfo_exists():
            root.destroy()
    
    root.after(15000, timeout)
    root.mainloop()
    
    if result["confirmed"]:
        callback(True, result["client_id"], result["client_name"], {})
    else:
        callback(False, None, None, {})


# ============================================================
# Modern Today's Time Window
# ============================================================
class TodayTimeWindowModern:
    """Beautiful window showing today's time"""
    
    def __init__(self, api_callback: Callable):
        self.api_callback = api_callback
        
        ctk.set_appearance_mode("dark")
        self.root = ctk.CTk()
        self.root.title("Today's Time")
        self.root.geometry("500x450")
        self.root.resizable(False, False)
        self.root.attributes('-topmost', True)
        
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - 250
        y = (self.root.winfo_screenheight() // 2) - 225
        self.root.geometry(f"+{x}+{y}")
        
        self._setup_ui()
    
    def _setup_ui(self):
        content = ctk.CTkFrame(self.root, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=20)
        
        header = ctk.CTkFrame(content, fg_color="transparent")
        header.pack(fill="x", pady=(0, 15))
        
        date_str = datetime.now().strftime("%A, %B %d")
        date_label = ctk.CTkLabel(
            header,
            text=f"{date_str}",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        date_label.pack(side="left")
        
        self.total_label = ctk.CTkLabel(
            header,
            text="0.0 hrs",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLORS["primary"]
        )
        self.total_label.pack(side="right")
        
        self.entries_frame = ctk.CTkScrollableFrame(content, corner_radius=10)
        self.entries_frame.pack(fill="both", expand=True, pady=(0, 15))
        
        btn_frame = ctk.CTkFrame(content, fg_color="transparent")
        btn_frame.pack(fill="x")
        
        refresh_btn = ctk.CTkButton(
            btn_frame,
            text="Refresh",
            command=self._on_refresh,
            fg_color=COLORS["primary"],
            hover_color=COLORS["primary_hover"],
            height=40
        )
        refresh_btn.pack(side="left", expand=True, fill="x", padx=(0, 5))
        
        close_btn = ctk.CTkButton(
            btn_frame,
            text="Close",
            command=self.root.destroy,
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_dark"],
            height=40
        )
        close_btn.pack(side="right", expand=True, fill="x", padx=(5, 0))
        
        self.root.bind("<Escape>", lambda e: self.root.destroy())
    
    def _on_refresh(self):
        if not self.api_callback:
            return
        
        try:
            data = self.api_callback()
            
            for widget in self.entries_frame.winfo_children():
                widget.destroy()
            
            total_hours = 0.0
            
            if not data:
                empty_label = ctk.CTkLabel(
                    self.entries_frame,
                    text="No time tracked yet today",
                    font=ctk.CTkFont(size=14),
                    text_color=COLORS["text_muted"]
                )
                empty_label.pack(pady=40)
            else:
                for entry in data:
                    client = entry.get("client", "Unknown")
                    hours = entry.get("hours", 0)
                    total_hours += hours
                    
                    row = ctk.CTkFrame(self.entries_frame, corner_radius=8)
                    row.pack(fill="x", pady=3, padx=5)
                    
                    row_inner = ctk.CTkFrame(row, fg_color="transparent")
                    row_inner.pack(fill="x", padx=12, pady=10)
                    
                    client_label = ctk.CTkLabel(
                        row_inner,
                        text=client,
                        font=ctk.CTkFont(size=14),
                        anchor="w"
                    )
                    client_label.pack(side="left")
                    
                    hours_label = ctk.CTkLabel(
                        row_inner,
                        text=f"{hours:.1f} hrs",
                        font=ctk.CTkFont(size=14, weight="bold"),
                        text_color=COLORS["primary"]
                    )
                    hours_label.pack(side="right")
            
            self.total_label.configure(text=f"{total_hours:.1f} hrs")
        
        except Exception as e:
            print(f"[GUI] Failed to fetch today's time: {e}")
    
    def show_and_refresh(self):
        self._on_refresh()
        self.root.mainloop()


# ============================================================
# System Tray Controller
# ============================================================
class TimeTrackerSystemTray:
    """Main system tray controller with modern UI"""
    
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
        self.repair_callback = None  # NEW: Repair device callback
        
        self.icon = None
        self.floating_widget = None
        self.user_name = None  # NEW: Store user's display name
        
        self._last_picker_time = 0
        self._picker_lock = threading.Lock()
    
    def _create_image(self):
        """Create system tray icon"""
        size = 64
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        draw.rounded_rectangle(
            [(4, 4), (size-4, size-4)],
            radius=12,
            fill=COLORS["tray_bg"]
        )
        
        center = size // 2
        radius = 18
        
        draw.ellipse(
            [(center - radius, center - radius), 
             (center + radius, center + radius)],
            outline='white',
            width=3
        )
        
        draw.line([(center, center), (center, center - 10)], fill='white', width=3)
        draw.line([(center, center), (center + 8, center)], fill='white', width=2)
        
        return img
        
    def _build_menu_items(self):
        """Build system tray menu items"""
        
        def make_switch_handler(cid, cname):
            def handler(icon, item):
                threading.Thread(target=lambda: self._switch_client(cid, cname), daemon=True).start()
            return handler

        clients = sort_clients_by_usage(self.client_mgr.get_all())
        
        client_items = [Item("Clear Client", make_switch_handler(0, "No Client"))]
        
        for client in clients[:10]:
            client_id = client["id"]
            client_name = client["name"]
            is_current = client_id == self.state.current_client_id
            
            prefix = "● " if is_current else ""
            
            client_items.append(
                Item(f"{prefix}{client_name}", make_switch_handler(client_id, client_name))
            )
        
        if len(clients) > 10:
            client_items.append(Item(f"... and {len(clients) - 10} more (use Search)", None, enabled=False))
        
        def on_search(icon, item):
            threading.Timer(0.05, self._show_client_picker).start()
        
        def on_today(icon, item):
            threading.Timer(0.05, self._on_today_time).start()

        def on_show_widget(icon, item):
            if self.floating_widget and self.floating_widget.root:
                # Widget exists but is hidden — just deiconify it
                self.floating_widget.is_visible = True
                self.floating_widget._save_state()
                self.floating_widget.root.after(0, lambda: (
                    self.floating_widget.root.deiconify(),
                    self.floating_widget.root.attributes('-topmost', True),
                    self.floating_widget.root.lift()
                ))
            else:
                print("[GUI] Widget will appear on next restart — cannot recreate mid-session")
        
        def on_repair(icon, item):
            threading.Timer(0.05, self._on_repair_device).start()
        
        def on_quit(icon, item):
            self._on_quit()
        
        # Build menu with user name header if available
        menu_items = []
        
        # User name header (like Mac version)
        if self.user_name:
            menu_items.append(Item(f"👤 {self.user_name}", None, enabled=False))
            menu_items.append(pystray.Menu.SEPARATOR)
        
        # Current client status
        current_client = self.state.current_client_name or "No Client"
        menu_items.append(Item(f"⏱ {current_client}", None, enabled=False))
        menu_items.append(pystray.Menu.SEPARATOR)
        
        # Main actions
        menu_items.extend([
            Item("Search Clients...    Alt+Ctrl+T", on_search),
            Item("Switch Client", pystray.Menu(*client_items)),
            Item("Today's Time...", on_today),
            pystray.Menu.SEPARATOR,
            Item("Show Client Widget", on_show_widget),
            pystray.Menu.SEPARATOR,
            Item("🔧 Repair Device...", on_repair),
            Item("Quit", on_quit),
        ])
        
        return tuple(menu_items)
    
    def _on_repair_device(self):
        """Handle repair device request"""
        print("[GUI] Repair device menu clicked")
        if MODERN_UI:
            self._show_repair_dialog()
        elif self.repair_callback:
            print("[GUI] Calling repair callback directly (no modern UI)")
            self.repair_callback()
        else:
            print("[GUI] No repair callback set!")
    
    def _show_repair_dialog(self):
        """Show confirmation dialog for device repair"""
        print("[GUI] Showing repair dialog...")
        
        ctk.set_appearance_mode("dark")
        root = ctk.CTk()
        root.title("Repair Device")
        root.geometry("400x220")
        root.resizable(False, False)
        root.attributes('-topmost', True)
        
        root.update_idletasks()
        x = (root.winfo_screenwidth() // 2) - 200
        y = (root.winfo_screenheight() // 2) - 110
        root.geometry(f"+{x}+{y}")
        
        content = ctk.CTkFrame(root, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=25, pady=20)
        
        # Warning icon and title
        header = ctk.CTkFrame(content, fg_color="transparent")
        header.pack(fill="x", pady=(0, 15))
        
        icon_label = ctk.CTkLabel(
            header,
            text="⚠️",
            font=ctk.CTkFont(size=32)
        )
        icon_label.pack(side="left")
        
        title = ctk.CTkLabel(
            header,
            text="Repair Device?",
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w"
        )
        title.pack(side="left", padx=(15, 0))
        
        # Description
        desc = ctk.CTkLabel(
            content,
            text="This will reset your device pairing.\nYou'll need to re-enter a pairing code from the web app.",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"],
            justify="left"
        )
        desc.pack(fill="x", pady=(0, 20))
        
        # Buttons
        btn_frame = ctk.CTkFrame(content, fg_color="transparent")
        btn_frame.pack(fill="x")
        
        # Store callback reference before dialog
        repair_callback = self.repair_callback
        
        def on_cancel():
            print("[GUI] Repair cancelled by user")
            root.destroy()
        
        def on_repair():
            print("[GUI] User confirmed repair")
            root.destroy()
            root.update()  # Ensure window is fully closed
            
            if repair_callback:
                print("[GUI] Executing repair callback...")
                try:
                    repair_callback()
                    print("[GUI] Repair callback completed")
                except Exception as e:
                    print(f"[GUI] Repair callback error: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                print("[GUI] ERROR: No repair callback was set!")
        
        cancel_btn = ctk.CTkButton(
            btn_frame,
            text="Cancel",
            command=on_cancel,
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_dark"],
            height=40
        )
        cancel_btn.pack(side="left", expand=True, fill="x", padx=(0, 5))
        
        repair_btn = ctk.CTkButton(
            btn_frame,
            text="Repair Device",
            command=on_repair,
            fg_color=COLORS["danger"],
            hover_color=COLORS["danger_hover"],
            height=40,
            font=ctk.CTkFont(weight="bold")
        )
        repair_btn.pack(side="right", expand=True, fill="x", padx=(5, 0))
        
        root.bind("<Escape>", lambda e: root.destroy())
        print("[GUI] Repair dialog ready, starting mainloop")
        root.mainloop()
        print("[GUI] Repair dialog closed")

\
    def _show_client_picker(self):
        """Show searchable client picker - instant open"""
        
        now = _time.time() * 1000
        with self._picker_lock:
            if now - self._last_picker_time < 1000:
                print("[GUI] Client picker debounced")
                return
            self._last_picker_time = now
        
        def run_picker():
            selected_id = None
            selected_name = None
            
            def on_select(cid, cname):
                nonlocal selected_id, selected_name
                selected_id = cid
                selected_name = cname
            
            # Refresh client list in background BEFORE showing picker
            # so cached data is fresh, but don't block on it
            try:
                if hasattr(self, 'fetch_clients') and self.fetch_clients:
                    def _bg_refresh():
                        try:
                            fresh = self.fetch_clients()
                            if fresh:
                                self.client_mgr.clients = fresh
                                self.client_mgr.save()
                        except:
                            pass
                    threading.Thread(target=_bg_refresh, daemon=True).start()
            except:
                pass
            
            parent = None
            if self.floating_widget and self.floating_widget.root:
                try:
                    if self.floating_widget.root.winfo_exists():
                        parent = self.floating_widget.root
                except Exception:
                    parent = None
            
            picker = ClientPickerWindow(
                self.client_mgr,
                on_select,
                current_id=self.state.current_client_id,
                parent_root=parent
            )
            picker.show()
            
            if selected_id is not None or selected_name == "No Client":
                self._switch_client(selected_id or 0, selected_name)
        
        if self.floating_widget and self.floating_widget.root:
            try:
                if self.floating_widget.root.winfo_exists():
                    self.floating_widget.root.after(0, run_picker)  # was 10, use 0
                    return
            except Exception:
                pass
        
        threading.Thread(target=run_picker, daemon=True).start()
    
    def _switch_client(self, client_id: int, client_name: str):
        """Handle client switch"""
        track_client_selection(client_id)
        
        if client_id == 0:
            self.state.set_client(None, "No Client")
            print(f"[GUI] Client cleared")
        else:
            self.state.set_client(client_id, client_name)
            print(f"[GUI] Switched to client: {client_name}")
        
        # Update tray icon tooltip to show current client
        if self.icon:
            tooltip = f"TimeTracker - {client_name}"
            if self.user_name:
                tooltip = f"TimeTracker ({self.user_name}) - {client_name}"
            self.icon.title = tooltip
        
        if self.set_current_client_callback:
            try:
                self.set_current_client_callback(client_id if client_id else 0)
            except Exception as e:
                print(f"[GUI] Failed to sync client: {e}")

        # Update floating widget
        if self.floating_widget:
            self.floating_widget.update_client(client_id, client_name)
    
    def _on_today_time(self):
        """Show today's time window"""
        if MODERN_UI:
            window = TodayTimeWindowModern(self.get_today_time_callback)
            window.show_and_refresh()
    
    def _on_quit(self):
        """Quit the application"""
        if self.icon:
            self.icon.stop()
    
    def refresh_client_menu(self, clients):
        """Called by sync to update client list"""
        self.client_mgr.clients = clients
        self.client_mgr.save()
        print(f"[GUI] Refreshed client list with {len(clients)} clients")
        
    def run(self):
        """Start the system tray icon and floating widget"""
        if not TRAY_AVAILABLE:
            print("[GUI] System tray not available")
            return
        
        # Set tooltip with current client and user name
        if self.user_name:
            tooltip = f"TimeTracker ({self.user_name}) - {self.state.current_client_name}"
        else:
            tooltip = f"TimeTracker - {self.state.current_client_name}"
        
        # Use native pystray menu (right-click to open)
        self.icon = pystray.Icon(
            "timetracker",
            self._create_image(),
            tooltip,
            menu=pystray.Menu(self._build_menu_items)
        )
        
        # Try floating widget first (runs in its own mainloop)
        widget_created = False
        if WIDGET_AVAILABLE:
            try:
                self.floating_widget = create_floating_widget(self)
                if self.floating_widget:
                    result = self.floating_widget.create()
                    # Check if widget was actually created (has a root window)
                    if result is not None and self.floating_widget.root is not None:
                        print("[GUI] Floating widget created successfully")
                        widget_created = True
                    else:
                        print("[GUI] Floating widget not visible (user closed it previously)")
                        widget_created = False
            except Exception as e:
                print(f"[GUI] Floating widget creation error: {e}")
                import traceback
                traceback.print_exc()
                widget_created = False
        
        if widget_created:
            # Run tray in background, widget in foreground (has mainloop)
            def run_tray():
                print("[GUI] System tray started (background)")
                self.icon.run()
            
            tray_thread = threading.Thread(target=run_tray, daemon=True)
            tray_thread.start()
            
            try:
                print("[GUI] Starting floating widget mainloop...")
                self.floating_widget.run()  # Blocks here
                print("[GUI] Floating widget mainloop ended")
            except Exception as e:
                print(f"[GUI] Floating widget error: {e}")
                import traceback
                traceback.print_exc()
            
            # If widget mainloop ended, keep tray running
            print("[GUI] Widget closed, keeping tray running...")
            tray_thread.join()
        
        else:
            # No widget - run tray in FOREGROUND (blocking)
            print("[GUI] Running system tray in foreground (no widget)")
            print("[GUI] System tray started - right-click tray icon for menu")
            self.icon.run()  # This blocks!
            print("[GUI] System tray stopped")


# ============================================================
# Standalone show_client_picker function (for hotkey use)
# ============================================================


# ============================================================
# Entrypoint
# ============================================================
def run_gui_app(on_client_confirmed: Callable,
                on_client_rejected: Callable,
                get_today_time: Callable,
                get_ai_guess: Callable = None,
                fetch_clients: Callable = None,
                set_current_client: Callable = None,
                get_current_client: Callable = None,
                repair_callback: Callable = None,
                sync=None):
    """Start the GUI system tray app."""
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
    tray.repair_callback = repair_callback  # NEW: Set repair callback
    
    if fetch_clients:
        try:
            tray.client_mgr.load(fetch_clients)
        except Exception as e:
            print(f"[GUI] Failed to load clients: {e}")
    
    if get_current_client:
        try:
            current = get_current_client()
            if current and current.get("client_id"):
                tray.state.set_client(
                    current["client_id"],
                    current["client_name"]
                )
                print(f"[GUI] Restored client: {current['client_name']}")
        except Exception as e:
            print(f"[GUI] Failed to restore client state: {e}")
    
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
        ]
    
    def test_repair():
        print("Repair device called!")
    
    tray = run_gui_app(test_confirmed, test_rejected, test_today, repair_callback=test_repair)
    if tray:
        tray.user_name = "Test User"  # Set test user name
        tray.run()