#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Floating Client Widget - Always visible current client indicator

Mac-style minimal pinned toolbar:
- Frameless always-on-top pill, sits just above the Windows taskbar
- Shows current client name only (no "switch" hint, no extra chrome)
- Click anywhere on it → opens the client picker
- Drag to move; snaps to screen edges; position persists
- Auto-fades to 55% opacity when not hovered, 98% on hover
- Collapsible to icon-only mode (kept for backward compatibility)
- Hide via × → reappears via "Show Client Widget" tray menu

Public API (preserved from prior version, used by gui_systemtray.py and main.py):
    WIDGET_AVAILABLE: bool
    FloatingClientWidget: class
        .create(parent_root=None) -> root window or None
        .run()                   -> blocking mainloop
        .update_client(id, name) -> updates display
        .show()                  -> deiconify + persist visible=True
        .destroy()               -> cleanup
        .root                    -> the CTk window (or CTkToplevel)
        .is_visible              -> bool
        ._save_state()           -> persist position/visibility
    create_floating_widget(tray_controller) -> FloatingClientWidget | None
"""

import os
import json
import threading
import time as _time

try:
    import customtkinter as ctk
    WIDGET_AVAILABLE = True
except ImportError:
    WIDGET_AVAILABLE = False


# Colors matching the app theme
COLORS = {
    "primary": "#14B8A6",
    "primary_dark": "#0D9488",
    "bg_dark": "#1A1A1A",
    "bg_card": "#252525",
    "text": "#FFFFFF",
    "text_muted": "#888888",
    "no_client": "#EF4444",
}

WIDGET_STATE_FILE = os.path.expanduser("~/.timetracker/widget_state.json")

# ---- Geometry / behavior tunables ----
WIDGET_WIDTH = 200
WIDGET_HEIGHT = 36
COLLAPSED_WIDTH = 45
COLLAPSED_HEIGHT = 35

EDGE_SNAP_THRESHOLD = 24      # px — snap when within this distance of an edge
TASKBAR_CLEARANCE = 56        # px above bottom edge so widget clears taskbar
DEFAULT_MARGIN = 12           # px from edge for default position

# Opacity behavior — Mac-like "out of the way" feel
OPACITY_IDLE = 0.55
OPACITY_HOVER = 0.98
FADE_DELAY_MS = 1500          # ms after mouseleave before fading

# Drag detection — clicks under this pixel threshold open the picker
DRAG_THRESHOLD_PX = 4

# Background polling interval for client updates (matches old behavior)
POLL_INTERVAL_S = 2.0


class FloatingClientWidget:
    """Mac-style minimal pinned client toolbar for Windows."""

    def __init__(self, on_click_callback=None, get_client_callback=None):
        """
        Args:
            on_click_callback: Called when user clicks the widget (opens picker)
            get_client_callback: Returns {"client_id": int, "client_name": str}
        """
        self.on_click = on_click_callback
        self.get_client = get_client_callback

        self.root = None
        self.is_collapsed = False
        self.is_visible = True

        # Drag state — measure motion to distinguish click from drag
        self._press_x = 0
        self._press_y = 0
        self._drag_offset_x = 0
        self._drag_offset_y = 0
        self._drag_started = False

        # Fade state
        self._fade_after_id = None

        # Polling thread
        self._update_running = False

        self.current_client_name = "No Client"
        self.current_client_id = None

        # Saved-state defaults (overwritten by _load_state)
        self.saved_x = None
        self.saved_y = None

        self._load_state()

    # ------------------------------------------------------------------
    # Persisted state
    # ------------------------------------------------------------------
    def _load_state(self):
        """Load widget position and collapse state from disk."""
        if os.path.exists(WIDGET_STATE_FILE):
            try:
                with open(WIDGET_STATE_FILE, 'r') as f:
                    state = json.load(f)
                    self.saved_x = state.get('x')
                    self.saved_y = state.get('y')
                    self.is_collapsed = state.get('collapsed', False)
                    self.is_visible = state.get('visible', True)
            except Exception:
                pass

    def _save_state(self):
        """Save widget position and collapse state to disk."""
        try:
            os.makedirs(os.path.dirname(WIDGET_STATE_FILE), exist_ok=True)
            x = self.root.winfo_x() if (self.root and self._root_alive()) else self.saved_x
            y = self.root.winfo_y() if (self.root and self._root_alive()) else self.saved_y
            state = {
                'x': x,
                'y': y,
                'collapsed': self.is_collapsed,
                'visible': self.is_visible,
            }
            with open(WIDGET_STATE_FILE, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            print(f"[WIDGET] Failed to save state: {e}")

    def _root_alive(self):
        try:
            return bool(self.root) and bool(self.root.winfo_exists())
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def create(self, parent_root=None):
        if not WIDGET_AVAILABLE:
            print("[WIDGET] customtkinter not available")
            return None

        # Reset visibility to True on create — explicit show() / hide() controls it
        self.is_visible = True
        ctk.set_appearance_mode("dark")

        if parent_root:
            self.root = ctk.CTkToplevel(parent_root)
        else:
            self.root = ctk.CTk()

        self.root.title("TimeTracker")
        self.root.overrideredirect(True)         # no title bar
        self.root.attributes('-topmost', True)   # always on top

        # Keep out of Alt+Tab
        try:
            self.root.attributes('-toolwindow', True)
        except Exception:
            pass

        # Initial size
        if self.is_collapsed:
            w, h = COLLAPSED_WIDTH, COLLAPSED_HEIGHT
        else:
            w, h = WIDGET_WIDTH, WIDGET_HEIGHT

        # Initial position — saved, otherwise bottom-right above taskbar
        x, y = self._compute_initial_position(w, h)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        self._build_ui()
        self._apply_opacity(OPACITY_IDLE)
        self._start_update_loop()

        return self.root

    def run(self):
        """Run the widget mainloop (call from main thread)."""
        if self.root:
            self.root.mainloop()

    def destroy(self):
        """Clean up the widget."""
        self._update_running = False
        self._save_state()
        if self.root:
            try:
                self.root.destroy()
            except Exception:
                pass
            self.root = None

    # ------------------------------------------------------------------
    # Positioning
    # ------------------------------------------------------------------
    def _compute_initial_position(self, w, h):
        """Use saved position if valid, else bottom-right above taskbar."""
        try:
            self.root.update_idletasks()
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
        except Exception:
            screen_w, screen_h = 1920, 1080  # safe defaults

        if self.saved_x is not None and self.saved_y is not None:
            x = max(0, min(self.saved_x, screen_w - w))
            y = max(0, min(self.saved_y, screen_h - h))
            return x, y

        # Default: bottom-right, just above the taskbar
        x = screen_w - w - DEFAULT_MARGIN
        y = screen_h - h - TASKBAR_CLEARANCE
        return x, y

    def _snap_to_edges(self, x, y, w, h):
        """Snap to nearest screen edge if within threshold."""
        try:
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
        except Exception:
            return x, y

        if x < EDGE_SNAP_THRESHOLD:
            x = DEFAULT_MARGIN
        elif x + w > screen_w - EDGE_SNAP_THRESHOLD:
            x = screen_w - w - DEFAULT_MARGIN

        if y < EDGE_SNAP_THRESHOLD:
            y = DEFAULT_MARGIN
        elif y + h > screen_h - EDGE_SNAP_THRESHOLD:
            y = screen_h - h - TASKBAR_CLEARANCE

        return x, y

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        """Build the minimal Mac-style UI."""
        # Outer container — gives us the rounded "card" look + accent border
        self.container = ctk.CTkFrame(
            self.root,
            fg_color=COLORS["bg_card"],
            corner_radius=10,
            border_width=1,
            border_color=COLORS["primary"],
        )
        self.container.pack(fill="both", expand=True, padx=2, pady=2)

        # Inner content — keeps the body separate from the close button
        self.content = ctk.CTkFrame(self.container, fg_color="transparent")
        self.content.pack(fill="both", expand=True, padx=4, pady=2)

        # Accent dot (also acts as the "collapsed" icon)
        self.icon_label = ctk.CTkLabel(
            self.content,
            text="●",
            font=ctk.CTkFont(family="Segoe UI", size=14),
            text_color=COLORS["primary"],
            width=14,
            cursor="hand2",
        )
        self.icon_label.pack(side="left", padx=(8, 6))

        # Client name label
        self.client_label = ctk.CTkLabel(
            self.content,
            text=self._truncate(self.current_client_name),
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=COLORS["text"],
            anchor="w",
            cursor="hand2",
        )
        if not self.is_collapsed:
            self.client_label.pack(side="left", fill="x", expand=True, padx=(0, 6))

        # Close (hide) button — only widget in expanded mode
        self.close_btn = ctk.CTkLabel(
            self.content,
            text="×",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_muted"],
            width=18,
            cursor="hand2",
        )
        if not self.is_collapsed:
            self.close_btn.pack(side="right", padx=(0, 6))
        # Hover styling for the close button
        self.close_btn.bind("<Enter>",
                            lambda e: self.close_btn.configure(text_color=COLORS["no_client"]))
        self.close_btn.bind("<Leave>",
                            lambda e: self.close_btn.configure(text_color=COLORS["text_muted"]))
        self.close_btn.bind("<Button-1>", lambda e: self._hide())

        # Bind drag/click handlers on body widgets (NOT the close button)
        for widget in (self.container, self.content, self.icon_label, self.client_label):
            widget.bind("<ButtonPress-1>", self._on_press)
            widget.bind("<B1-Motion>", self._on_drag)
            widget.bind("<ButtonRelease-1>", self._on_release)

        # Hover anywhere on the widget → fade in
        for widget in (self.root, self.container, self.content,
                       self.icon_label, self.client_label, self.close_btn):
            widget.bind("<Enter>", self._on_enter, add="+")
            widget.bind("<Leave>", self._on_leave, add="+")

        # Right-click anywhere → hide (matches Mac menubar item behavior)
        for widget in (self.container, self.content, self.icon_label, self.client_label):
            widget.bind("<Button-3>", lambda e: self._hide())

        # Initial color state
        self._update_appearance()

    # ------------------------------------------------------------------
    # Drag + click
    # ------------------------------------------------------------------
    def _on_press(self, event):
        self._press_x = event.x_root
        self._press_y = event.y_root
        self._drag_offset_x = event.x_root - self.root.winfo_x()
        self._drag_offset_y = event.y_root - self.root.winfo_y()
        self._drag_started = False

    def _on_drag(self, event):
        # Only start dragging once the mouse moves past the threshold —
        # this preserves quick clicks as "open picker"
        if not self._drag_started:
            dx = abs(event.x_root - self._press_x)
            dy = abs(event.y_root - self._press_y)
            if dx > DRAG_THRESHOLD_PX or dy > DRAG_THRESHOLD_PX:
                self._drag_started = True

        if self._drag_started:
            new_x = event.x_root - self._drag_offset_x
            new_y = event.y_root - self._drag_offset_y
            self.root.geometry(f"+{new_x}+{new_y}")

    def _on_release(self, event):
        if self._drag_started:
            # Drag ended — snap and persist
            try:
                w = self.root.winfo_width()
                h = self.root.winfo_height()
                x = self.root.winfo_x()
                y = self.root.winfo_y()
                x, y = self._snap_to_edges(x, y, w, h)
                self.root.geometry(f"{w}x{h}+{x}+{y}")
            except Exception:
                pass
            self._save_state()
            self._drag_started = False
            return

        # No drag — treat as click
        if self.is_collapsed:
            self._toggle_collapse()
        elif self.on_click:
            try:
                self.on_click()
            except Exception as e:
                print(f"[WIDGET] on_click error: {e}")

    # ------------------------------------------------------------------
    # Hover / fade
    # ------------------------------------------------------------------
    def _on_enter(self, _event=None):
        self._cancel_fade()
        self._apply_opacity(OPACITY_HOVER)

    def _on_leave(self, _event=None):
        self._schedule_fade()

    def _schedule_fade(self):
        self._cancel_fade()
        if self._root_alive():
            self._fade_after_id = self.root.after(
                FADE_DELAY_MS, lambda: self._apply_opacity(OPACITY_IDLE)
            )

    def _cancel_fade(self):
        if self._fade_after_id and self._root_alive():
            try:
                self.root.after_cancel(self._fade_after_id)
            except Exception:
                pass
        self._fade_after_id = None

    def _apply_opacity(self, alpha):
        if not self._root_alive():
            return
        try:
            self.root.attributes('-alpha', alpha)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Collapse / expand
    # ------------------------------------------------------------------
    def _toggle_collapse(self):
        """Toggle between expanded pill and icon-only collapsed mode."""
        self.is_collapsed = not self.is_collapsed

        if self.is_collapsed:
            self.client_label.pack_forget()
            self.close_btn.pack_forget()
            self.root.geometry(f"{COLLAPSED_WIDTH}x{COLLAPSED_HEIGHT}")
        else:
            self.client_label.pack(side="left", fill="x", expand=True, padx=(0, 6))
            self.close_btn.pack(side="right", padx=(0, 6))
            self.root.geometry(f"{WIDGET_WIDTH}x{WIDGET_HEIGHT}")

        self._save_state()

    # ------------------------------------------------------------------
    # Show / hide
    # ------------------------------------------------------------------
    def _hide(self):
        """Hide the widget (persisted — reopen via tray menu)."""
        self.is_visible = False
        self._save_state()
        if self.root:
            self.root.withdraw()

    def show(self):
        """Show the widget if hidden."""
        self.is_visible = True
        self._save_state()
        if self.root:
            try:
                self.root.deiconify()
                self.root.attributes('-topmost', True)
                self.root.lift()
                self._apply_opacity(OPACITY_HOVER)
                self._schedule_fade()
            except Exception:
                pass
        else:
            # Widget was destroyed — recreate
            self.create()
            if self.root:
                self.root.mainloop()

    # ------------------------------------------------------------------
    # Client display
    # ------------------------------------------------------------------
    def update_client(self, client_id, client_name):
        """Update the displayed client (called by tray controller)."""
        self.current_client_id = client_id
        self.current_client_name = client_name or "No Client"
        # Schedule on main thread if called from background
        if self._root_alive():
            try:
                self.root.after(0, self._update_appearance)
                # Briefly flash to full opacity so the user sees the change
                self.root.after(0, lambda: self._apply_opacity(OPACITY_HOVER))
                self.root.after(0, self._schedule_fade)
            except Exception:
                pass

    def _update_appearance(self):
        """Update colors and text based on current client state."""
        if not self._root_alive():
            return

        try:
            self.client_label.configure(text=self._truncate(self.current_client_name))

            if self.current_client_id:
                # Has client — teal accent
                self.container.configure(border_color=COLORS["primary"])
                self.icon_label.configure(text_color=COLORS["primary"])
                self.client_label.configure(text_color=COLORS["text"])
            else:
                # No client — red warning
                self.container.configure(border_color=COLORS["no_client"])
                self.icon_label.configure(text_color=COLORS["no_client"])
                self.client_label.configure(text_color=COLORS["no_client"])
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Background poller (kept from old behavior so widget stays in sync
    # even if update_client() is missed somewhere)
    # ------------------------------------------------------------------
    def _start_update_loop(self):
        self._update_running = True

        def update_loop():
            while self._update_running:
                try:
                    if self.get_client:
                        info = self.get_client()
                        if info:
                            new_id = info.get("client_id")
                            new_name = info.get("client_name") or "No Client"
                            if (new_id != self.current_client_id
                                    or new_name != self.current_client_name):
                                self.current_client_id = new_id
                                self.current_client_name = new_name
                                if self._root_alive():
                                    try:
                                        self.root.after(0, self._update_appearance)
                                    except Exception:
                                        pass
                except Exception as e:
                    print(f"[WIDGET] Update error: {e}")

                _time.sleep(POLL_INTERVAL_S)

        threading.Thread(target=update_loop, daemon=True).start()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _truncate(text, max_len=22):
        if not text:
            return "No Client"
        if len(text) <= max_len:
            return text
        return text[: max_len - 1] + "…"


# ============================================================
# Integration helper for TimeTrackerSystemTray
# ============================================================
def create_floating_widget(tray_controller):
    """
    Create and attach a floating widget to the system tray controller.

    Args:
        tray_controller: TimeTrackerSystemTray instance

    Returns:
        FloatingClientWidget instance, or None if customtkinter unavailable.
    """
    if not WIDGET_AVAILABLE:
        print("[WIDGET] Cannot create widget - customtkinter not available")
        return None

    def on_click():
        """Open client picker when widget body is clicked."""
        if hasattr(tray_controller, '_show_client_picker'):
            try:
                tray_controller._show_client_picker()
            except Exception as e:
                print(f"[WIDGET] Failed to open picker: {e}")

    def get_client():
        """Get current client from tray state."""
        if hasattr(tray_controller, 'state'):
            return {
                "client_id": tray_controller.state.current_client_id,
                "client_name": tray_controller.state.current_client_name,
            }
        return {"client_id": None, "client_name": "No Client"}

    widget = FloatingClientWidget(
        on_click_callback=on_click,
        get_client_callback=get_client,
    )
    return widget


if __name__ == "__main__":
    # Standalone test
    test_client = {"id": 1, "name": "Test Client Inc"}

    def on_click():
        print("Widget clicked — would open picker here")

    def get_client():
        return {"client_id": test_client["id"], "client_name": test_client["name"]}

    widget = FloatingClientWidget(
        on_click_callback=on_click,
        get_client_callback=get_client,
    )
    widget.create()

    def test_no_client():
        test_client["id"] = None
        test_client["name"] = "No Client"

    def test_new_client():
        test_client["id"] = 2
        test_client["name"] = "Varacchi 1040 - 2024 Tax Return"

    if widget.root:
        widget.root.after(3000, test_no_client)
        widget.root.after(6000, test_new_client)
        widget.run()