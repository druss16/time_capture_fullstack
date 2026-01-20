#!/usr/bin/env python3
"""
Modern client picker using CustomTkinter with ROBUST Windows focus handling
"""

import os
import sys
import json
import threading
import ctypes
from ctypes import wintypes

try:
    import customtkinter as ctk
    CTK_AVAILABLE = True
except ImportError:
    CTK_AVAILABLE = False
    print("CustomTkinter not available. Install with: pip install customtkinter")

CLIENT_USAGE_FILE = os.path.expanduser("~/.timetracker/client_usage.json")

# Colors matching main theme
COLORS = {
    "bg_window": "#1A1A1A",
    "bg_input": "#2A2A2A", 
    "bg_item": "#252525",
    "bg_item_hover": "#333333",
    "bg_item_selected": "#14B8A6",
    "border": "#3A3A3A",
    "text_primary": "#FFFFFF",
    "text_secondary": "#888888",
    "text_muted": "#666666",
    "accent": "#14B8A6",
}

# Windows API constants
SW_RESTORE = 9
SW_SHOW = 5
GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008


def load_usage():
    if os.path.exists(CLIENT_USAGE_FILE):
        try:
            with open(CLIENT_USAGE_FILE, 'r') as f:
                return {int(k): v for k, v in json.load(f).items()}
        except:
            pass
    return {}


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
        
        # Get current foreground window's thread
        foreground_hwnd = user32.GetForegroundWindow()
        foreground_thread = user32.GetWindowThreadProcessId(foreground_hwnd, None)
        current_thread = ctypes.windll.kernel32.GetCurrentThreadId()

        
        # Attach to foreground thread to steal focus
        if foreground_thread != current_thread:
            user32.AttachThreadInput(foreground_thread, current_thread, True)
        
        # Restore if minimized
        user32.ShowWindow(hwnd, SW_RESTORE)
        
        # Bring to top
        user32.BringWindowToTop(hwnd)
        
        # Set as foreground
        user32.SetForegroundWindow(hwnd)
        
        # Set focus
        user32.SetFocus(hwnd)
        
        # Detach threads
        if foreground_thread != current_thread:
            user32.AttachThreadInput(foreground_thread, current_thread, False)
        
        return True
    except Exception as e:
        print(f"[Focus] Error: {e}")
        return False


def show_client_picker(clients: list, current_id: int = None, on_select=None):
    """Show the client picker dialog with robust Windows focus"""
    if not CTK_AVAILABLE:
        print("CustomTkinter not available!")
        return None, None
    
    # Release any held hotkey keys first
    try:
        import keyboard
        keyboard.release('alt')
        keyboard.release('shift')
        keyboard.release('t')
        keyboard.release('ctrl')
    except:
        pass
    
    import time
    time.sleep(0.05)
    
    # Allow this process to set foreground window
    try:
        ctypes.windll.user32.AllowSetForegroundWindow(-1)
    except:
        pass
    
    # Sort clients by usage
    usage_data = load_usage()
    sorted_clients = sorted(
        clients,
        key=lambda c: usage_data.get(c.get("id", 0), 0),
        reverse=True
    )
    
    # State
    selected = {"id": None, "name": None}
    current_index = [0]
    visible_clients = []
    item_widgets = []
    shutting_down = [False]
    after_ids = []
    
    # Unique window title for finding HWND
    WINDOW_TITLE = "Switch Client"
    
    def fuzzy_match(query, text):
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
    
    def filter_clients(query):
        if not query.strip():
            return sorted_clients[:15]
        scored = []
        for client in sorted_clients:
            name = client.get("name", "")
            code = client.get("code", "")
            match_name, score_name = fuzzy_match(query, name)
            match_code, score_code = fuzzy_match(query, code)
            if match_name or match_code:
                usage_bonus = min(usage_data.get(client.get("id", 0), 0) * 2, 200)
                total_score = max(score_name, score_code) + usage_bonus
                scored.append((client, total_score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [c for c, _ in scored][:15]
    
    def cancel_all_after():
        shutting_down[0] = True
        for after_id in after_ids:
            try:
                root.after_cancel(after_id)
            except:
                pass
        after_ids.clear()
    
    def update_selection(new_index):
        if not visible_clients:
            return
        new_index = max(0, min(new_index, len(visible_clients) - 1))
        current_index[0] = new_index
        for i, (frame, name_lbl, code_lbl) in enumerate(item_widgets):
            if i == new_index:
                frame.configure(fg_color=COLORS["bg_item_selected"])
            else:
                frame.configure(fg_color=COLORS["bg_item"])
    
    def confirm_selection():
        if visible_clients and 0 <= current_index[0] < len(visible_clients):
            client = visible_clients[current_index[0]]
            selected["id"] = client.get("id")
            selected["name"] = client.get("name")
        cancel_all_after()
        root.quit()
    
    def cancel():
        selected["id"] = None
        selected["name"] = None
        cancel_all_after()
        root.quit()
    
    def clear_client():
        selected["id"] = 0
        selected["name"] = "No Client"
        cancel_all_after()
        root.quit()
    
    def rebuild_list(query=""):
        nonlocal visible_clients, item_widgets
        
        visible_clients = filter_clients(query)
        
        for widget in results_frame.winfo_children():
            widget.destroy()
        item_widgets = []
        
        if not visible_clients:
            no_results = ctk.CTkLabel(
                results_frame, 
                text="No clients found",
                font=ctk.CTkFont(size=13),
                text_color=COLORS["text_muted"]
            )
            no_results.pack(pady=20)
            resize_window(1)
            return
        
        for i, client in enumerate(visible_clients):
            cid = client.get("id")
            cname = client.get("name", "Unknown")
            ccode = client.get("code", "")
            is_current = cid == current_id
            
            item_frame = ctk.CTkFrame(
                results_frame,
                fg_color=COLORS["bg_item_selected"] if i == 0 else COLORS["bg_item"],
                corner_radius=8,
                height=ITEM_HEIGHT
            )
            item_frame.pack(fill="x", pady=2, padx=4)
            item_frame.pack_propagate(False)
            
            inner = ctk.CTkFrame(item_frame, fg_color="transparent")
            inner.pack(fill="both", expand=True, padx=12, pady=8)
            
            display_name = f"● {cname}" if is_current else cname
            name_label = ctk.CTkLabel(
                inner,
                text=display_name,
                font=ctk.CTkFont(family="Segoe UI", size=14, 
                                weight="bold" if i < 3 else "normal"),
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
            
            item_widgets.append((item_frame, name_label, code_label))
            
            def make_click(idx):
                def handler(e):
                    update_selection(idx)
                return handler
            
            def make_dblclick(idx):
                def handler(e):
                    update_selection(idx)
                    confirm_selection()
                return handler
            
            for widget in [item_frame, inner, name_label] + ([code_label] if code_label else []):
                widget.bind("<Button-1>", make_click(i))
                widget.bind("<Double-Button-1>", make_dblclick(i))
            
            def make_hover(frame, idx):
                def enter(e):
                    if current_index[0] != idx:
                        frame.configure(fg_color=COLORS["bg_item_hover"])
                def leave(e):
                    if current_index[0] != idx:
                        frame.configure(fg_color=COLORS["bg_item"])
                return enter, leave
            
            enter_fn, leave_fn = make_hover(item_frame, i)
            item_frame.bind("<Enter>", enter_fn)
            item_frame.bind("<Leave>", leave_fn)
        
        current_index[0] = 0
        resize_window(len(visible_clients))
    
    def resize_window(num_items):
        num_items = max(1, min(num_items, 12))
        content_height = INPUT_HEIGHT + PADDING * 2 + (num_items * (ITEM_HEIGHT + 4)) + 100
        content_height = min(content_height, MAX_HEIGHT)
        root.geometry(f"{WIDTH}x{content_height}+{x}+{y}")
    
    def on_search_change(*args):
        if shutting_down[0]:
            return
        query = search_var.get()
        rebuild_list(query)
    
    # Window setup
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    root.title(WINDOW_TITLE)
    root.attributes('-topmost', True)
    
    try:
        root.attributes('-alpha', 0.98)
    except:
        pass
    
    # Dimensions
    WIDTH = 450
    MAX_HEIGHT = 550
    ITEM_HEIGHT = 48
    INPUT_HEIGHT = 50
    PADDING = 12
    
    root.update_idletasks()
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    x = (screen_w // 2) - (WIDTH // 2)
    y = (screen_h // 3)
    
    root.geometry(f"{WIDTH}x{INPUT_HEIGHT + PADDING * 2}+{x}+{y}")
    root.configure(fg_color=COLORS["bg_window"])
    
    # Build UI
    container = ctk.CTkFrame(root, fg_color=COLORS["bg_window"], corner_radius=12)
    container.pack(fill="both", expand=True, padx=1, pady=1)
    
    # Header
    header_frame = ctk.CTkFrame(container, fg_color="transparent")
    header_frame.pack(fill="x", padx=PADDING, pady=(PADDING, 8))
    
    header_label = ctk.CTkLabel(
        header_frame,
        text="🔍  Switch Client",
        font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold"),
        text_color=COLORS["text_primary"]
    )
    header_label.pack(side="left")
    
    # Close button
    close_btn = ctk.CTkButton(
        header_frame,
        text="✕",
        width=30,
        height=30,
        corner_radius=15,
        fg_color=COLORS["bg_item"],
        hover_color=COLORS["bg_item_hover"],
        text_color=COLORS["text_secondary"],
        command=cancel
    )
    close_btn.pack(side="right")
    
    # Search input
    search_var = ctk.StringVar()
    
    search_frame = ctk.CTkFrame(container, fg_color="transparent")
    search_frame.pack(fill="x", padx=PADDING, pady=(0, 8))
    
    search_entry = ctk.CTkEntry(
        search_frame,
        textvariable=search_var,
        placeholder_text="Type to search...",
        font=ctk.CTkFont(family="Segoe UI", size=15),
        fg_color=COLORS["bg_input"],
        border_color=COLORS["accent"],
        border_width=2,
        text_color=COLORS["text_primary"],
        placeholder_text_color=COLORS["text_muted"],
        height=INPUT_HEIGHT - 5,
        corner_radius=10
    )
    search_entry.pack(fill="x")
    
    # Results frame
    results_frame = ctk.CTkScrollableFrame(container, fg_color="transparent")
    results_frame.pack(fill="both", expand=True, padx=4, pady=(0, 8))
    
    # Clear client button
    clear_btn = ctk.CTkButton(
        container,
        text="Clear Client",
        command=clear_client,
        fg_color=COLORS["bg_item"],
        hover_color=COLORS["bg_item_hover"],
        text_color=COLORS["text_secondary"],
        height=35,
        corner_radius=8
    )
    clear_btn.pack(fill="x", padx=PADDING, pady=(0, PADDING))
    
    # Bindings
    search_var.trace_add("write", on_search_change)
    
    search_entry.bind("<Escape>", lambda e: cancel())
    search_entry.bind("<Return>", lambda e: confirm_selection())
    search_entry.bind("<Down>", lambda e: [update_selection(current_index[0] + 1), "break"][1])
    search_entry.bind("<Up>", lambda e: [update_selection(current_index[0] - 1), "break"][1])
    
    root.bind("<Escape>", lambda e: cancel())
    root.bind("<Return>", lambda e: confirm_selection())
    root.bind("<Down>", lambda e: update_selection(current_index[0] + 1))
    root.bind("<Up>", lambda e: update_selection(current_index[0] - 1))
    
    # Initialize list
    rebuild_list("")
    
    # === ROBUST FOCUS HANDLING ===
    def force_focus():
        if shutting_down[0]:
            return
        try:
            # Ensure window is visible
            root.deiconify()
            root.state('normal')
            root.lift()
            root.attributes('-topmost', True)
            root.update()
            
            # Get HWND by window title (more reliable than winfo_id)
            hwnd = get_hwnd_by_title(WINDOW_TITLE)
            if hwnd:
                force_window_to_foreground(hwnd)
            
            # Tkinter focus
            root.focus_force()
            
            # Focus the CTK entry's internal widget
            if hasattr(search_entry, '_entry'):
                search_entry._entry.focus_set()
                search_entry._entry.focus_force()
                search_entry._entry.icursor('end')
            else:
                search_entry.focus_set()
            
        except Exception as e:
            print(f"[Picker] Focus error: {e}")
    
    # Multiple aggressive focus attempts at different intervals
    for delay in [10, 50, 100, 150, 200, 300, 400, 500]:
        after_ids.append(root.after(delay, force_focus))
    
    # Keep window on top
    def stay_on_top():
        if shutting_down[0]:
            return
        try:
            if root.winfo_exists():
                root.lift()
                root.attributes('-topmost', True)
                after_id = root.after(300, stay_on_top)
                after_ids.append(after_id)
        except:
            pass
    
    after_ids.append(root.after(100, stay_on_top))
    
    # Run mainloop
    root.mainloop()
    cancel_all_after()
    
    try:
        root.destroy()
    except:
        pass
    
    # Callback
    if on_select and (selected["id"] is not None or selected["name"] == "No Client"):
        on_select(selected["id"], selected["name"])
    
    return selected.get("id"), selected.get("name")


if __name__ == "__main__":
    if not CTK_AVAILABLE:
        print("Install CustomTkinter: pip install customtkinter")
        sys.exit(1)
    
    # Load real clients if available
    clients_file = os.path.expanduser("~/.timetracker/clients.json")
    if os.path.exists(clients_file):
        with open(clients_file) as f:
            test_clients = json.load(f)
        print(f"Loaded {len(test_clients)} clients")
    else:
        test_clients = [
            {"id": 1, "name": "Acme Corporation", "code": "ACME"},
            {"id": 2, "name": "Beta Industries", "code": "BETA"},
            {"id": 3, "name": "55 Twin Lane", "code": "55TWINLA"},
            {"id": 4, "name": "Barnett Design", "code": "BARNETTDE"},
            {"id": 5, "name": "Cool Cars", "code": "COOLCARS"},
        ]
    
    def on_select(cid, cname):
        print(f"Selected: {cname} (ID: {cid})")
    
    cid, cname = show_client_picker(test_clients, current_id=3, on_select=on_select)
    print(f"Result: {cname} ({cid})")