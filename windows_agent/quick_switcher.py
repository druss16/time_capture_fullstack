#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TimeTracker Quick Switcher - Spotlight-style client picker

Features:
- Global hotkey (Cmd+Shift+T on Mac, Ctrl+Shift+T on Windows)
- Fuzzy search with instant filtering
- Recent clients at top
- Keyboard-first navigation
- Sub-200ms popup time

Usage:
    from quick_switcher import QuickSwitcher, start_hotkey_listener
    
    switcher = QuickSwitcher(
        get_clients=lambda: [...],
        on_select=lambda id, name: ...,
        get_usage=lambda: {...}
    )
    
    # Start listening for Cmd+Shift+T
    start_hotkey_listener(switcher.show)
"""

import os
import sys
import json
import threading
import multiprocessing
from typing import Callable, List, Dict, Optional, Tuple
from datetime import datetime

# Set spawn method for macOS
try:
    multiprocessing.set_start_method('spawn', force=True)
except RuntimeError:
    pass

# ============================================================
# FUZZY MATCHING
# ============================================================

def fuzzy_match(query: str, text: str) -> Tuple[bool, int]:
    """
    Simple fuzzy matching - returns (matches, score).
    Higher score = better match.
    """
    if not query:
        return True, 0
    
    query = query.lower()
    text = text.lower()
    
    # Exact substring match (highest priority)
    if query in text:
        # Bonus for matching at start
        if text.startswith(query):
            return True, 1000 + (100 - len(text))
        return True, 500 + (100 - text.index(query))
    
    # Fuzzy: all query chars appear in order
    qi = 0
    score = 0
    last_match = -1
    
    for i, char in enumerate(text):
        if qi < len(query) and char == query[qi]:
            # Bonus for consecutive matches
            if last_match == i - 1:
                score += 10
            else:
                score += 5
            # Bonus for matching at word boundaries
            if i == 0 or text[i-1] in ' -_.':
                score += 15
            last_match = i
            qi += 1
    
    if qi == len(query):
        return True, score
    
    return False, 0


def filter_and_sort_clients(clients: List[Dict], query: str, 
                           usage: Dict[int, int]) -> List[Dict]:
    """Filter clients by query and sort by relevance + usage."""
    if not query.strip():
        # No query: sort by usage only
        return sorted(clients, key=lambda c: usage.get(c.get("id", 0), 0), reverse=True)
    
    # Filter and score
    scored = []
    for client in clients:
        name = client.get("name", "")
        code = client.get("code", "")
        
        match_name, score_name = fuzzy_match(query, name)
        match_code, score_code = fuzzy_match(query, code)
        
        if match_name or match_code:
            # Combine fuzzy score with usage
            usage_bonus = min(usage.get(client.get("id", 0), 0) * 2, 200)
            total_score = max(score_name, score_code) + usage_bonus
            scored.append((client, total_score))
    
    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)
    return [c for c, _ in scored]


# ============================================================
# QUICK SWITCHER SUBPROCESS
# ============================================================

def _run_quick_switcher_process(clients_json: str, usage_json: str, 
                                current_id: int, result_queue):
    """
    Run the quick switcher popup in a separate process.
    This avoids Tkinter threading issues with rumps.
    """
    import json
    import tkinter as tk
    
    try:
        import customtkinter as ctk
        USE_CTK = True
    except ImportError:
        USE_CTK = False
    
    # Parse data
    clients = json.loads(clients_json) if clients_json else []
    usage_data = json.loads(usage_json) if usage_json else {}
    usage_data = {int(k): v for k, v in usage_data.items()}
    
    # Colors - dark theme matching TimeTracker
    colors = {
        "bg_window": "#1A1A1A",
        "bg_input": "#2A2A2A", 
        "bg_item": "#252525",
        "bg_item_hover": "#333333",
        "bg_item_selected": "#14B8A6",
        "border": "#3A3A3A",
        "text_primary": "#FFFFFF",
        "text_secondary": "#888888",
        "text_muted": "#555555",
        "accent": "#14B8A6",
    }
    
    selected = {"id": None, "name": None}
    current_index = [0]  # Mutable for nested function access
    visible_clients = []
    item_widgets = []
    
    # Track after IDs for cleanup and shutdown flag
    after_ids = []
    shutting_down = [False]  # Mutable for nested function access
    
    # ---- Window Setup ----
    if USE_CTK:
        ctk.set_appearance_mode("dark")
        root = ctk.CTk()
    else:
        root = tk.Tk()
    
    root.title("")
    root.overrideredirect(True)  # No title bar - Spotlight style
    root.attributes('-topmost', True)
    
    # Window size
    WIDTH = 500
    MAX_HEIGHT = 400
    ITEM_HEIGHT = 44
    INPUT_HEIGHT = 50
    PADDING = 8
    
    # Center on screen
    root.withdraw()
    root.update_idletasks()
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    x = (screen_w // 2) - (WIDTH // 2)
    y = (screen_h // 3)  # Upper third of screen
    
    root.geometry(f"{WIDTH}x{INPUT_HEIGHT + PADDING * 2}+{x}+{y}")
    root.configure(bg=colors["bg_window"])
    
    # Ensure window gets focus and STAYS on top on macOS
    root.lift()
    root.attributes('-topmost', True)
    root.focus_force()
    
    # Keep it on top continuously (with proper cleanup)
    def stay_on_top():
        if shutting_down[0]:
            return
        try:
            if root.winfo_exists():
                root.lift()
                root.attributes('-topmost', True)
                after_id = root.after(100, stay_on_top)
                after_ids.append(after_id)
        except:
            pass
    
    after_ids.append(root.after(100, stay_on_top))
    
    # Add subtle shadow/border effect
    if USE_CTK:
        root.configure(fg_color=colors["bg_window"])
    
    # ---- Helper Functions ----
    def cancel_all_after():
        """Cancel all pending after callbacks."""
        shutting_down[0] = True
        for after_id in after_ids:
            try:
                root.after_cancel(after_id)
            except:
                pass
        after_ids.clear()
    
    def update_selection(new_index: int):
        """Update visual selection."""
        if not visible_clients:
            return
        
        new_index = max(0, min(new_index, len(visible_clients) - 1))
        old_index = current_index[0]
        current_index[0] = new_index
        
        # Update colors
        for i, (frame, name_lbl, code_lbl) in enumerate(item_widgets):
            if i == new_index:
                if USE_CTK:
                    frame.configure(fg_color=colors["bg_item_selected"])
                else:
                    frame.configure(bg=colors["bg_item_selected"])
            else:
                if USE_CTK:
                    frame.configure(fg_color=colors["bg_item"])
                else:
                    frame.configure(bg=colors["bg_item"])
        
        # Scroll into view if needed
        if item_widgets and new_index < len(item_widgets):
            item_widgets[new_index][0].update_idletasks()
    
    def confirm_selection():
        """Confirm current selection and close."""
        if visible_clients and 0 <= current_index[0] < len(visible_clients):
            client = visible_clients[current_index[0]]
            selected["id"] = client.get("id")
            selected["name"] = client.get("name")
        cancel_all_after()
        root.quit()
    
    def cancel():
        """Cancel and close."""
        selected["id"] = None
        selected["name"] = None
        cancel_all_after()
        root.quit()
    
    def rebuild_list(query: str = ""):
        """Rebuild the client list based on search query."""
        nonlocal visible_clients, item_widgets
        
        # Filter and sort
        visible_clients = filter_and_sort_clients(clients, query, usage_data)[:10]
        
        # Clear existing items
        for widget in results_frame.winfo_children():
            widget.destroy()
        item_widgets = []
        
        if not visible_clients:
            # No results message
            if USE_CTK:
                no_results = ctk.CTkLabel(
                    results_frame, 
                    text="No clients found",
                    font=ctk.CTkFont(size=13),
                    text_color=colors["text_muted"]
                )
            else:
                no_results = tk.Label(
                    results_frame,
                    text="No clients found",
                    font=("SF Pro Text", 13),
                    fg=colors["text_muted"],
                    bg=colors["bg_window"]
                )
            no_results.pack(pady=20)
            resize_window(1)
            return
        
        # Create items
        for i, client in enumerate(visible_clients):
            cid = client.get("id")
            cname = client.get("name", "Unknown")
            ccode = client.get("code", "")
            is_current = cid == current_id
            
            # Item frame
            if USE_CTK:
                item_frame = ctk.CTkFrame(
                    results_frame,
                    fg_color=colors["bg_item_selected"] if i == 0 else colors["bg_item"],
                    corner_radius=8,
                    height=ITEM_HEIGHT
                )
            else:
                item_frame = tk.Frame(
                    results_frame,
                    bg=colors["bg_item_selected"] if i == 0 else colors["bg_item"],
                    height=ITEM_HEIGHT
                )
            item_frame.pack(fill="x", pady=2, padx=4)
            item_frame.pack_propagate(False)
            
            # Inner content frame
            if USE_CTK:
                inner = ctk.CTkFrame(item_frame, fg_color="transparent")
            else:
                inner = tk.Frame(item_frame, bg=item_frame.cget("bg"))
            inner.pack(fill="both", expand=True, padx=12, pady=8)
            
            # Client name
            display_name = f"● {cname}" if is_current else cname
            if USE_CTK:
                name_label = ctk.CTkLabel(
                    inner,
                    text=display_name,
                    font=ctk.CTkFont(family="SF Pro Text", size=14, 
                                    weight="bold" if i < 3 else "normal"),
                    text_color=colors["text_primary"],
                    anchor="w"
                )
            else:
                name_label = tk.Label(
                    inner,
                    text=display_name,
                    font=("SF Pro Text", 14, "bold" if i < 3 else "normal"),
                    fg=colors["text_primary"],
                    bg=inner.cget("bg"),
                    anchor="w"
                )
            name_label.pack(side="left", fill="x", expand=True)
            
            # Client code (right side)
            code_label = None
            if ccode:
                if USE_CTK:
                    code_label = ctk.CTkLabel(
                        inner,
                        text=ccode,
                        font=ctk.CTkFont(family="SF Pro Text", size=12),
                        text_color=colors["accent"]
                    )
                else:
                    code_label = tk.Label(
                        inner,
                        text=ccode,
                        font=("SF Pro Text", 12),
                        fg=colors["accent"],
                        bg=inner.cget("bg")
                    )
                code_label.pack(side="right")
            
            item_widgets.append((item_frame, name_label, code_label))
            
            # Click handlers
            def make_click(idx):
                def handler(e):
                    update_selection(idx)
                return handler
            
            def make_dblclick(idx):
                def handler(e):
                    update_selection(idx)
                    confirm_selection()
                return handler
            
            # Bind to all widgets in the item
            for widget in [item_frame, inner, name_label] + ([code_label] if code_label else []):
                widget.bind("<Button-1>", make_click(i))
                widget.bind("<Double-Button-1>", make_dblclick(i))
            
            # Hover effects
            def make_hover(frame, idx):
                def enter(e):
                    if current_index[0] != idx:
                        if USE_CTK:
                            frame.configure(fg_color=colors["bg_item_hover"])
                        else:
                            frame.configure(bg=colors["bg_item_hover"])
                def leave(e):
                    if current_index[0] != idx:
                        if USE_CTK:
                            frame.configure(fg_color=colors["bg_item"])
                        else:
                            frame.configure(bg=colors["bg_item"])
                return enter, leave
            
            enter_fn, leave_fn = make_hover(item_frame, i)
            item_frame.bind("<Enter>", enter_fn)
            item_frame.bind("<Leave>", leave_fn)
        
        # Reset selection to first item
        current_index[0] = 0
        resize_window(len(visible_clients))
    
    def resize_window(num_items: int):
        """Resize window to fit content."""
        num_items = max(1, min(num_items, 10))
        content_height = INPUT_HEIGHT + PADDING * 2 + (num_items * (ITEM_HEIGHT + 4)) + 8
        content_height = min(content_height, MAX_HEIGHT)
        root.geometry(f"{WIDTH}x{content_height}+{x}+{y}")
    
    def on_search_change(*args):
        """Called when search text changes."""
        if shutting_down[0]:
            return
        query = search_var.get()
        rebuild_list(query)
    
    def on_key(event):
        """Handle keyboard navigation."""
        if event.keysym == "Down":
            update_selection(current_index[0] + 1)
            return "break"
        elif event.keysym == "Up":
            update_selection(current_index[0] - 1)
            return "break"
        elif event.keysym == "Return":
            confirm_selection()
            return "break"
        elif event.keysym == "Escape":
            cancel()
            return "break"
        # Allow typing in search box
        return None
    
    # ---- Build UI ----
    
    # Main container
    if USE_CTK:
        container = ctk.CTkFrame(root, fg_color=colors["bg_window"], corner_radius=12)
    else:
        container = tk.Frame(root, bg=colors["bg_window"])
    container.pack(fill="both", expand=True, padx=1, pady=1)
    
    # Search input
    search_var = tk.StringVar() if not USE_CTK else ctk.StringVar()
    
    if USE_CTK:
        search_frame = ctk.CTkFrame(container, fg_color="transparent")
        search_frame.pack(fill="x", padx=PADDING, pady=(PADDING, 4))
        
        search_entry = ctk.CTkEntry(
            search_frame,
            textvariable=search_var,
            placeholder_text="Search clients...",
            font=ctk.CTkFont(family="SF Pro Text", size=16),
            fg_color=colors["bg_input"],
            border_color=colors["border"],
            border_width=1,
            text_color=colors["text_primary"],
            placeholder_text_color=colors["text_muted"],
            height=INPUT_HEIGHT - 10,
            corner_radius=10
        )
    else:
        search_frame = tk.Frame(container, bg=colors["bg_window"])
        search_frame.pack(fill="x", padx=PADDING, pady=(PADDING, 4))
        
        search_entry = tk.Entry(
            search_frame,
            textvariable=search_var,
            font=("SF Pro Text", 16),
            bg=colors["bg_input"],
            fg=colors["text_primary"],
            insertbackground=colors["text_primary"],
            relief="flat",
            highlightthickness=1,
            highlightbackground=colors["border"],
            highlightcolor=colors["accent"]
        )
    
    search_entry.pack(fill="x", ipady=8 if not USE_CTK else 0)
    
    # Results frame
    if USE_CTK:
        results_frame = ctk.CTkFrame(container, fg_color="transparent")
    else:
        results_frame = tk.Frame(container, bg=colors["bg_window"])
    results_frame.pack(fill="both", expand=True, padx=4, pady=(0, PADDING))
    
    # ---- Bindings ----
    search_var.trace_add("write", on_search_change)
    
    # Explicit Escape binding (works even when search has focus)
    root.bind("<Escape>", lambda e: cancel())
    search_entry.bind("<Escape>", lambda e: cancel())
    
    # Arrow keys and Enter
    root.bind("<Down>", lambda e: update_selection(current_index[0] + 1))
    root.bind("<Up>", lambda e: update_selection(current_index[0] - 1))
    root.bind("<Return>", lambda e: confirm_selection())
    search_entry.bind("<Return>", lambda e: confirm_selection())
    
    # ---- Close button (top right) ----
    if USE_CTK:
        close_btn = ctk.CTkButton(
            container,
            text="✕",
            width=30,
            height=30,
            corner_radius=15,
            fg_color=colors["bg_item"],
            hover_color=colors["bg_item_hover"],
            text_color=colors["text_secondary"],
            command=cancel
        )
    else:
        close_btn = tk.Button(
            container,
            text="✕",
            width=3,
            bg=colors["bg_item"],
            fg=colors["text_secondary"],
            relief="flat",
            command=cancel
        )
    close_btn.place(relx=1.0, y=5, anchor="ne", x=-5)
    
    # ---- Initialize ----
    root.deiconify()
    rebuild_list("")
    
    # Force focus to search entry after a brief delay
    def focus_search():
        if shutting_down[0]:
            return
        try:
            search_entry.focus_force()
            root.lift()
            root.attributes('-topmost', True)
        except:
            pass
    
    after_ids.append(root.after(100, focus_search))
    
    # ---- Run ----
    root.mainloop()
    
    # Cleanup: cancel any remaining after callbacks before destroy
    cancel_all_after()
    
    # Process exits here - no need to destroy, OS cleans up

    
    # Return result
    result_queue.put((selected["id"], selected["name"]))


# ============================================================
# QUICK SWITCHER CLASS
# ============================================================

class QuickSwitcher:
    """
    Spotlight-style quick client switcher.
    
    Usage:
        switcher = QuickSwitcher(
            get_clients=lambda: client_manager.get_all(),
            on_select=lambda id, name: switch_client(id, name),
            get_usage=lambda: load_client_usage()
        )
        
        switcher.show()  # Opens the popup
    """
    
    def __init__(self, 
                 get_clients: Callable[[], List[Dict]],
                 on_select: Callable[[int, str], None],
                 get_usage: Callable[[], Dict[int, int]] = None,
                 get_current_id: Callable[[], Optional[int]] = None):
        """
        Args:
            get_clients: Function returning list of client dicts with 'id', 'name', 'code'
            on_select: Callback when client is selected (client_id, client_name)
            get_usage: Optional function returning {client_id: usage_count} dict
            get_current_id: Optional function returning current client ID
        """
        self.get_clients = get_clients
        self.on_select = on_select
        self.get_usage = get_usage or (lambda: {})
        self.get_current_id = get_current_id or (lambda: None)
        
        self._showing = False
        self._lock = threading.Lock()
    
    def show(self):
        """Show the quick switcher popup."""
        with self._lock:
            if self._showing:
                return
            self._showing = True
        
        try:
            self._show_impl()
        finally:
            with self._lock:
                self._showing = False
    
    def _show_impl(self):
        """Internal implementation of show."""
        # Gather data
        clients = self.get_clients() or []
        usage = self.get_usage() or {}
        current_id = self.get_current_id()
        
        # Serialize for subprocess
        clients_json = json.dumps(clients)
        usage_json = json.dumps(usage)
        
        # Run in subprocess
        result_queue = multiprocessing.Queue()
        
        p = multiprocessing.Process(
            target=_run_quick_switcher_process,
            args=(clients_json, usage_json, current_id, result_queue)
        )
        p.start()
        p.join(timeout=60)  # 1 minute timeout
        
        if p.is_alive():
            p.terminate()
            print("[QuickSwitcher] Timeout")
            return
        
        # Get result
        try:
            selected_id, selected_name = result_queue.get(timeout=1)
            if selected_id is not None and selected_name is not None:
                print(f"[QuickSwitcher] Selected: {selected_name} (id={selected_id})")
                self.on_select(selected_id, selected_name)
        except Exception as e:
            print(f"[QuickSwitcher] No selection or error: {e}")


# ============================================================
# GLOBAL HOTKEY LISTENER (macOS)
# ============================================================

_hotkey_callback = None
_hotkey_thread = None
_hotkey_stop = threading.Event()

def _mac_hotkey_listener(callback: Callable, stop_event: threading.Event):
    """
    Listen for Cmd+Shift+T on macOS using PyObjC.
    """
    try:
        from AppKit import NSEvent, NSApplication, NSApp
        from Quartz import (
            CGEventTapCreate, CGEventTapEnable,
            kCGSessionEventTap, kCGHeadInsertEventTap,
            kCGEventTapOptionDefault, kCGEventKeyDown,
            CGEventGetIntegerValueField, kCGKeyboardEventKeycode,
            CGEventGetFlags, kCGEventFlagMaskCommand, kCGEventFlagMaskShift,
            CFMachPortCreateRunLoopSource, CFRunLoopGetCurrent,
            CFRunLoopAddSource, kCFRunLoopCommonModes, CFRunLoopRun,
            CFRunLoopStop
        )
        from PyObjCTools import AppHelper
        import Quartz
    except ImportError as e:
        print(f"[Hotkey] PyObjC not available: {e}")
        return
    
    # Key code for 'T' on US keyboard
    KEY_T = 17
    
    def callback_wrapper(proxy, event_type, event, refcon):
        try:
            if event_type == kCGEventKeyDown:
                keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
                flags = CGEventGetFlags(event)
                
                # Check for Cmd+Shift+T
                cmd_pressed = (flags & kCGEventFlagMaskCommand) != 0
                shift_pressed = (flags & kCGEventFlagMaskShift) != 0
                
                if keycode == KEY_T and cmd_pressed and shift_pressed:
                    print("[Hotkey] Cmd+Shift+T detected!")
                    # Call callback in separate thread to not block
                    threading.Thread(target=callback, daemon=True).start()
                    # Return None to consume the event (optional)
                    # return None
        except Exception as e:
            print(f"[Hotkey] Error in callback: {e}")
        
        return event
    
    # Create event tap
    mask = 1 << kCGEventKeyDown
    
    tap = CGEventTapCreate(
        kCGSessionEventTap,
        kCGHeadInsertEventTap,
        kCGEventTapOptionDefault,
        mask,
        callback_wrapper,
        None
    )
    
    if tap is None:
        print("[Hotkey] Failed to create event tap. Need Accessibility permissions.")
        print("[Hotkey] Go to System Settings → Privacy & Security → Accessibility")
        print("[Hotkey] and add this application.")
        return
    
    # Add to run loop
    source = CFMachPortCreateRunLoopSource(None, tap, 0)
    CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes)
    CGEventTapEnable(tap, True)
    
    print("[Hotkey] Listening for Cmd+Shift+T...")
    
    # Run loop (blocks until stopped)
    while not stop_event.is_set():
        # Process events for a short time, then check stop flag
        Quartz.CFRunLoopRunInMode(kCFRunLoopCommonModes, 0.5, False)
    
    print("[Hotkey] Stopped")


def _fallback_hotkey_listener(callback: Callable, stop_event: threading.Event):
    """
    Fallback hotkey listener using pynput (cross-platform).
    """
    try:
        from pynput import keyboard
    except ImportError:
        print("[Hotkey] pynput not available. Install with: pip install pynput")
        return
    
    # Track modifier state
    current_keys = set()
    
    def on_press(key):
        if stop_event.is_set():
            return False
        
        current_keys.add(key)
        
        # Check for Cmd/Ctrl + Shift + T
        cmd_or_ctrl = (
            keyboard.Key.cmd in current_keys or 
            keyboard.Key.cmd_l in current_keys or
            keyboard.Key.cmd_r in current_keys or
            keyboard.Key.ctrl in current_keys or
            keyboard.Key.ctrl_l in current_keys or
            keyboard.Key.ctrl_r in current_keys
        )
        shift = (
            keyboard.Key.shift in current_keys or
            keyboard.Key.shift_l in current_keys or
            keyboard.Key.shift_r in current_keys
        )
        
        try:
            t_pressed = hasattr(key, 'char') and key.char and key.char.lower() == 't'
        except:
            t_pressed = False
        
        if cmd_or_ctrl and shift and t_pressed:
            print("[Hotkey] Cmd/Ctrl+Shift+T detected!")
            threading.Thread(target=callback, daemon=True).start()
    
    def on_release(key):
        if stop_event.is_set():
            return False
        current_keys.discard(key)
    
    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        print("[Hotkey] Listening for Cmd/Ctrl+Shift+T (pynput)...")
        while not stop_event.is_set():
            stop_event.wait(0.5)


def start_hotkey_listener(callback: Callable, use_fallback: bool = False) -> bool:
    """
    Start listening for global hotkey.
    - Mac: Cmd+Shift+T (native or pynput fallback)
    - Windows: Ctrl+Shift+T (pynput or keyboard library)
    
    Args:
        callback: Function to call when hotkey is pressed
        use_fallback: If True, use pynput instead of native macOS API
    
    Returns:
        True if listener started successfully
    """
    global _hotkey_callback, _hotkey_thread, _hotkey_stop
    
    if _hotkey_thread is not None and _hotkey_thread.is_alive():
        print("[Hotkey] Already running")
        return True
    
    _hotkey_callback = callback
    _hotkey_stop.clear()
    
    if sys.platform == 'darwin' and not use_fallback:
        _hotkey_thread = threading.Thread(
            target=_mac_hotkey_listener,
            args=(callback, _hotkey_stop),
            daemon=True
        )
        hotkey_desc = "Cmd+Shift+T (native)"
    elif sys.platform == 'win32':
        # Try keyboard library first on Windows (more reliable)
        _hotkey_thread = threading.Thread(
            target=_windows_hotkey_listener,
            args=(callback, _hotkey_stop),
            daemon=True
        )
        hotkey_desc = "Ctrl+Shift+T (Windows)"
    else:
        _hotkey_thread = threading.Thread(
            target=_fallback_hotkey_listener,
            args=(callback, _hotkey_stop),
            daemon=True
        )
        hotkey_desc = "Ctrl+Shift+T (pynput)"
    
    _hotkey_thread.start()
    print(f"[Hotkey] Listening for {hotkey_desc}")
    return True


def _windows_hotkey_listener(callback: Callable, stop_event: threading.Event):
    """
    Windows-specific hotkey listener using keyboard library.
    Falls back to pynput if keyboard not available.
    """
    # Try keyboard library first (better Windows support)
    try:
        import keyboard
        
        print("[Hotkey] Using keyboard library for Ctrl+Shift+T")
        
        def on_hotkey():
            print("[Hotkey] Ctrl+Shift+T detected!")
            threading.Thread(target=callback, daemon=True).start()
        
        keyboard.add_hotkey('ctrl+shift+t', on_hotkey, suppress=False)
        
        while not stop_event.is_set():
            stop_event.wait(0.5)
        
        keyboard.remove_hotkey('ctrl+shift+t')
        return
        
    except ImportError:
        print("[Hotkey] keyboard library not available, trying pynput...")
    
    # Fallback to pynput
    _fallback_hotkey_listener(callback, stop_event)


def stop_hotkey_listener():
    """Stop the global hotkey listener."""
    global _hotkey_stop, _hotkey_thread
    
    _hotkey_stop.set()
    if _hotkey_thread is not None:
        _hotkey_thread.join(timeout=2)
        _hotkey_thread = None


# ============================================================
# TESTING
# ============================================================

if __name__ == "__main__":
    # Test data
    test_clients = [
        {"id": 1, "name": "Acme Corporation", "code": "ACME"},
        {"id": 2, "name": "Beta Industries LLC", "code": "BETA"},
        {"id": 3, "name": "Gamma Holdings", "code": "GAMM"},
        {"id": 4, "name": "Delta Partners", "code": "DLTA"},
        {"id": 5, "name": "Smith & Associates CPA", "code": "SMTH"},
        {"id": 6, "name": "Johnson Family Trust", "code": "JFAM"},
        {"id": 7, "name": "Tech Startup Inc", "code": "TECH"},
        {"id": 8, "name": "Local Restaurant Group", "code": "LRST"},
        {"id": 9, "name": "Manufacturing Co", "code": "MFGC"},
        {"id": 10, "name": "Healthcare Solutions", "code": "HLTH"},
    ]
    
    test_usage = {1: 50, 2: 30, 5: 100, 7: 25}  # Smith most used
    
    def on_select(client_id, client_name):
        print(f"\n✅ Selected: {client_name} (ID: {client_id})")
    
    # Test QuickSwitcher
    switcher = QuickSwitcher(
        get_clients=lambda: test_clients,
        on_select=on_select,
        get_usage=lambda: test_usage,
        get_current_id=lambda: 2  # Beta is current
    )
    
    print("=" * 50)
    print("Quick Switcher Test")
    print("=" * 50)
    print("\nPress Cmd+Shift+T to open (or wait for manual test)...")
    
    # Start hotkey listener
    start_hotkey_listener(switcher.show, use_fallback=True)
    
    # Also show immediately for testing
    import time
    time.sleep(1)
    print("\nOpening quick switcher directly for testing...")
    switcher.show()
    
    print("\nTest complete. Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_hotkey_listener()
        print("\nExiting.")