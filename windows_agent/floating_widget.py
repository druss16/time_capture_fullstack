"""
Floating Client Widget - Always visible current client indicator

v1.3.22 fixes:
  - Widget no longer grows during drag (locked size in every geometry call)
  - Snap threshold reduced 24px -> 8px so you can place it anywhere without
    it yanking to bottom/edge

Mac-style minimal pinned toolbar:
- Frameless always-on-top pill, sits just above the Windows taskbar
- Shows current client name only
- Click anywhere on it -> opens the client picker
- Drag to move; snaps to screen edges only if released within 8px
- Auto-fades to 55% opacity when not hovered, 98% on hover
- Hide via x -> reappears via "Show Client Widget" tray menu
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

# Geometry / behavior tunables
WIDGET_WIDTH = 200
WIDGET_HEIGHT = 36
COLLAPSED_WIDTH = 45
COLLAPSED_HEIGHT = 35

# Snap only if released REALLY close to an edge — was 24, too aggressive
EDGE_SNAP_THRESHOLD = 8
TASKBAR_CLEARANCE = 56
DEFAULT_MARGIN = 12

OPACITY_IDLE = 0.55
OPACITY_HOVER = 0.98
FADE_DELAY_MS = 1500

DRAG_THRESHOLD_PX = 4
POLL_INTERVAL_S = 2.0


class FloatingClientWidget:
    """Mac-style minimal pinned client toolbar for Windows."""

    def __init__(self, on_click_callback=None, get_client_callback=None):
        self.on_click = on_click_callback
        self.get_client = get_client_callback

        self.root = None
        self.is_collapsed = False
        self.is_visible = True

        # Drag state
        self._press_x = 0
        self._press_y = 0
        self._drag_offset_x = 0
        self._drag_offset_y = 0
        self._drag_started = False

        # Locked-in size — set once, used in every geometry() call to
        # prevent the "grows when dragged" Tkinter bug on Windows
        self._locked_width = WIDGET_WIDTH
        self._locked_height = WIDGET_HEIGHT

        self._fade_after_id = None
        self._update_running = False

        self.current_client_name = "No Client"
        self.current_client_id = None

        self.saved_x = None
        self.saved_y = None
        self._load_state()

    # ------------------------------------------------------------------
    # Persisted state
    # ------------------------------------------------------------------
    def _load_state(self):
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

        self.is_visible = True
        ctk.set_appearance_mode("dark")

        if parent_root:
            self.root = ctk.CTkToplevel(parent_root)
        else:
            self.root = ctk.CTk()

        self.root.title("TimeTracker")
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)

        try:
            self.root.attributes('-toolwindow', True)
        except Exception:
            pass

        # Lock in size based on current state
        if self.is_collapsed:
            self._locked_width = COLLAPSED_WIDTH
            self._locked_height = COLLAPSED_HEIGHT
        else:
            self._locked_width = WIDGET_WIDTH
            self._locked_height = WIDGET_HEIGHT

        x, y = self._compute_initial_position(self._locked_width, self._locked_height)
        self.root.geometry(f"{self._locked_width}x{self._locked_height}+{x}+{y}")

        self._build_ui()
        self._apply_opacity(OPACITY_IDLE)
        self._start_update_loop()

        return self.root

    def run(self):
        if self.root:
            self.root.mainloop()

    def destroy(self):
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
        try:
            self.root.update_idletasks()
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
        except Exception:
            screen_w, screen_h = 1920, 1080

        if self.saved_x is not None and self.saved_y is not None:
            x = max(0, min(self.saved_x, screen_w - w))
            y = max(0, min(self.saved_y, screen_h - h))
            return x, y

        # Default: bottom-right, just above the taskbar
        x = screen_w - w - DEFAULT_MARGIN
        y = screen_h - h - TASKBAR_CLEARANCE
        return x, y

    def _snap_to_edges(self, x, y, w, h):
        """Snap to nearest screen edge ONLY if released within snap threshold."""
        try:
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
        except Exception:
            return x, y

        # Horizontal snap — only if very close to an edge
        if x < EDGE_SNAP_THRESHOLD:
            x = DEFAULT_MARGIN
        elif x + w > screen_w - EDGE_SNAP_THRESHOLD:
            x = screen_w - w - DEFAULT_MARGIN

        # Vertical snap — only if very close to an edge
        if y < EDGE_SNAP_THRESHOLD:
            y = DEFAULT_MARGIN
        elif y + h > screen_h - EDGE_SNAP_THRESHOLD:
            y = screen_h - h - TASKBAR_CLEARANCE

        # Final clamp — never let widget end up off-screen
        x = max(0, min(x, screen_w - w))
        y = max(0, min(y, screen_h - h))
        return x, y

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        self.container = ctk.CTkFrame(
            self.root,
            fg_color=COLORS["bg_card"],
            corner_radius=10,
            border_width=1,
            border_color=COLORS["primary"],
        )
        self.container.pack(fill="both", expand=True, padx=2, pady=2)

        self.content = ctk.CTkFrame(self.container, fg_color="transparent")
        self.content.pack(fill="both", expand=True, padx=4, pady=2)

        self.icon_label = ctk.CTkLabel(
            self.content,
            text="●",
            font=ctk.CTkFont(family="Segoe UI", size=14),
            text_color=COLORS["primary"],
            width=14,
            cursor="hand2",
        )
        self.icon_label.pack(side="left", padx=(8, 6))

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
        self.close_btn.bind("<Enter>",
                            lambda e: self.close_btn.configure(text_color=COLORS["no_client"]))
        self.close_btn.bind("<Leave>",
                            lambda e: self.close_btn.configure(text_color=COLORS["text_muted"]))
        self.close_btn.bind("<Button-1>", lambda e: self._hide())

        for widget in (self.container, self.content, self.icon_label, self.client_label):
            widget.bind("<ButtonPress-1>", self._on_press)
            widget.bind("<B1-Motion>", self._on_drag)
            widget.bind("<ButtonRelease-1>", self._on_release)

        for widget in (self.root, self.container, self.content,
                       self.icon_label, self.client_label, self.close_btn):
            widget.bind("<Enter>", self._on_enter, add="+")
            widget.bind("<Leave>", self._on_leave, add="+")

        for widget in (self.container, self.content, self.icon_label, self.client_label):
            widget.bind("<Button-3>", lambda e: self._hide())

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
        if not self._drag_started:
            dx = abs(event.x_root - self._press_x)
            dy = abs(event.y_root - self._press_y)
            if dx > DRAG_THRESHOLD_PX or dy > DRAG_THRESHOLD_PX:
                self._drag_started = True

        if self._drag_started:
            new_x = event.x_root - self._drag_offset_x
            new_y = event.y_root - self._drag_offset_y
            # CRITICAL FIX: include locked width+height in every geometry call.
            # Using "+x+y" alone causes Tkinter to re-measure the window each
            # time and grow it by a few pixels per drag event on Windows.
            self.root.geometry(
                f"{self._locked_width}x{self._locked_height}+{new_x}+{new_y}"
            )

    def _on_release(self, event):
        if self._drag_started:
            try:
                x = self.root.winfo_x()
                y = self.root.winfo_y()
                x, y = self._snap_to_edges(x, y, self._locked_width, self._locked_height)
                self.root.geometry(
                    f"{self._locked_width}x{self._locked_height}+{x}+{y}"
                )
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
        self.is_collapsed = not self.is_collapsed

        if self.is_collapsed:
            self.client_label.pack_forget()
            self.close_btn.pack_forget()
            self._locked_width = COLLAPSED_WIDTH
            self._locked_height = COLLAPSED_HEIGHT
        else:
            self.client_label.pack(side="left", fill="x", expand=True, padx=(0, 6))
            self.close_btn.pack(side="right", padx=(0, 6))
            self._locked_width = WIDGET_WIDTH
            self._locked_height = WIDGET_HEIGHT

        try:
            x = self.root.winfo_x()
            y = self.root.winfo_y()
            self.root.geometry(
                f"{self._locked_width}x{self._locked_height}+{x}+{y}"
            )
        except Exception:
            self.root.geometry(f"{self._locked_width}x{self._locked_height}")

        self._save_state()

    # ------------------------------------------------------------------
    # Show / hide
    # ------------------------------------------------------------------
    def _hide(self):
        self.is_visible = False
        self._save_state()
        if self.root:
            self.root.withdraw()

    def show(self):
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
            self.create()
            if self.root:
                self.root.mainloop()

    # ------------------------------------------------------------------
    # Client display
    # ------------------------------------------------------------------
    def update_client(self, client_id, client_name):
        self.current_client_id = client_id
        self.current_client_name = client_name or "No Client"
        if self._root_alive():
            try:
                self.root.after(0, self._update_appearance)
                self.root.after(0, lambda: self._apply_opacity(OPACITY_HOVER))
                self.root.after(0, self._schedule_fade)
            except Exception:
                pass

    def _update_appearance(self):
        if not self._root_alive():
            return
        try:
            self.client_label.configure(text=self._truncate(self.current_client_name))
            if self.current_client_id:
                self.container.configure(border_color=COLORS["primary"])
                self.icon_label.configure(text_color=COLORS["primary"])
                self.client_label.configure(text_color=COLORS["text"])
            else:
                self.container.configure(border_color=COLORS["no_client"])
                self.icon_label.configure(text_color=COLORS["no_client"])
                self.client_label.configure(text_color=COLORS["no_client"])
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Background poller
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

    @staticmethod
    def _truncate(text, max_len=22):
        if not text:
            return "No Client"
        if len(text) <= max_len:
            return text
        return text[: max_len - 1] + "…"


# ============================================================
# Integration helper
# ============================================================
def create_floating_widget(tray_controller):
    if not WIDGET_AVAILABLE:
        print("[WIDGET] Cannot create widget - customtkinter not available")
        return None

    def on_click():
        if hasattr(tray_controller, '_show_client_picker'):
            try:
                tray_controller._show_client_picker()
            except Exception as e:
                print(f"[WIDGET] Failed to open picker: {e}")

    def get_client():
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
    test_client = {"id": 1, "name": "Test Client Inc"}

    def on_click():
        print("Widget clicked")

    def get_client():
        return {"client_id": test_client["id"], "client_name": test_client["name"]}

    widget = FloatingClientWidget(
        on_click_callback=on_click,
        get_client_callback=get_client,
    )
    widget.create()

    if widget.root:
        widget.run()