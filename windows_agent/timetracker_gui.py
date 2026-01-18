#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TimeTracker Windows System Tray GUI - Modern Version

Features:
- Beautiful system tray icon
- Modern dialogs with CustomTkinter
- Client switching
- AI client prompts
- Today's time viewer
"""

import os
import json
import threading
import time as _time
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

GUI_AVAILABLE = TRAY_AVAILABLE

# Config paths
CLIENTS_FILE = os.path.expanduser("~/.timetracker/clients.json")
GUI_STATE_FILE = os.path.expanduser("~/.timetracker/gui_state.json")

# Color scheme
COLORS = {
    "primary": "#3B82F6",
    "primary_hover": "#2563EB",
    "success": "#10B981",
    "success_hover": "#059669",
    "danger": "#EF4444",
    "danger_hover": "#DC2626",
    "warning": "#F59E0B",
    "bg_dark": "#1F2937",
    "bg_card": "#374151",
    "text": "#F9FAFB",
    "text_muted": "#9CA3AF",
    "tray_bg": "#3B82F6",  # Blue tray icon
}

CLIENT_USAGE_FILE = os.path.expanduser("~/.timetracker/client_usage.json")

def _run_client_picker_process(clients_json: str, current_id: int, result_queue):
    """Run client picker in separate process"""
    import json
    clients = json.loads(clients_json) if clients_json else []
    
    # Create a minimal client manager for the picker
    class TempClientMgr:
        def __init__(self, clients):
            self.clients = clients
        def get_all(self):
            return self.clients
    
    selected = {"id": None, "name": None}
    
    def on_select(client_id, client_name):
        selected["id"] = client_id
        selected["name"] = client_name
    
    picker = ClientPickerWindow(TempClientMgr(clients), on_select)
    picker.show()
    
    result_queue.put((selected["id"], selected["name"]))

def load_client_usage() -> Dict[int, int]:
    """Load client selection counts"""
    if os.path.exists(CLIENT_USAGE_FILE):
        try:
            with open(CLIENT_USAGE_FILE, 'r') as f:
                # Convert string keys back to int
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
# GUI State
# ------------------------------------------------------------
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


# ------------------------------------------------------------
# Modern AI Prompt Dialog
# ------------------------------------------------------------
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
    
    # Center window
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
    
    # Main content
    content = ctk.CTkFrame(root, fg_color="transparent")
    content.pack(fill="both", expand=True, padx=25, pady=20)
    
    # Icon and question
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
    
    # Client card
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
    
    # Confidence badge
    conf_color = COLORS["success"] if confidence >= 0.7 else COLORS["warning"]
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
    
    # Buttons
    btn_frame = ctk.CTkFrame(content, fg_color="transparent")
    btn_frame.pack(fill="x", pady=(0, 10))
    
    yes_btn = ctk.CTkButton(
        btn_frame,
        text="✓  Yes",
        command=on_yes,
        fg_color=COLORS["success"],
        hover_color=COLORS["success_hover"],
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
    
    # Different client dropdown
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
    
    # Auto-close after 15 seconds
    def timeout():
        if root.winfo_exists():
            root.destroy()
    
    root.after(15000, timeout)
    root.mainloop()
    
    # Callback
    if result["confirmed"]:
        callback(True, result["client_id"], result["client_name"], {})
    else:
        callback(False, None, None, {})


# ------------------------------------------------------------
# Modern Today's Time Window
# ------------------------------------------------------------
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
        
        # Center window
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - 250
        y = (self.root.winfo_screenheight() // 2) - 225
        self.root.geometry(f"+{x}+{y}")
        
        self._setup_ui()
    
    def _setup_ui(self):
        content = ctk.CTkFrame(self.root, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Header
        header = ctk.CTkFrame(content, fg_color="transparent")
        header.pack(fill="x", pady=(0, 15))
        
        date_str = datetime.now().strftime("%A, %B %d")
        date_label = ctk.CTkLabel(
            header,
            text=f"📅  {date_str}",
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
        
        # Time entries list
        self.entries_frame = ctk.CTkScrollableFrame(content, corner_radius=10)
        self.entries_frame.pack(fill="both", expand=True, pady=(0, 15))
        
        # Buttons
        btn_frame = ctk.CTkFrame(content, fg_color="transparent")
        btn_frame.pack(fill="x")
        
        refresh_btn = ctk.CTkButton(
            btn_frame,
            text="🔄  Refresh",
            command=self._on_refresh,
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
        
        # Escape to close
        self.root.bind("<Escape>", lambda e: self.root.destroy())
    
    def _on_refresh(self):
        if not self.api_callback:
            return
        
        try:
            data = self.api_callback()
            
            # Clear existing entries
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
                    
                    # Entry row
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


# ------------------------------------------------------------
# System Tray Controller
# ------------------------------------------------------------
class TimeTrackerSystemTray:
    """Main system tray controller with modern UI"""
    
    def __init__(self):
        self.client_mgr = ClientManager()
        self.state = GUIState()
        
        # Callbacks
        self.on_client_confirmed_callback = None
        self.on_client_rejected_callback = None
        self.get_today_time_callback = None
        self.get_ai_guess_callback = None
        self.fetch_clients_callback = None
        self.set_current_client_callback = None
        self.get_current_client_callback = None
        
        self.icon = None
        # Toast disabled - win10toast causes WNDPROC errors with pystray
        # self.toaster = ToastNotifier() if TOAST_AVAILABLE else None
        
        self._start_ai_timer()
    
    def _start_ai_timer(self):
        """Start periodic AI suggestion check"""
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
        """Show AI prompt if conditions are met"""
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
            else:
                # Fallback to basic prompt
                pass
        
        threading.Thread(target=show, daemon=True).start()
    
    def _on_prompt_response(self, confirmed: bool, client_id: Optional[int],
                           client_name: Optional[str], prompt_data: dict):
        if confirmed and client_id and client_name:
            self.state.set_client(client_id, client_name)
            print(f"[GUI] Client confirmed: {client_name}")
            
            if self.set_current_client_callback:
                self.set_current_client_callback(client_id)
            
            if self.on_client_confirmed_callback:
                self.on_client_confirmed_callback(client_id, client_name, prompt_data)
            # Menu rebuilds automatically on next click via callable
        else:
            print(f"[GUI] Client rejected")
            if self.on_client_rejected_callback:
                self.on_client_rejected_callback(prompt_data)
    
    def _create_image(self):
        """Create beautiful system tray icon"""
        size = 64
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Draw rounded rectangle background
        draw.rounded_rectangle(
            [(4, 4), (size-4, size-4)],
            radius=12,
            fill=COLORS["tray_bg"]
        )
        
        # Draw clock icon (circle with hands)
        center = size // 2
        radius = 18
        
        # Clock face
        draw.ellipse(
            [(center - radius, center - radius), 
             (center + radius, center + radius)],
            outline='white',
            width=3
        )
        
        # Hour hand
        draw.line([(center, center), (center, center - 10)], fill='white', width=3)
        # Minute hand
        draw.line([(center, center), (center + 8, center)], fill='white', width=2)
        
        return img
        
    def _build_menu_items(self):
        """Build system tray menu items (returns tuple for pystray callable)"""
        # Current client header
        client_display = self.state.current_client_name or "No Client"
        
        # Quick switch submenu
        def make_switch_handler(cid, cname):
            def handler(icon, item):
                # Schedule work and return immediately to avoid WNDPROC errors
                threading.Thread(target=lambda: self._switch_client(cid, cname), daemon=True).start()
            return handler

        clients = sort_clients_by_usage(self.client_mgr.get_all())
        
        # Show only first 10 clients in menu, rest via search
        client_items = [Item("Clear Client", make_switch_handler(0, "No Client"))]
        
        for client in clients[:10]:  # Limit to 10
            client_id = client["id"]
            client_name = client["name"]
            is_current = client_id == self.state.current_client_id
            prefix = "● " if is_current else "   "
            client_items.append(
                Item(f"{prefix}{client_name}", make_switch_handler(client_id, client_name))
            )
        
        if len(clients) > 10:
            client_items.append(Item(f"... and {len(clients) - 10} more (use Search)", None, enabled=False))
        
        def on_search(icon, item):
            threading.Timer(0.05, self._show_client_picker).start()
        
        def on_today(icon, item):
            threading.Timer(0.05, self._on_today_time).start()
        
        def on_quit(icon, item):
            self._on_quit()
        
        return (
            Item(f"⏱  {client_display}", None, enabled=False),
            Item("─" * 20, None, enabled=False),
            Item("🔍  Search Clients...", on_search),
            Item("Switch Client", pystray.Menu(*client_items)),
            Item("📊  Today's Time...", on_today),
            Item("─" * 20, None, enabled=False),
            Item("Quit", on_quit),
        )

    def _show_client_picker(self):
        """Show searchable client picker in subprocess to avoid threading issues"""
        import multiprocessing
        
        # Serialize data for subprocess
        clients_json = json.dumps(self.client_mgr.get_all())
        current_id = self.state.current_client_id
        
        result_queue = multiprocessing.Queue()
        
        p = multiprocessing.Process(
            target=_run_client_picker_process,
            args=(clients_json, current_id, result_queue)
        )
        p.start()
        p.join(timeout=60)
        
        if p.is_alive():
            p.terminate()
            return
        
        try:
            selected_id, selected_name = result_queue.get(timeout=1)
            if selected_id is not None or selected_name == "No Client":
                self._switch_client(selected_id or 0, selected_name)
        except:
            pass
    
    def _switch_client(self, client_id: int, client_name: str):
        """Handle client switch"""
        # Track usage
        track_client_selection(client_id)
        
        if client_id == 0:
            self.state.set_client(None, "No Client")
            print(f"[GUI] Client cleared")
        else:
            self.state.set_client(client_id, client_name)
            print(f"[GUI] Switched to client: {client_name}")
        
        if self.set_current_client_callback:
            try:
                self.set_current_client_callback(client_id if client_id else 0)
            except Exception as e:
                print(f"[GUI] Failed to sync client: {e}")
        
        # Toast disabled - win10toast causes WNDPROC errors with pystray
        # TODO: Replace with windows-toasts or winotify library
    
    def _on_today_time(self):
        """Show today's time window"""
        if MODERN_UI:
            window = TodayTimeWindowModern(self.get_today_time_callback)
        else:
            from timetracker_gui import TodayTimeWindow
            window = TodayTimeWindow(self.get_today_time_callback)
        window.show_and_refresh()
    
    def _on_quit(self):
        """Quit the application"""
        if self.icon:
            self.icon.stop()
    
    def refresh_client_menu(self, clients):
        """Called by sync to update client list"""
        self.client_mgr.clients = clients
        self.client_mgr.save()
        # Menu rebuilds automatically on next click via callable
        print(f"[GUI] Refreshed client list with {len(clients)} clients")
    
    def run(self):
        """Start the system tray icon"""
        if not TRAY_AVAILABLE:
            print("[GUI] System tray not available")
            return
        
        self.icon = pystray.Icon(
            "timetracker",
            self._create_image(),
            "TimeTracker",
            menu=pystray.Menu(self._build_menu_items)  # Pass callable - rebuilds on each click
        )
        
        print("[GUI] System tray started")
        self.icon.run()

# ------------------------------------------------------------
# Searchable Client Picker
# ------------------------------------------------------------
class ClientPickerWindow:
    """Searchable client picker popup"""
    
    def __init__(self, client_mgr: ClientManager, on_select: Callable):
        self.client_mgr = client_mgr
        self.on_select = on_select
        self.all_clients = client_mgr.get_all()
        
        ctk.set_appearance_mode("dark")
        self.root = ctk.CTk()
        self.root.title("Switch Client")
        self.root.geometry("400x500")
        self.root.resizable(False, False)
        self.root.attributes('-topmost', True)
        
        # Center window
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - 200
        y = (self.root.winfo_screenheight() // 2) - 250
        self.root.geometry(f"+{x}+{y}")
        
        self._setup_ui()
        self._filter_clients("")
        
        # Focus search box
        self.search_var.set("")
        self.search_entry.focus_set()
    
    def _setup_ui(self):
        content = ctk.CTkFrame(self.root, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Header
        header = ctk.CTkLabel(
            content,
            text="🔍  Switch Client",
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w"
        )
        header.pack(fill="x", pady=(0, 15))
        
        # Search box
        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", lambda *args: self._on_search())
        
        self.search_entry = ctk.CTkEntry(
            content,
            textvariable=self.search_var,
            placeholder_text="Type to search...",
            height=45,
            font=ctk.CTkFont(size=14)
        )
        self.search_entry.pack(fill="x", pady=(0, 15))
        
        # Bindings
        self.search_entry.bind("<Return>", self._select_first)
        self.search_entry.bind("<Escape>", lambda e: self.root.destroy())
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.root.bind("<Button-1>", lambda e: self.search_entry.focus_set())
        
        # Results list
        self.results_frame = ctk.CTkScrollableFrame(content, corner_radius=10)
        self.results_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        # Clear client button
        clear_btn = ctk.CTkButton(
            content,
            text="Clear Client",
            command=lambda: self._select_client(0, "No Client"),
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_dark"],
            height=35
        )
        clear_btn.pack(fill="x")
    
    def _on_search(self):
        query = self.search_var.get()
        self._filter_clients(query)
    
    def _filter_clients(self, query: str):
        # Clear existing results
        for widget in self.results_frame.winfo_children():
            widget.destroy()
        
        query_lower = query.lower().strip()
        
        # Filter clients
        if query_lower:
            filtered = [c for c in self.all_clients 
                       if query_lower in c.get("name", "").lower() 
                       or query_lower in c.get("code", "").lower()]
        else:
            filtered = self.all_clients

        # Sort by usage (most selected first)
        filtered = sort_clients_by_usage(filtered)
        
        if not filtered:
            no_results = ctk.CTkLabel(
                self.results_frame,
                text="No clients found",
                font=ctk.CTkFont(size=13),
                text_color=COLORS["text_muted"]
            )
            no_results.pack(pady=20)
            return
        
        # Show filtered results
        for i, client in enumerate(filtered):
            self._create_client_row(client, is_first=(i == 0))
    
    def _create_client_row(self, client: dict, is_first: bool = False):
        client_id = client.get("id")
        client_name = client.get("name", "Unknown")
        client_code = client.get("code", "")
        
        # Display text with code if available
        display_text = f"{client_name}  ({client_code})" if client_code else client_name
        
        row = ctk.CTkButton(
            self.results_frame,
            text=display_text,
            command=lambda cid=client_id, cname=client_name: self._select_client(cid, cname),
            fg_color=COLORS["primary"] if is_first else "transparent",
            hover_color=COLORS["primary_hover"] if is_first else COLORS["bg_card"],
            corner_radius=8,
            height=45,
            anchor="w",
            font=ctk.CTkFont(size=14, weight="bold" if is_first else "normal")
        )
        row.pack(fill="x", pady=2, padx=5)
    
    def _select_first(self, event=None):
        """Select the first filtered result"""
        query_lower = self.search_var.get().lower().strip()
        if query_lower:
            filtered = [c for c in self.all_clients 
                       if query_lower in c.get("name", "").lower()
                       or query_lower in c.get("code", "").lower()]
        else:
            filtered = self.all_clients
        
        # Sort by usage
        filtered = sort_clients_by_usage(filtered)
        
        if filtered:
            self._selected_id = filtered[0]["id"]
            self._selected_name = filtered[0]["name"]
            self.root.destroy()
    
    def _select_client(self, client_id: int, client_name: str):
        self._selected_id = client_id
        self._selected_name = client_name
        self.root.destroy()

    def show(self):
        self._selected_id = None
        self._selected_name = None
        
        # Force focus to window and search box
        def grab_focus():
            try:
                self.root.lift()
                self.root.attributes('-topmost', True)
                self.root.focus_force()
                self.root.grab_set()
                self.search_entry.focus_set()
                self.search_entry.focus_force()
            except:
                pass
        
        self.root.after(50, grab_focus)
        self.root.after(200, grab_focus)
        self.root.after(500, grab_focus)
        
        self.root.mainloop()
        
        # After mainloop exits, call the callback safely
        if self._selected_id is not None or self._selected_name == "No Client":
            self.on_select(self._selected_id or 0, self._selected_name)

# ------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------
def run_gui_app(on_client_confirmed: Callable,
                on_client_rejected: Callable,
                get_today_time: Callable,
                get_ai_guess: Callable = None,
                fetch_clients: Callable = None,
                set_current_client: Callable = None,
                get_current_client: Callable = None,
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
    # Test
    def test_confirmed(cid, cname, data):
        print(f"Confirmed: {cname}")
    
    def test_rejected(data):
        print("Rejected")
    
    def test_today():
        return [
            {"client": "Acme Corp", "hours": 3.5},
            {"client": "Beta Industries", "hours": 2.0},
        ]
    
    tray = run_gui_app(test_confirmed, test_rejected, test_today)
    if tray:
        tray.run()