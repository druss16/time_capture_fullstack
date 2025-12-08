#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TimeTracker Windows System Tray GUI

Features:
- System tray icon with menu
- Client switching
- AI client prompts (tkinter dialogs)
- Client management window
- Today's time viewer
- Backend sync integration
"""

import os
import json
import threading
import time as _time
from datetime import datetime
from typing import Optional, List, Dict, Callable
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

# System tray
try:
    import pystray
    from PIL import Image, ImageDraw
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

# ------------------------------------------------------------
# Client Manager
# ------------------------------------------------------------
class ClientManager:
    """Manages the list of clients (stored locally with backend sync)"""
    
    def __init__(self):
        self.clients: List[Dict] = []
        self.load()
    
    def load(self, fetch_callback=None):
        """Load clients from backend if available, otherwise use local cache"""
        # Try to fetch from backend first
        if fetch_callback:
            try:
                backend_clients = fetch_callback()
                if backend_clients and isinstance(backend_clients, list):
                    self.clients = backend_clients
                    self.save()  # Cache them locally
                    print(f"[GUI] Loaded {len(self.clients)} clients from backend")
                    return
            except Exception as e:
                print(f"[GUI] Failed to fetch clients from backend: {e}")
        
        # Fall back to local cache
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
    
    def add(self, name: str, code: str = "") -> Dict:
        max_id = max([c.get("id", 0) for c in self.clients], default=0)
        new_client = {
            "id": max_id + 1,
            "name": name.strip(),
            "code": (code or name[:4]).strip().upper()
        }
        self.clients.append(new_client)
        self.save()
        return new_client
    
    def update(self, client_id: int, name: str, code: str):
        for c in self.clients:
            if c.get("id") == client_id:
                c["name"] = name.strip()
                c["code"] = code.strip().upper()
                self.save()
                return True
        return False
    
    def delete(self, client_id: int):
        self.clients = [c for c in self.clients if c.get("id") != client_id]
        self.save()

# ------------------------------------------------------------
# GUI State
# ------------------------------------------------------------
class GUIState:
    """Manages GUI state (current client, etc.)"""
    
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
# AI Prompt Dialog
# ------------------------------------------------------------
def show_client_prompt(client_id: int, client_name: str, confidence: float, 
                       callback: Callable, client_mgr: ClientManager):
    """Show AI suggestion dialog using tkinter"""
    
    result = {"confirmed": False, "client_id": None, "client_name": None}
    
    def on_yes():
        result["confirmed"] = True
        result["client_id"] = client_id
        result["client_name"] = client_name
        root.destroy()
    
    def on_no():
        result["confirmed"] = False
        root.destroy()
    
    def on_select():
        selected = combo.get()
        client = client_mgr.get_by_name(selected)
        if client:
            result["confirmed"] = True
            result["client_id"] = client["id"]
            result["client_name"] = client["name"]
        root.destroy()
    
    root = tk.Tk()
    root.title("Time Tracker")
    root.geometry("400x200")
    root.resizable(False, False)
    
    # Keep window on top
    root.attributes('-topmost', True)
    
    # Question label
    question = tk.Label(root, text="Are you working on this client?", font=("Arial", 10))
    question.pack(pady=(15, 5))
    
    # Client name with confidence
    client_label = tk.Label(root, text=f"{client_name} ({int(confidence * 100)}% confidence)", 
                           font=("Arial", 12, "bold"))
    client_label.pack(pady=5)
    
    # Yes/No buttons
    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=10)
    
    yes_btn = tk.Button(btn_frame, text="✓ Yes", command=on_yes, width=10, 
                       bg="#4CAF50", fg="white", font=("Arial", 10, "bold"))
    yes_btn.pack(side=tk.LEFT, padx=5)
    
    no_btn = tk.Button(btn_frame, text="✗ No", command=on_no, width=10,
                      bg="#f44336", fg="white", font=("Arial", 10, "bold"))
    no_btn.pack(side=tk.LEFT, padx=5)
    
    # Or select different client
    or_label = tk.Label(root, text="Or select a different client:", font=("Arial", 9))
    or_label.pack(pady=(10, 5))
    
    select_frame = tk.Frame(root)
    select_frame.pack(pady=5)
    
    client_names = [c["name"] for c in client_mgr.get_all()]
    combo = ttk.Combobox(select_frame, values=client_names, width=30, state="readonly")
    if client_names:
        combo.current(0)
    combo.pack(side=tk.LEFT, padx=5)
    
    select_btn = tk.Button(select_frame, text="Select", command=on_select, width=10)
    select_btn.pack(side=tk.LEFT, padx=5)
    
    # Timeout after 15 seconds
    def timeout():
        if root.winfo_exists():
            root.destroy()
    
    root.after(15000, timeout)
    
    # Center window
    root.update_idletasks()
    x = (root.winfo_screenwidth() // 2) - (root.winfo_width() // 2)
    y = (root.winfo_screenheight() // 2) - (root.winfo_height() // 2)
    root.geometry(f'+{x}+{y}')
    
    root.mainloop()
    
    # Call callback with result
    if result["confirmed"]:
        callback(True, result["client_id"], result["client_name"], {})
    else:
        callback(False, None, None, {})

# ------------------------------------------------------------
# Client Management Window
# ------------------------------------------------------------
class ClientManagementWindow:
    """Window for managing clients (add/edit/delete)"""
    
    def __init__(self, client_mgr: ClientManager, callback: Callable = None):
        self.client_mgr = client_mgr
        self.callback = callback
        
        self.root = tk.Tk()
        self.root.title("Manage Clients")
        self.root.geometry("600x400")
        
        self._setup_ui()
        self._refresh_list()
    
    def _setup_ui(self):
        # Client list
        list_frame = tk.Frame(self.root)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, font=("Arial", 10))
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.listbox.yview)
        
        # Add new client
        add_frame = tk.Frame(self.root)
        add_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(add_frame, text="New Client:").pack(side=tk.LEFT, padx=5)
        
        self.name_entry = tk.Entry(add_frame, width=30)
        self.name_entry.pack(side=tk.LEFT, padx=5)
        
        tk.Label(add_frame, text="Code:").pack(side=tk.LEFT, padx=5)
        
        self.code_entry = tk.Entry(add_frame, width=10)
        self.code_entry.pack(side=tk.LEFT, padx=5)
        
        add_btn = tk.Button(add_frame, text="Add", command=self._on_add, width=8)
        add_btn.pack(side=tk.LEFT, padx=5)
        
        # Buttons
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        
        delete_btn = tk.Button(btn_frame, text="Delete Selected", command=self._on_delete)
        delete_btn.pack(side=tk.LEFT, padx=5)
        
        close_btn = tk.Button(btn_frame, text="Close", command=self.root.destroy)
        close_btn.pack(side=tk.RIGHT, padx=5)
    
    def _refresh_list(self):
        self.listbox.delete(0, tk.END)
        for client in self.client_mgr.get_all():
            self.listbox.insert(tk.END, f"{client['name']} ({client.get('code', '')})")
    
    def _on_add(self):
        name = self.name_entry.get().strip()
        code = self.code_entry.get().strip()
        
        if not name:
            messagebox.showwarning("Invalid Input", "Client name cannot be empty")
            return
        
        self.client_mgr.add(name, code)
        self._refresh_list()
        self.name_entry.delete(0, tk.END)
        self.code_entry.delete(0, tk.END)
        
        if self.callback:
            self.callback()
    
    def _on_delete(self):
        selection = self.listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a client to delete")
            return
        
        idx = selection[0]
        clients = self.client_mgr.get_all()
        if 0 <= idx < len(clients):
            client = clients[idx]
            if messagebox.askyesno("Confirm Delete", f"Delete client '{client['name']}'?"):
                self.client_mgr.delete(client["id"])
                self._refresh_list()
                
                if self.callback:
                    self.callback()
    
    def show(self):
        self.root.mainloop()

# ------------------------------------------------------------
# Today's Time Window
# ------------------------------------------------------------
class TodayTimeWindow:
    """Window showing today's tracked time by client"""
    
    def __init__(self, api_callback: Callable):
        self.api_callback = api_callback
        
        self.root = tk.Tk()
        self.root.title("Today's Time Tracking")
        self.root.geometry("600x400")
        
        self._setup_ui()
    
    def _setup_ui(self):
        # Date label
        date_str = datetime.now().strftime("%A, %B %d, %Y")
        date_label = tk.Label(self.root, text=date_str, font=("Arial", 12, "bold"))
        date_label.pack(pady=10)
        
        # Table
        table_frame = tk.Frame(self.root)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        scrollbar = tk.Scrollbar(table_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.tree = ttk.Treeview(table_frame, columns=("Client", "Hours"), show="headings",
                                 yscrollcommand=scrollbar.set)
        self.tree.heading("Client", text="Client")
        self.tree.heading("Hours", text="Hours")
        self.tree.column("Client", width=400)
        self.tree.column("Hours", width=150)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.tree.yview)
        
        # Total label
        self.total_label = tk.Label(self.root, text="Total: 0.0 hours", font=("Arial", 10))
        self.total_label.pack(pady=5)
        
        # Buttons
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        
        refresh_btn = tk.Button(btn_frame, text="Refresh", command=self._on_refresh)
        refresh_btn.pack(side=tk.LEFT, padx=5)
        
        close_btn = tk.Button(btn_frame, text="Close", command=self.root.destroy)
        close_btn.pack(side=tk.RIGHT, padx=5)
    
    def _on_refresh(self):
        if not self.api_callback:
            return
        
        try:
            data = self.api_callback()
            
            # Clear existing items
            for item in self.tree.get_children():
                self.tree.delete(item)
            
            # Add new items
            total_hours = 0.0
            for entry in data:
                client = entry.get("client", "Unknown")
                hours = entry.get("hours", 0)
                total_hours += hours
                self.tree.insert("", tk.END, values=(client, f"{hours:.2f}"))
            
            self.total_label.config(text=f"Total: {total_hours:.1f} hours")
        
        except Exception as e:
            messagebox.showerror("Error", f"Failed to fetch today's time: {e}")
    
    def show_and_refresh(self):
        self._on_refresh()
        self.root.mainloop()

# ------------------------------------------------------------
# System Tray Controller
# ------------------------------------------------------------
class TimeTrackerSystemTray:
    """Main system tray controller"""
    
    def __init__(self):
        self.client_mgr = ClientManager()
        self.state = GUIState()
        
        # External callbacks (set by run_gui_app)
        self.on_client_confirmed_callback = None
        self.on_client_rejected_callback = None
        self.get_today_time_callback = None
        self.get_ai_guess_callback = None
        self.fetch_clients_callback = None
        self.set_current_client_callback = None
        self.get_current_client_callback = None
        
        self.icon = None
        self.toaster = ToastNotifier() if TOAST_AVAILABLE else None
        
        # Periodic AI check
        self.ai_timer = None
        self._start_ai_timer()
    
    def _start_ai_timer(self):
        """Start periodic AI suggestion check"""
        def ai_tick():
            while True:
                _time.sleep(15)  # Check every 15 seconds
                try:
                    if self.get_ai_guess_callback:
                        guess = self.get_ai_guess_callback()
                        if guess and guess.get("client_id"):
                            self._maybe_show_prompt(guess)
                except Exception as e:
                    print(f"[AI] Error: {e}")
        
        self.ai_timer = threading.Thread(target=ai_tick, daemon=True)
        self.ai_timer.start()
    
    def _maybe_show_prompt(self, guess: dict):
        """Show AI prompt if conditions are met"""
        client_id = guess.get("client_id")
        client_name = guess.get("client_name")
        confidence = float(guess.get("confidence", 0))
        
        if not client_id or confidence < 0.45:
            return
        
        if confidence >= 0.80:  # Auto-assign
            return
        
        if self.state.current_client_id == client_id:
            return
        
        # Show prompt in separate thread
        def show():
            show_client_prompt(
                client_id, client_name, confidence,
                self._on_prompt_response,
                self.client_mgr
            )
        
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
        else:
            print(f"[GUI] Client rejected")
            if self.on_client_rejected_callback:
                self.on_client_rejected_callback(prompt_data)
    
    def _create_image(self):
        """Create system tray icon image"""
        # Simple blue square icon
        img = Image.new('RGB', (64, 64), color='#2196F3')
        draw = ImageDraw.Draw(img)
        # Add "TT" text
        draw.text((8, 20), "TT", fill='white')
        return img
    
    def _build_menu(self):
        """Build system tray menu"""
        menu_items = []
        
        # Current client (disabled, just for display)
        menu_items.append(Item(
            f"Client: {self.state.current_client_name}",
            lambda: None,
            enabled=False
        ))
        
        menu_items.append(Menu.SEPARATOR)
        
        # Switch Client submenu
        client_items = [
            Item("Clear Client", lambda: self._switch_client(0, "No Client"))
        ]
        
        for client in self.client_mgr.get_all():
            client_id = client["id"]
            client_name = client["name"]
            client_items.append(
                Item(client_name, lambda cid=client_id, cname=client_name: self._switch_client(cid, cname))
            )
        
        menu_items.append(Item("Switch Client", pystray.Menu(*client_items)))
        
        menu_items.append(Menu.SEPARATOR)
        
        # Management options
        # menu_items.append(Item("Manage Clients...", self._on_manage_clients))
        menu_items.append(Item("Today's Time...", self._on_today_time))
        
        menu_items.append(Menu.SEPARATOR)
        
        # Quit
        menu_items.append(Item("Quit", self._on_quit))
        
        return pystray.Menu(*menu_items)
    
    def _switch_client(self, client_id: int, client_name: str):
        """Handle client switch"""
        if client_id == 0:
            self.state.set_client(None, "No Client")
            print(f"[GUI] Client cleared")
            
            if self.set_current_client_callback:
                try:
                    self.set_current_client_callback(0)
                except Exception as e:
                    print(f"[GUI] Failed to clear client on backend: {e}")
        else:
            self.state.set_client(client_id, client_name)
            print(f"[GUI] Switched to client: {client_name}")
            
            if self.set_current_client_callback:
                try:
                    self.set_current_client_callback(client_id)
                except Exception as e:
                    print(f"[GUI] Failed to sync client to backend: {e}")
        
        # Update menu
        self.icon.menu = self._build_menu()
    
    def _on_manage_clients(self):
        """Show client management window"""
        def show():
            window = ClientManagementWindow(self.client_mgr, self._on_clients_changed)
            window.show()
        
        threading.Thread(target=show, daemon=True).start()
    
    def _on_today_time(self):
        """Show today's time window"""
        def show():
            window = TodayTimeWindow(self.get_today_time_callback)
            window.show_and_refresh()
        
        threading.Thread(target=show, daemon=True).start()
    
    def _on_clients_changed(self):
        """Called when clients list changes"""
        # Reload from backend if available
        if self.fetch_clients_callback:
            try:
                self.client_mgr.load(self.fetch_clients_callback)
            except Exception:
                pass
        
        # Update menu
        if self.icon:
            self.icon.menu = self._build_menu()
    
    def _on_quit(self):
        """Quit the application"""
        if self.icon:
            self.icon.stop()
    
    def run(self):
        """Start the system tray icon"""
        if not TRAY_AVAILABLE:
            print("[GUI] System tray not available")
            return
        
        self.icon = pystray.Icon(
            "timetracker",
            self._create_image(),
            "TimeTracker",
            menu=self._build_menu()
        )
        
        self.icon.run()

# ------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------
def run_gui_app(on_client_confirmed: Callable,
                on_client_rejected: Callable,
                get_today_time: Callable,
                get_ai_guess: Callable = None,
                fetch_clients: Callable = None,
                set_current_client: Callable = None,
                get_current_client: Callable = None):
    """
    Start the GUI system tray app with backend sync.
    """
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
    
    # Load clients from backend
    if fetch_clients:
        try:
            tray.client_mgr.load(fetch_clients)
        except Exception as e:
            print(f"[GUI] Failed to load clients: {e}")
    
    # Restore client state from backend
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
    
    return tray

if __name__ == "__main__":
    # Standalone test
    def test_confirmed(client_id, client_name, data):
        print(f"Test: Confirmed {client_name}")
    
    def test_rejected(data):
        print("Test: Rejected")
    
    def test_get_today():
        return [
            {"client": "Acme Corp", "hours": 3.5},
            {"client": "Beta Industries", "hours": 2.0},
        ]
    
    tray = run_gui_app(test_confirmed, test_rejected, test_get_today)
    if tray:
        tray.run()
