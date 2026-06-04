"""
Floating Client Widget — Minimal Dot Mode

v1.3.25 redesign:
  Default state is a tiny 18x18 dot in the bottom-right corner.
  Hovering the dot expands it to the full pill widget.
  Mouse leave collapses back to dot after a short delay.
  When client switches, pill flashes to 100% opacity, holds at 98%
  for 3 seconds, then collapses back to dot.

Classification states (drives dot/pill color and label):
  - "committed" → teal (green)  — system confident, shows client name
  - "proposed"  → amber (yellow) — system tentative, shows "ClientName?"
  - "captured"  → gray           — block exists but no signal matched
  - "no_client" → red            — no recent activity, prompts user to set client

Visual states:
  - Dot (idle): 18x18 dot at 55% opacity, basically invisible
  - Dot (no client / proposed): 95% opacity to grab attention
  - Pill (hover): full 200x36 pill with client name, close button
  - Pill (just switched): briefly flashes to 100% opacity for visibility
    def _refresh_current_view(self):

Interactions:
  - Hover dot → expands to pill
  - Mouse leaves pill → collapses back to dot after 600ms
  - Click pill body → opens client picker
  - Click × on pill → hides widget entirely (reopen via tray)
  - Drag from anywhere → moves widget; snaps to edges within 8px
  - Right-click → hides widget
  - Client switch → pill flashes + holds for 3s + collapses
"""

import os
import json
import threading
import time as _time
from typing import Optional

try:
    import customtkinter as ctk
    WIDGET_AVAILABLE = True
except ImportError:
    WIDGET_AVAILABLE = False


COLORS = {
    "primary": "#14B8A6",         # teal — state="committed" (confirmed classification)
    "primary_dark": "#0D9488",
    "uncertain": "#FCD34D",       # yellow — state="proposed" (tentative, append "?")
    "uncategorized": "#6B7280",   # gray — state="captured" (no signals matched)
    "bg_dark": "#1A1A1A",
    "bg_card": "#252525",
    "text": "#FFFFFF",
    "text_muted": "#888888",
    "no_client": "#EF4444",       # red — state="no_client" (no activity, no pinned client)
}

WIDGET_STATE_FILE = os.path.expanduser("~/.timetracker/widget_state.json")

# --- Dot mode (idle) ---
DOT_SIZE = 18
DOT_OPACITY_IDLE = 0.55
DOT_OPACITY_NO_CLIENT = 0.95   # red dot stays bright so people notice

# --- Pill mode (hover) ---
PILL_WIDTH = 200
PROPOSED_PILL_WIDTH = 320   # v1.5.2: wider pill ONLY for "Still working on <client>?" prompt
PILL_HEIGHT = 36
PILL_OPACITY = 0.98
PILL_OPACITY_FLASH = 1.0       # brief flash on client switch

# --- Behavior tunables ---
COLLAPSE_DELAY_MS = 600        # delay after mouseleave before collapsing
SWITCH_HOLD_MS = 3000          # how long the pill stays expanded after a client switch
FLASH_DURATION_MS = 600        # how long the 100% flash lasts before settling to 98%

EDGE_SNAP_THRESHOLD = 8        # snap only if released within 8px of edge
TASKBAR_CLEARANCE = 56
DEFAULT_MARGIN = 12

DRAG_THRESHOLD_PX = 4
POLL_INTERVAL_S = 2.0


class FloatingClientWidget:
    """Minimal dot that expands to a full pill on hover."""

    def __init__(self, on_click_callback=None, get_client_callback=None):
        self.on_click = on_click_callback
        self.get_client = get_client_callback

        self.root = None

        # Mode tracking
        self._mode = "dot"            # "dot" or "pill"
        self._collapse_after_id = None
        self._flash_after_id = None

        # Visibility state (persisted across restarts)
        self.is_visible = True

        # Drag state
        self._press_x = 0
        self._press_y = 0
        self._drag_offset_x = 0
        self._drag_offset_y = 0
        self._drag_started = False

        # Polling thread
        self._update_running = False

        self.current_client_name = "No Client"
        self.current_client_id = None
        # Classification state from backend: "committed" | "proposed" | "captured" | "no_client"
        self.current_state = "no_client"
        # Last state we actually rendered — used by _refresh_current_view to
        # detect transitions vs steady-state polls. Without this, the 2s poll
        # would re-arm the collapse timer every cycle and the pill never closes.
        self._rendered_state: Optional[str] = None

        # Saved position
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
                    self.is_visible = state.get('visible', True)
            except Exception:
                pass

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(WIDGET_STATE_FILE), exist_ok=True)
            x = self.root.winfo_x() if self._root_alive() else self.saved_x
            y = self.root.winfo_y() if self._root_alive() else self.saved_y
            state = {
                'x': x,
                'y': y,
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

        # Start in dot mode at saved position (or bottom-right by default)
        x, y = self._compute_initial_position(DOT_SIZE, DOT_SIZE)
        self.root.geometry(f"{DOT_SIZE}x{DOT_SIZE}+{x}+{y}")
        self.root.configure(fg_color=COLORS["bg_dark"])

        self._build_dot_ui()
        self._apply_idle_opacity()
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
        """Saved position if valid, else bottom-right above taskbar."""
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
        """Snap only if released within 8px of edge."""
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

        x = max(0, min(x, screen_w - w))
        y = max(0, min(y, screen_h - h))
        return x, y

    # ------------------------------------------------------------------
    # DOT UI (default minimal state)
    # ------------------------------------------------------------------
    def _build_dot_ui(self):
        """Tiny circular dot. Just one widget — hover expands to pill."""
        for child in self.root.winfo_children():
            child.destroy()

        color = self._state_color()

        self.dot = ctk.CTkFrame(
            self.root,
            fg_color=color,
            corner_radius=DOT_SIZE // 2,
            width=DOT_SIZE,
            height=DOT_SIZE,
            cursor="hand2",
        )
        self.dot.pack(fill="both", expand=True)

        for w in (self.root, self.dot):
            w.bind("<Enter>", self._on_enter, add="+")
            w.bind("<Leave>", self._on_leave, add="+")
            w.bind("<ButtonPress-1>", self._on_press, add="+")
            w.bind("<B1-Motion>", self._on_drag, add="+")
            w.bind("<ButtonRelease-1>", self._on_release, add="+")
            w.bind("<Button-3>", lambda e: self._hide(), add="+")

    # ------------------------------------------------------------------
    # PILL UI (hover-expanded state)
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # v1.5.0 — Confirmation handlers for proposed-state buttons
    # ------------------------------------------------------------------
    def _current_pill_width(self) -> int:
        """v1.5.2: Pill widens only for proposed state to fit the prompt.
        Returns PROPOSED_PILL_WIDTH (320) when state is 'proposed',
        else PILL_WIDTH (200) for committed/captured.
        """
        if getattr(self, 'current_state', None) == "proposed":
            return PROPOSED_PILL_WIDTH
        return PILL_WIDTH

    # ------------------------------------------------------------------
    # v1.5.0 — Confirmation handlers for proposed-state buttons
    # ------------------------------------------------------------------
    def _on_confirm_continue(self, event=None):
        """User clicked ✓ — confirm still on this client.
        Resets sticky 5-min timer via widget_tracker.confirm_continue().
        v1.5.1: accepts event arg + returns 'break' to stop propagation
        to parent widgets (which would otherwise fire the click handler
        and open the client picker).
        """
        try:
            from widget_state_tracker import get_widget_state_tracker as _get_tracker
        except ImportError:
            try:
                from windows_agent.widget_state_tracker import get_widget_state_tracker as _get_tracker
            except ImportError:
                _get_tracker = None
        if _get_tracker is None:
            return "break"
        try:
            tracker = _get_tracker()
            tracker.confirm_continue()
            self.current_state = tracker.state
            self.current_client_id = tracker.displayed_client_id
            self.current_client_name = tracker.displayed_client_name or "No Client"
            if self._root_alive():
                self.root.after(0, self._refresh_current_view)
        except Exception as e:
            print(f"[WIDGET] confirm_continue error: {e}")
        return "break"

    def _on_confirm_deny(self, event=None):
        """User clicked ✗ — deny, clear sticky, go to captured.
        Calls widget_tracker.confirm_deny() which clears sticky state and
        prevents auto-restore until a new recognized client window is detected.
        v1.5.1: accepts event arg + returns 'break' to stop propagation
        to parent widgets (which would otherwise open the client picker).
        """
        try:
            from widget_state_tracker import get_widget_state_tracker as _get_tracker
        except ImportError:
            try:
                from windows_agent.widget_state_tracker import get_widget_state_tracker as _get_tracker
            except ImportError:
                _get_tracker = None
        if _get_tracker is None:
            return "break"
        try:
            tracker = _get_tracker()
            tracker.confirm_deny()
            self.current_state = "captured"
            self.current_client_id = None
            self.current_client_name = "No Client"
            if self._root_alive():
                self.root.after(0, self._refresh_current_view)
        except Exception as e:
            print(f"[WIDGET] confirm_deny error: {e}")
        return "break"

    def _build_pill_ui(self):
        """Full pill widget — same design as before, just rebuilt on demand."""
        # v1.5.2: Resize root to match current state width (wider for proposed).
        try:
            cur_x = self.root.winfo_x()
            cur_y = self.root.winfo_y()
            self.root.geometry(
                f"{self._current_pill_width()}x{PILL_HEIGHT}+{cur_x}+{cur_y}"
            )
        except Exception:
            pass

        for child in self.root.winfo_children():
            child.destroy()

        border_color = self._state_color()
        accent_color = self._state_color()
        # Use the state color for text on red/yellow/gray states for emphasis,
        # white for committed (green) where the bg is dark teal vs dark gray
        text_color = COLORS["text"] if self.current_state == "committed" else self._state_color()

        self.container = ctk.CTkFrame(
            self.root,
            fg_color=COLORS["bg_card"],
            corner_radius=10,
            border_width=1,
            border_color=border_color,
        )
        self.container.pack(fill="both", expand=True, padx=2, pady=2)

        self.content = ctk.CTkFrame(self.container, fg_color="transparent")
        self.content.pack(fill="both", expand=True, padx=4, pady=2)

        self.icon_label = ctk.CTkLabel(
            self.content,
            text="●",
            font=ctk.CTkFont(family="Segoe UI", size=14),
            text_color=accent_color,
            width=14,
            cursor="hand2",
        )
        self.icon_label.pack(side="left", padx=(8, 6))

        # v1.5.2: In proposed state, prompt the user explicitly with
        # "Still working on <client>?" rather than the bare name.
        # The ✓/✗ buttons next to it make the question actionable.
        if (self.current_state == "proposed"
                and self.current_client_name
                and self.current_client_name != "No Client"):
            pill_text = f"Still working on {self.current_client_name}?"
        else:
            pill_text = self._display_name()

        self.client_label = ctk.CTkLabel(
            self.content,
            text=pill_text,
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=text_color,
            anchor="w",
            cursor="hand2",
        )
        self.client_label.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.close_btn = ctk.CTkLabel(
            self.content,
            text="×",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color=COLORS["text_muted"],
            width=18,
            cursor="hand2",
        )
        self.close_btn.pack(side="right", padx=(0, 6))
        self.close_btn.bind("<Enter>",
                            lambda e: self.close_btn.configure(text_color=COLORS["no_client"]))
        self.close_btn.bind("<Leave>",
                            lambda e: self.close_btn.configure(text_color=COLORS["text_muted"]))
        self.close_btn.bind("<Button-1>", lambda e: self._hide())
        self.close_btn.bind("<Double-Button-1>", lambda e: "break")

        # v1.5.0: Confirmation buttons rendered only in proposed state.
        # ✓ confirms still on this client (resets sticky 5-min timer)
        # ✗ denies (clears sticky, goes to captured immediately)
        if self.current_state == "proposed":
            self.deny_btn = ctk.CTkLabel(
                self.content,
                text="✗",
                font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
                text_color=COLORS["no_client"],
                width=18,
                cursor="hand2",
            )
            self.deny_btn.pack(side="right", padx=(0, 4))
            self.deny_btn.bind("<Button-1>", self._on_confirm_deny)
            self.deny_btn.bind("<Double-Button-1>", lambda e: "break")

            self.confirm_btn = ctk.CTkLabel(
                self.content,
                text="✓",
                font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
                text_color="#16A34A",  # green-600
                width=18,
                cursor="hand2",
            )
            self.confirm_btn.pack(side="right", padx=(0, 4))
            self.confirm_btn.bind("<Button-1>", self._on_confirm_continue)
            self.confirm_btn.bind("<Double-Button-1>", lambda e: "break")

            # Hover handlers so the pill doesn't accidentally collapse
            # while user is choosing.
            for btn in (self.confirm_btn, self.deny_btn):
                btn.bind("<Enter>", self._on_enter, add="+")
                btn.bind("<Leave>", self._on_leave, add="+")

        for w in (self.container, self.content, self.icon_label, self.client_label):
            w.bind("<ButtonPress-1>", self._on_press)
            w.bind("<B1-Motion>", self._on_drag)
            w.bind("<ButtonRelease-1>", self._on_release)
            w.bind("<Double-Button-1>", self._on_double_click)
            w.bind("<Button-3>", lambda e: self._hide())

        for w in (self.root, self.container, self.content,
                  self.icon_label, self.client_label, self.close_btn):
            w.bind("<Enter>", self._on_enter, add="+")
            w.bind("<Leave>", self._on_leave, add="+")

    # ------------------------------------------------------------------
    # Mode transitions: dot ↔ pill
    # ------------------------------------------------------------------
    def _expand_to_pill(self):
        if self._mode == "pill" or not self._root_alive():
            return

        try:
            current_x = self.root.winfo_x()
            current_y = self.root.winfo_y()
            screen_w = self.root.winfo_screenwidth()

            # Anchor pill's right edge to where dot's right edge was —
            # prevents pill from "shooting out left" on right-side dots
            dot_right = current_x + DOT_SIZE
            if dot_right > screen_w - 100:
                new_x = dot_right - self._current_pill_width()
            else:
                new_x = current_x

            new_x = max(0, min(new_x, screen_w - self._current_pill_width()))
        except Exception:
            new_x = current_x

        self._mode = "pill"
        self.root.geometry(f"{self._current_pill_width()}x{PILL_HEIGHT}+{new_x}+{current_y}")
        self._build_pill_ui()
        self._apply_opacity(PILL_OPACITY)

    def _collapse_to_dot(self):
        if self._mode == "dot" or not self._root_alive():
            return
        print(f"[WIDGET] collapse check: state={self.current_state}, client={self.current_client_name}")
        if self.current_state in ("proposed", "captured"):
            print(f"[WIDGET] collapse BLOCKED (state={self.current_state})")
            return
        print(f"[WIDGET] collapsing to dot")

        try:
            current_x = self.root.winfo_x()
            current_y = self.root.winfo_y()
            screen_w = self.root.winfo_screenwidth()

            pill_right = current_x + self._current_pill_width()
            if pill_right > screen_w - 100:
                new_x = pill_right - DOT_SIZE
            else:
                new_x = current_x

            new_x = max(0, min(new_x, screen_w - DOT_SIZE))
        except Exception:
            new_x = current_x

        self._mode = "dot"
        self.root.geometry(f"{DOT_SIZE}x{DOT_SIZE}+{new_x}+{current_y}")
        self._build_dot_ui()
        self._apply_idle_opacity()

    # ------------------------------------------------------------------
    # Hover handlers
    # ------------------------------------------------------------------
    def _on_enter(self, _event=None):
        self._cancel_collapse()
        if self._mode == "dot":
            self._expand_to_pill()

    def _on_leave(self, _event=None):
        # Leave fires when pointer crosses to a child widget too — guard
        # against spurious collapses by checking if pointer is actually outside
        if not self._root_alive():
            return
        try:
            x, y = self.root.winfo_pointerxy()
            wx, wy = self.root.winfo_x(), self.root.winfo_y()
            ww, wh = self.root.winfo_width(), self.root.winfo_height()
            if wx <= x < wx + ww and wy <= y < wy + wh:
                return  # pointer still inside
        except Exception:
            pass

        self._schedule_collapse()

    def _schedule_collapse(self, delay_ms=None):
        self._cancel_collapse()
        if self._root_alive():
            delay = delay_ms if delay_ms is not None else COLLAPSE_DELAY_MS
            self._collapse_after_id = self.root.after(delay, self._collapse_to_dot)

    def _cancel_collapse(self):
        if self._collapse_after_id and self._root_alive():
            try:
                self.root.after_cancel(self._collapse_after_id)
            except Exception:
                pass
        self._collapse_after_id = None

    def _apply_opacity(self, alpha):
        if not self._root_alive():
            return
        try:
            self.root.attributes('-alpha', alpha)
        except Exception:
            pass

    def _apply_idle_opacity(self):
        """Dot opacity depends on classification state."""
        self._apply_opacity(self._idle_opacity())

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
            w = self._current_pill_width() if self._mode == "pill" else DOT_SIZE
            h = PILL_HEIGHT if self._mode == "pill" else DOT_SIZE
            new_x = event.x_root - self._drag_offset_x
            new_y = event.y_root - self._drag_offset_y
            self.root.geometry(f"{w}x{h}+{new_x}+{new_y}")

    def _on_release(self, event):
        if self._drag_started:
            try:
                w = self._current_pill_width() if self._mode == "pill" else DOT_SIZE
                h = PILL_HEIGHT if self._mode == "pill" else DOT_SIZE
                x = self.root.winfo_x()
                y = self.root.winfo_y()
                x, y = self._snap_to_edges(x, y, w, h)
                self.root.geometry(f"{w}x{h}+{x}+{y}")
            except Exception:
                pass
            self._save_state()
            self._drag_started = False
            return

        # No drag — treat as click.
        # v1.5.1: Removed single-click → picker. Picker now opens via
        # <Double-Button-1> binding to avoid accidental opens while
        # dragging or clicking ✓/✗/× buttons. Dot single-click still
        # expands to pill (matches "show me state" expectation).
        if self._mode == "dot":
            self._expand_to_pill()

    def _on_double_click(self, event=None):
        """v1.5.1: Picker opens via double-click only.
        Avoids accidental opens when user drags the widget or clicks
        any of the inline buttons (✓ ✗ ×).
        """
        if self.on_click:
            try:
                self.on_click()
            except Exception as e:
                print(f"[WIDGET] on_click error: {e}")
        return "break"

    # ------------------------------------------------------------------
    # Show / hide
    # ------------------------------------------------------------------
    def _hide(self):
        """Hide the widget entirely (persisted — reopen via tray menu)."""
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
            except Exception:
                pass
        else:
            self.create()
            if self.root:
                self.root.mainloop()

    # ------------------------------------------------------------------
    # Client display — pulse-on-switch behavior
    # ------------------------------------------------------------------
    def update_client(self, client_id, client_name, state=None):
        """
        Called by the tray controller on every client switch or state change.

        Args:
            client_id: int or None
            client_name: str or None
            state: "committed" | "proposed" | "captured" | "no_client" or None.
                   If None, infers from client_id (legacy callers).

        Visual sequence:
          1. Expand dot → pill (instant)
          2. Flash to 100% opacity for 600ms (catches the eye)
          3. Settle to normal 98% opacity
          4. Hold expanded for 3 seconds total
          5. Collapse back to dot
        """
        self.current_client_id = client_id
        self.current_client_name = client_name or "No Client"
        # If state not provided, infer from client_id for backwards compat
        if state is not None:
            self.current_state = state
        else:
            self.current_state = "committed" if client_id else "no_client"

        if not self._root_alive():
            return

        try:
            # Cancel any pending collapse / flash from a previous switch
            self._cancel_collapse()
            self._cancel_flash()

            # 1. Expand to pill immediately. If pill is already open (e.g. user
            #    is correcting a yellow proposed state by manually picking the
            #    right client), force a rebuild so the new green color and
            #    client name show BEFORE the flash + collapse sequence runs.
            def _expand_or_repaint():
                if self._mode == "pill":
                    self._build_pill_ui()  # in-place repaint with new state
                else:
                    self._expand_to_pill()
            self.root.after(0, _expand_or_repaint)

            # 2. Flash to 100% opacity to catch the eye
            self.root.after(0, lambda: self._apply_opacity(PILL_OPACITY_FLASH))

            # 3. Settle to normal pill opacity after the flash
            self._flash_after_id = self.root.after(
                FLASH_DURATION_MS,
                lambda: self._apply_opacity(PILL_OPACITY)
            )

            # 4. Schedule collapse only for committed state. Yellow/gray
            #    pills stay open by design — scheduling a collapse here
            #    would just bump _rendered_state churn and waste a timer.
            if self.current_state == "committed":
                self._schedule_collapse(delay_ms=SWITCH_HOLD_MS)

            # 5. Mark this state as "rendered" so the poller's transition
            #    detector doesn't re-fire flash+collapse on the next tick.
            self._rendered_state = self.current_state
        except Exception as e:
            print(f"[WIDGET] update_client error: {e}")

    def _cancel_flash(self):
        if self._flash_after_id and self._root_alive():
            try:
                self.root.after_cancel(self._flash_after_id)
            except Exception:
                pass
        self._flash_after_id = None

    # ------------------------------------------------------------------
    # Background poller — keeps widget in sync if update_client is missed
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
                            new_state = info.get("state") or (
                                "committed" if new_id else "no_client"
                            )
                            if (new_id != self.current_client_id
                                    or new_name != self.current_client_name
                                    or new_state != self.current_state):
                                self.current_client_id = new_id
                                self.current_client_name = new_name
                                self.current_state = new_state
                                if self._root_alive():
                                    try:
                                        self.root.after(0, self._refresh_current_view)
                                    except Exception:
                                        pass
                except Exception as e:
                    print(f"[WIDGET] Update error: {e}")
                _time.sleep(POLL_INTERVAL_S)

        threading.Thread(target=update_loop, daemon=True).start()

    def _refresh_current_view(self):
        """Rebuild whichever view (dot or pill) is currently showing.

        Only schedules collapses or expansions on REAL state transitions —
        otherwise the 2-second poll would re-arm the collapse timer every
        cycle and a green pill would never actually close.
        """
        if not self._root_alive():
            return

        prev_state = self._rendered_state
        new_state = self.current_state
        is_transition = prev_state != new_state
        self._rendered_state = new_state

        # Yellow / gray want attention — force pill open if we're a dot.
        # Always re-evaluate (even on steady-state polls) since a stuck dot
        # in proposed/captured state is a UX bug.
        if new_state in ("proposed", "captured") and self._mode == "dot":
            self._cancel_collapse()
            self._expand_to_pill()
            return

        # v1.5.0: Pill-mode transitions to proposed or captured.
        # Without this rebuild, the poller never calls _build_pill_ui when
        # state changes while pill is open — yellow ? + confirmation buttons
        # would never appear when transitioning from green committed.
        if is_transition and self._mode == "pill":
            if new_state == "proposed":
                # committed → proposed: rebuild with yellow + ✓/✗ buttons.
                # Stay open (no auto-collapse) — user needs to see and click.
                self._cancel_collapse()
                self._cancel_flash()
                self._build_pill_ui()
                return
            if new_state == "captured":
                # proposed → captured (timeout or ✗ click): rebuild gray
                # without buttons, then collapse to dot.
                self._cancel_flash()
                self._build_pill_ui()
                self._schedule_collapse(delay_ms=SWITCH_HOLD_MS)
                return

        # Green TRANSITION while pill is open — flash + schedule collapse.
        # Steady-state green polls (prev == new == committed) must NOT
        # re-arm the timer; otherwise the pill stays open forever.
        if (
            new_state == "committed"
            and self._mode == "pill"
            and is_transition
            and prev_state in ("proposed", "captured")
        ):
            # Yellow/gray → green transition. Make sure the user sees the
            # new client name with a clear flash before we collapse.
            self._build_pill_ui()
            self._cancel_flash()
            # Start at full opacity so the new green name pops
            self._apply_opacity(PILL_OPACITY_FLASH)
            # Settle to normal pill opacity after the flash
            self._flash_after_id = self.root.after(
                FLASH_DURATION_MS,
                lambda: self._apply_opacity(PILL_OPACITY),
            )
            # Hold longer than a manual switch so the user clearly reads
            # the new client name before it collapses to a dot
            self._schedule_collapse(delay_ms=SWITCH_HOLD_MS)
            return

        # No transition — only rebuild if something visible actually changed.
        # Steady-state polls would otherwise destroy + recreate child widgets
        # every 2s, which fires synthetic Enter/Leave events on the new
        # widgets and silently cancels any scheduled collapse timer (since
        # _on_enter cancels collapses). That's why a green pill that should
        # collapse after 3s never closed — the 2s poll kept wiping the timer.
        if self._mode == "dot":
            # Cheap recolor — no rebuild
            try:
                self.dot.configure(fg_color=self._state_color())
                self._apply_idle_opacity()
            except Exception:
                # Fallback if dot widget got destroyed
                self._build_dot_ui()
                self._apply_idle_opacity()
        else:
            # Pill — only rebuild if the visible label actually changed.
            # Otherwise leave it alone so collapse timers keep ticking.
            try:
                desired_text = self._display_name()
                current_text = self.client_label.cget("text")
                if desired_text != current_text:
                    # State changed (proposed → captured, etc). Recolor
                    # ALL three painted elements: icon dot, label text,
                    # and container border. Without recoloring the label,
                    # the new text inherits the old state's color (e.g.
                    # gray "Uncategorized" rendered in yellow).
                    accent = self._state_color()
                    label_color = COLORS["text"] if self.current_state == "committed" else accent
                    self.client_label.configure(text=desired_text, text_color=label_color)
                    self.icon_label.configure(text_color=accent)
                    self.container.configure(border_color=accent)
            except Exception:
                self._build_pill_ui()

    @staticmethod
    def _truncate(text, max_len=22):
        if not text:
            return "No Client"
        if len(text) <= max_len:
            return text
        return text[: max_len - 1] + "…"

    # ------------------------------------------------------------------
    # State-based color and label helpers
    # ------------------------------------------------------------------
    def _state_color(self):
        """Color for the current classification state."""
        return {
            "committed":  COLORS["primary"],
            "proposed":   COLORS["uncertain"],
            "captured":   COLORS["uncategorized"],
            "no_client":  COLORS["no_client"],
        }.get(self.current_state, COLORS["no_client"])

    def _display_name(self):
        """Label text for the current state.

        State → display:
          no_client    → "No Client"
          captured     → "Uncategorized" (will land as Uncategorized
                         unless user corrects, regardless of active client)
          proposed     → "ClientName?"
          committed    → "ClientName"
        """
        if self.current_state == "no_client" or not self.current_client_id:
            return "No Client"
        if self.current_state == "captured":
            return "Uncategorized"
        name = self._truncate(self.current_client_name or "No Client")
        if self.current_state == "proposed":
            return f"{name}?"
        return name

    def _idle_opacity(self):
        """Dot opacity. Brighter when something needs user attention."""
        if self.current_state in ("no_client", "proposed"):
            return DOT_OPACITY_NO_CLIENT  # 0.95 — grab attention
        return DOT_OPACITY_IDLE           # 0.55 — basically invisible


# ============================================================
# Integration helper for TimeTrackerSystemTray
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
        # v1.4.5: Read sticky-aware display values from widget_state_tracker.
        # The tracker maintains the last committed client for 5 min after the
        # user leaves the recognized context (sticky green), then 5 more min
        # in yellow ? (Phase 2 will add confirmation buttons), then captured.
        # Idle ≥ MOUSE_IDLE_PAUSE_S clears sticky (no auto-restore on resume).
        try:
            from widget_state_tracker import get_widget_state_tracker as _get_tracker
        except ImportError:
            try:
                from windows_agent.widget_state_tracker import get_widget_state_tracker as _get_tracker
            except ImportError:
                _get_tracker = None

        if _get_tracker is not None:
            try:
                tracker = _get_tracker()
                # Reading .state runs the sticky state machine; the
                # displayed_* properties are sticky-aware.
                state = tracker.state
                return {
                    "client_id":   tracker.displayed_client_id,
                    "client_name": tracker.displayed_client_name or "No Client",
                    "state":       state,
                }
            except Exception as e:
                print(f"[WIDGET] get_client tracker error: {e}")

        # Fallback only if tracker can't be imported (extremely unlikely)
        if hasattr(tray_controller, 'state'):
            return {
                "client_id":   tray_controller.state.current_client_id,
                "client_name": tray_controller.state.current_client_name,
                "state":       getattr(tray_controller.state, 'current_widget_state', None),
            }
        return {"client_id": None, "client_name": "No Client", "state": "no_client"}

    widget = FloatingClientWidget(
        on_click_callback=on_click,
        get_client_callback=get_client,
    )
    return widget


if __name__ == "__main__":
    test_client = {"id": 1, "name": "Test Client Inc"}

    def on_click():
        print("Picker would open now")

    def get_client():
        return {"client_id": test_client["id"], "client_name": test_client["name"]}

    widget = FloatingClientWidget(
        on_click_callback=on_click,
        get_client_callback=get_client,
    )
    widget.create()

    # Simulate a client switch after 3 seconds to test the pulse-flash
    if widget.root:
        widget.root.after(3000, lambda: widget.update_client(2, "Varacchi 1040"))
        widget.run()