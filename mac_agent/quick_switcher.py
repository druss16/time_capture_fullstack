#!/usr/bin/env python3
"""
TimeTracker Quick Switcher - Clean Tkinter version

Hotkey: Ctrl+Option+T (handled in main.py via NSEvent monitors)
"""

import os
import sys
import json
import threading
import subprocess
from typing import Callable, List, Dict, Optional, Tuple


def fuzzy_match(query: str, text: str) -> Tuple[bool, int]:
    """Simple fuzzy matching - returns (matches, score)."""
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
    last_match = -1
    
    for i, char in enumerate(text):
        if qi < len(query) and char == query[qi]:
            if last_match == i - 1:
                score += 10
            else:
                score += 5
            if i == 0 or text[i-1] in ' -_.':
                score += 15
            last_match = i
            qi += 1
    
    if qi == len(query):
        return True, score
    
    return False, 0


# Standalone picker script - runs in subprocess
PICKER_SCRIPT = r'''
import sys
import json
import tkinter as tk
from tkinter import font as tkfont

def run_picker(clients_json, usage_json, current_id):
    clients = json.loads(clients_json) if clients_json else []
    usage = json.loads(usage_json) if usage_json else {}
    usage = {int(k): v for k, v in usage.items()}
    
    result = {"id": None, "name": None}
    selected_index = [0]
    filtered = [clients[:]]
    
    # Colors
    BG = "#1e1e1e"
    BG_INPUT = "#2d2d2d"
    BG_ITEM = "#2d2d2d"
    BG_SELECTED = "#0d9488"
    BG_HOVER = "#3d3d3d"
    FG = "#ffffff"
    FG_DIM = "#888888"
    ACCENT = "#14b8a6"
    
    root = tk.Tk()
    root.title("Switch Client")
    root.configure(bg=BG)
    root.overrideredirect(False)
    
    # Size and center
    width, height = 420, 380
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    x = (screen_w - width) // 2
    y = (screen_h - height) // 3
    root.geometry(f"{width}x{height}+{x}+{y}")
    root.minsize(400, 300)
    
    # FORCE MACOS TO ACTIVATE THIS PROCESS
    try:
        from AppKit import NSApplication, NSApp, NSRunningApplication, NSApplicationActivateIgnoringOtherApps
        NSApplication.sharedApplication()
        NSApp.activateIgnoringOtherApps_(True)
        # Also activate the current app
        current = NSRunningApplication.currentApplication()
        current.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
    except Exception as e:
        print(f"AppKit activation failed: {e}")
    
    # Fonts
    try:
        font_main = tkfont.Font(family="SF Pro Text", size=13)
        font_title = tkfont.Font(family="SF Pro Text", size=14, weight="bold")
        font_code = tkfont.Font(family="SF Mono", size=11)
        font_small = tkfont.Font(family="SF Pro Text", size=11)
    except:
        font_main = tkfont.Font(family="Helvetica", size=13)
        font_title = tkfont.Font(family="Helvetica", size=14, weight="bold")
        font_code = tkfont.Font(family="Courier", size=11)
        font_small = tkfont.Font(family="Helvetica", size=11)
    
    # Focus handling
    root.attributes("-topmost", True)
    root.lift()
    root.focus_force()
    
    # Main container
    main = tk.Frame(root, bg=BG, padx=15, pady=15)
    main.pack(fill="both", expand=True)
    
    # Title
    title_frame = tk.Frame(main, bg=BG)
    title_frame.pack(fill="x", pady=(0, 10))
    
    title_lbl = tk.Label(title_frame, text="Switch Client", font=font_title, bg=BG, fg=FG)
    title_lbl.pack(side="left")
    
    hint_lbl = tk.Label(title_frame, text="↑↓ navigate • Enter select • Esc cancel", 
                        font=font_small, bg=BG, fg=FG_DIM)
    hint_lbl.pack(side="right")
    
    # Search
    search_frame = tk.Frame(main, bg=BG_INPUT, highlightbackground=ACCENT, 
                           highlightthickness=2, highlightcolor=ACCENT)
    search_frame.pack(fill="x", pady=(0, 10))
    
    search_var = tk.StringVar()
    search = tk.Entry(
        search_frame,
        textvariable=search_var,
        font=font_main,
        bg=BG_INPUT,
        fg=FG,
        insertbackground=FG,
        relief="flat",
        bd=8
    )
    search.pack(fill="x")
    search.insert(0, "")  # Start empty
    search.focus_set()
    
    # Click anywhere to ensure focus
    def on_click(e):
        search.focus_set()
    root.bind("<Button-1>", on_click)
    
    # When mouse enters window, focus search
    def on_enter(e):
        root.focus_force()
        search.focus_set()
    root.bind("<Enter>", on_enter)
    
    # Results area
    results_outer = tk.Frame(main, bg=BG)
    results_outer.pack(fill="both", expand=True)
    
    canvas = tk.Canvas(results_outer, bg=BG, highlightthickness=0, bd=0)
    scrollbar = tk.Scrollbar(results_outer, orient="vertical", command=canvas.yview)
    results_frame = tk.Frame(canvas, bg=BG)
    
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    
    canvas_window = canvas.create_window((0, 0), window=results_frame, anchor="nw")
    
    def on_frame_configure(e):
        canvas.configure(scrollregion=canvas.bbox("all"))
    results_frame.bind("<Configure>", on_frame_configure)
    
    def on_canvas_configure(e):
        canvas.itemconfig(canvas_window, width=e.width)
    canvas.bind("<Configure>", on_canvas_configure)
    
    # Mouse wheel scrolling
    def on_mousewheel(e):
        canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
    canvas.bind_all("<MouseWheel>", on_mousewheel)
    
    item_frames = []
    
    def confirm():
        if filtered[0] and 0 <= selected_index[0] < len(filtered[0]):
            c = filtered[0][selected_index[0]]
            result["id"] = c.get("id")
            result["name"] = c.get("name")
        root.quit()
    
    def cancel():
        root.quit()
    
    def update_selection(new_idx):
        if not filtered[0]:
            return
        new_idx = max(0, min(new_idx, len(filtered[0]) - 1))
        selected_index[0] = new_idx
        
        for i, (frame, inner, name_lbl, code_lbl) in enumerate(item_frames):
            if i == new_idx:
                frame.configure(bg=BG_SELECTED)
                inner.configure(bg=BG_SELECTED)
                name_lbl.configure(bg=BG_SELECTED)
                if code_lbl:
                    code_lbl.configure(bg=BG_SELECTED)
                # Scroll into view
                frame.update_idletasks()
                y = frame.winfo_y()
                h = frame.winfo_height()
                canvas_h = canvas.winfo_height()
                frame_h = results_frame.winfo_height()
                if frame_h > 0:
                    target = max(0, min(1, (y - canvas_h//2 + h//2) / frame_h))
                    canvas.yview_moveto(target)
            else:
                frame.configure(bg=BG_ITEM)
                inner.configure(bg=BG_ITEM)
                name_lbl.configure(bg=BG_ITEM)
                if code_lbl:
                    code_lbl.configure(bg=BG_ITEM)
    
    def rebuild_list(query=""):
        nonlocal item_frames
        
        for w in results_frame.winfo_children():
            w.destroy()
        item_frames = []
        
        # Filter and sort
        if not query.strip():
            filtered[0] = sorted(clients, key=lambda c: usage.get(c.get("id", 0), 0), reverse=True)[:12]
        else:
            query_lower = query.lower()
            scored = []
            for c in clients:
                name = c.get("name", "").lower()
                code = c.get("code", "").lower()
                if query_lower in name:
                    score = 200 if name.startswith(query_lower) else 100
                    scored.append((c, score + usage.get(c.get("id", 0), 0)))
                elif query_lower in code:
                    scored.append((c, 50 + usage.get(c.get("id", 0), 0)))
            scored.sort(key=lambda x: x[1], reverse=True)
            filtered[0] = [c for c, _ in scored[:12]]
        
        if not filtered[0]:
            lbl = tk.Label(results_frame, text="No clients found", font=font_main, bg=BG, fg=FG_DIM)
            lbl.pack(pady=30)
            return
        
        for i, client in enumerate(filtered[0]):
            cid = client.get("id")
            cname = client.get("name", "Unknown")
            ccode = client.get("code", "")
            is_current = cid == current_id
            
            bg_color = BG_SELECTED if i == 0 else BG_ITEM
            
            frame = tk.Frame(results_frame, bg=bg_color, cursor="hand2")
            frame.pack(fill="x", pady=2)
            
            inner = tk.Frame(frame, bg=bg_color, padx=12, pady=10)
            inner.pack(fill="x")
            
            name_text = f"● {cname}" if is_current else cname
            name_lbl = tk.Label(inner, text=name_text, font=font_main, bg=bg_color, fg=FG, anchor="w")
            name_lbl.pack(side="left", fill="x", expand=True)
            
            code_lbl = None
            if ccode:
                code_lbl = tk.Label(inner, text=ccode, font=font_code, bg=bg_color, fg=ACCENT)
                code_lbl.pack(side="right")
            
            item_frames.append((frame, inner, name_lbl, code_lbl))
            
            # Click handlers
            def make_click(idx):
                def handler(e):
                    update_selection(idx)
                return handler
            
            def make_dblclick(idx):
                def handler(e):
                    update_selection(idx)
                    confirm()
                return handler
            
            # Hover
            def make_enter(idx, f, inn, nlbl, clbl):
                def handler(e):
                    if selected_index[0] != idx:
                        f.configure(bg=BG_HOVER)
                        inn.configure(bg=BG_HOVER)
                        nlbl.configure(bg=BG_HOVER)
                        if clbl:
                            clbl.configure(bg=BG_HOVER)
                return handler
            
            def make_leave(idx, f, inn, nlbl, clbl):
                def handler(e):
                    if selected_index[0] != idx:
                        f.configure(bg=BG_ITEM)
                        inn.configure(bg=BG_ITEM)
                        nlbl.configure(bg=BG_ITEM)
                        if clbl:
                            clbl.configure(bg=BG_ITEM)
                return handler
            
            for widget in [frame, inner, name_lbl] + ([code_lbl] if code_lbl else []):
                widget.bind("<Button-1>", make_click(i))
                widget.bind("<Double-Button-1>", make_dblclick(i))
            
            frame.bind("<Enter>", make_enter(i, frame, inner, name_lbl, code_lbl))
            frame.bind("<Leave>", make_leave(i, frame, inner, name_lbl, code_lbl))
        
        selected_index[0] = 0
    
    def on_key(event):
        if event.keysym == "Down":
            update_selection(selected_index[0] + 1)
            return "break"
        elif event.keysym == "Up":
            update_selection(selected_index[0] - 1)
            return "break"
        elif event.keysym == "Return":
            confirm()
            return "break"
        elif event.keysym == "Escape":
            cancel()
            return "break"
    
    def on_search_change(*args):
        rebuild_list(search_var.get())
    
    search_var.trace_add("write", on_search_change)
    root.bind("<Down>", on_key)
    root.bind("<Up>", on_key)
    root.bind("<Return>", on_key)
    root.bind("<Escape>", on_key)
    search.bind("<Down>", on_key)
    search.bind("<Up>", on_key)
    
    # Any other key press focuses search and types there
    def on_any_key(e):
        if e.keysym not in ('Down', 'Up', 'Return', 'Escape', 'Tab', 'Shift_L', 'Shift_R', 'Control_L', 'Control_R', 'Alt_L', 'Alt_R', 'Meta_L', 'Meta_R'):
            search.focus_set()
            # Insert the character
            if e.char and e.char.isprintable():
                search.insert('end', e.char)
                return "break"
    root.bind("<Key>", on_any_key)
    
    # Cancel button
    btn_frame = tk.Frame(main, bg=BG)
    btn_frame.pack(fill="x", pady=(10, 0))
    
    cancel_btn = tk.Button(
        btn_frame,
        text="Cancel",
        command=cancel,
        font=font_small,
        bg=BG_ITEM,
        fg=FG_DIM,
        activebackground=BG_HOVER,
        activeforeground=FG,
        relief="flat",
        padx=20,
        pady=5,
        cursor="hand2"
    )
    cancel_btn.pack(side="right")
    
    # Init
    rebuild_list("")
    
    def focus_later():
        root.lift()
        root.attributes("-topmost", True)
        root.focus_force()
        search.focus_set()
        search.focus_force()
        # Try activating again
        try:
            from AppKit import NSApp
            NSApp.activateIgnoringOtherApps_(True)
        except:
            pass
        # Also try osascript to bring window to front
        try:
            import subprocess as sp
            sp.Popen(['osascript', '-e', 'tell application "System Events" to set frontmost of every process whose name contains "Python" to true'], stdout=sp.DEVNULL, stderr=sp.DEVNULL)
        except:
            pass
    
    root.after(50, focus_later)
    root.after(150, focus_later)
    root.after(300, focus_later)
    root.after(500, focus_later)
    
    # Final activation before mainloop
    try:
        from AppKit import NSApp
        NSApp.activateIgnoringOtherApps_(True)
    except:
        pass
    
    root.mainloop()
    
    try:
        root.destroy()
    except:
        pass
    
    return result

if __name__ == "__main__":
    clients_json = sys.argv[1] if len(sys.argv) > 1 else "[]"
    usage_json = sys.argv[2] if len(sys.argv) > 2 else "{}"
    current_id = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isdigit() else 0
    
    result = run_picker(clients_json, usage_json, current_id)
    print(json.dumps(result))
'''


class QuickSwitcher:
    """Spotlight-style quick client switcher."""
    
    def __init__(self, 
                 get_clients: Callable[[], List[Dict]],
                 on_select: Callable[[int, str], None],
                 get_usage: Callable[[], Dict[int, int]] = None,
                 get_current_id: Callable[[], Optional[int]] = None):
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
        """Run picker in subprocess."""
        import tempfile
        
        clients = self.get_clients() or []
        usage = self.get_usage() or {}
        current_id = self.get_current_id() or 0
        
        # Write script to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(PICKER_SCRIPT)
            script_path = f.name
        
        try:
            result = subprocess.run(
                [sys.executable, script_path, 
                 json.dumps(clients), 
                 json.dumps(usage), 
                 str(current_id)],
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout.strip())
                if data.get("id") and data.get("name"):
                    print(f"[QuickSwitcher] Selected: {data['name']} (id={data['id']})")
                    self.on_select(data["id"], data["name"])
        except subprocess.TimeoutExpired:
            print("[QuickSwitcher] Timeout")
        except Exception as e:
            print(f"[QuickSwitcher] Error: {e}")
        finally:
            try:
                os.unlink(script_path)
            except:
                pass


# Compatibility stubs
def start_hotkey_listener(callback: Callable, use_fallback: bool = False) -> bool:
    return False

def stop_hotkey_listener():
    pass


if __name__ == "__main__":
    test_clients = [
        {"id": 1, "name": "Acme Corporation", "code": "ACME"},
        {"id": 2, "name": "Beta Industries LLC", "code": "BETA"},
        {"id": 3, "name": "Smith & Associates CPA", "code": "SMTH"},
        {"id": 4, "name": "Johnson Family Trust", "code": "JFAM"},
        {"id": 5, "name": "Tech Startup Inc", "code": "TECH"},
        {"id": 6, "name": "Local Restaurant Group", "code": "REST"},
        {"id": 7, "name": "Healthcare Solutions", "code": "HLTH"},
    ]
    
    def on_select(cid, name):
        print(f"\n✅ Selected: {name} (ID: {cid})")
    
    switcher = QuickSwitcher(
        get_clients=lambda: test_clients,
        on_select=on_select,
        get_usage=lambda: {3: 100, 1: 50, 5: 25},
        get_current_id=lambda: 2
    )
    
    print("Opening picker...")
    switcher.show()
    print("Done")