#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Morning Timesheet Review - In-App Modal Dialog

Shows a prominent modal dialog prompting users to review yesterday's timesheet.
Triggers on:
  - Agent startup (if within morning window and not yet dismissed today)
  - "Remind Me Later" re-trigger after configurable delay
  - Background periodic check (catches remind-later timers)

Features:
  - Full modal dialog (not a tiny toast - impossible to miss)
  - Yesterday's time summary with client breakdown
  - "Review Now" opens web app timesheet page
  - "Remind Me Later" re-triggers in 30 minutes
  - "Skip" marks as seen for the day
  - Persists dismiss state so it doesn't nag all day
"""

import os
import json
import threading
import time
import webbrowser
from datetime import datetime, date, timedelta
from typing import Optional, Callable, Dict, List

try:
    import customtkinter as ctk
    CTK_AVAILABLE = True
except ImportError:
    CTK_AVAILABLE = False

# Colors matching the app theme
COLORS = {
    "primary": "#14B8A6",
    "primary_hover": "#0D9488",
    "primary_light": "#5EEAD4",
    "success": "#10B981",
    "warning": "#F59E0B",
    "danger": "#EF4444",
    "bg_dark": "#1A1A1A",
    "bg_card": "#252525",
    "bg_input": "#2A2A2A",
    "bg_item": "#2D2D2D",
    "border": "#3A3A3A",
    "text": "#FFFFFF",
    "text_secondary": "#888888",
    "text_muted": "#666666",
}

STATE_FILE = os.path.expanduser("~/.timetracker/morning_review_state.json")


# ============================================================
# Configuration
# ============================================================
DEFAULT_CONFIG = {
    "enabled": True,
    "earliest_hour": 6,          # Don't show before 6 AM
    "latest_hour": 12,           # Don't show after noon
    "remind_later_minutes": 30,  # "Remind Me Later" delay
    "skip_weekends": True,       # Don't prompt on Sat/Sun for Fri
    "min_hours_to_prompt": 0.0,  # Show even if 0 hours (so they know!)
}


class MorningReviewConfig:
    def __init__(self, **kwargs):
        for key, default in DEFAULT_CONFIG.items():
            setattr(self, key, kwargs.get(key, default))


# ============================================================
# State Persistence
# ============================================================
def _load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_state(state: dict):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[MORNING] Failed to save state: {e}")


def was_dismissed_today() -> bool:
    state = _load_state()
    last_dismissed = state.get("last_dismissed_date")
    return last_dismissed == date.today().isoformat() if last_dismissed else False


def mark_dismissed():
    state = _load_state()
    state["last_dismissed_date"] = date.today().isoformat()
    state["last_dismissed_ts"] = datetime.now().isoformat()
    state.pop("remind_at", None)
    _save_state(state)


def get_remind_later_time() -> Optional[float]:
    state = _load_state()
    return state.get("remind_at")


def set_remind_later(minutes: int):
    state = _load_state()
    state["remind_at"] = time.time() + (minutes * 60)
    state.pop("last_dismissed_date", None)  # Clear dismiss so reminder fires
    _save_state(state)


def clear_remind_later():
    state = _load_state()
    state.pop("remind_at", None)
    _save_state(state)


# ============================================================
# Should We Show?
# ============================================================
def should_show_review(config: MorningReviewConfig = None) -> bool:
    """
    Returns True if:
    - Enabled
    - Within morning window OR remind-later timer expired
    - Not already dismissed today
    - Not a weekend (if configured)
    """
    if config is None:
        config = MorningReviewConfig()

    if not config.enabled:
        return False

    now = datetime.now()

    # Check for expired "remind me later" timer
    remind_at = get_remind_later_time()
    if remind_at and time.time() >= remind_at:
        clear_remind_later()
        return True

    # Already dismissed today?
    if was_dismissed_today():
        return False

    # Check time window
    if now.hour < config.earliest_hour or now.hour >= config.latest_hour:
        return False

    # Skip weekends — yesterday would be Fri/Sat
    if config.skip_weekends:
        yesterday = now.date() - timedelta(days=1)
        if yesterday.weekday() >= 5:  # 5=Sat, 6=Sun
            return False

    return True


# ============================================================
# Fetch Yesterday's Summary
# ============================================================
def fetch_yesterday_summary(api_base: str, api_key: str) -> Optional[dict]:
    """
    Fetch yesterday's timesheet summary from backend.
    
    Expected response:
    {
        "date": "2026-02-06",
        "total_hours": 7.5,
        "status": "draft",
        "entries": [
            {"client_name": "Acme Corp", "hours": 3.5},
            ...
        ]
    }
    """
    import urllib.request
    import urllib.error

    if not api_base or not api_key:
        return None

    url = f"{api_base}/timesheet/yesterday-summary/"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"DeviceKey {api_key}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"[MORNING] Failed to fetch yesterday summary: {e}")
        return None


# ============================================================
# Morning Review Modal Dialog
# ============================================================
class MorningReviewDialog:
    """
    Prominent modal dialog for reviewing yesterday's timesheet.
    Hard to miss — it's a full window, not a toast.
    """

    def __init__(
        self,
        summary: Optional[dict] = None,
        web_url: str = "https://timetracker.mavops.ai",
        config: MorningReviewConfig = None,
        parent_root=None,
    ):
        self.summary = summary
        self.web_url = web_url
        self.config = config or MorningReviewConfig()
        self.parent_root = parent_root
        self.result = None  # "review", "remind", "dismiss"

    def show(self):
        if not CTK_AVAILABLE:
            print("[MORNING] customtkinter not available")
            return None

        ctk.set_appearance_mode("dark")

        if self.parent_root:
            self.root = ctk.CTkToplevel(self.parent_root)
        else:
            self.root = ctk.CTk()

        self.root.title("Review Timesheet")
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        try:
            self.root.attributes("-alpha", 0.98)
        except Exception:
            pass

        width, height = 480, 440
        self.root.geometry(f"{width}x{height}")
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 3)
        self.root.geometry(f"+{x}+{y}")
        self.root.configure(fg_color=COLORS["bg_dark"])

        self._build_ui()

        if self.parent_root:
            self.root.grab_set()
            self.root.wait_window()
        else:
            self.root.mainloop()
            try:
                self.root.destroy()
            except Exception:
                pass

        return self.result

    def _build_ui(self):
        container = ctk.CTkFrame(self.root, fg_color=COLORS["bg_dark"])
        container.pack(fill="both", expand=True, padx=24, pady=20)

        # ── Header ──
        header = ctk.CTkFrame(container, fg_color="transparent")
        header.pack(fill="x", pady=(0, 16))

        ctk.CTkLabel(
            header, text="📋", font=ctk.CTkFont(size=30)
        ).pack(side="left")

        ctk.CTkLabel(
            header,
            text="Review Yesterday's Timesheet",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLORS["text"],
            anchor="w",
        ).pack(side="left", padx=(12, 0))

        ctk.CTkButton(
            header, text="✕", width=30, height=30, corner_radius=15,
            fg_color="transparent", hover_color=COLORS["bg_card"],
            text_color=COLORS["text_muted"], command=self._on_dismiss,
        ).pack(side="right")

        # ── Date ──
        yesterday = date.today() - timedelta(days=1)
        ctk.CTkLabel(
            container,
            text=yesterday.strftime("%A, %B %d"),
            font=ctk.CTkFont(size=14),
            text_color=COLORS["text_secondary"],
            anchor="w",
        ).pack(fill="x", pady=(0, 12))

        # ── Summary Card ──
        card = ctk.CTkFrame(container, fg_color=COLORS["bg_card"], corner_radius=10)
        card.pack(fill="x", pady=(0, 12))

        entries = []
        total_hours = 0.0
        status = "unknown"

        if self.summary:
            entries = self.summary.get("entries", [])
            total_hours = self.summary.get("total_hours", 0.0)
            status = self.summary.get("status", "draft")

        if entries:
            for entry in entries:
                row = ctk.CTkFrame(card, fg_color="transparent")
                row.pack(fill="x", padx=16, pady=(8, 2))

                client = entry.get("client_name") or entry.get("client", "Unknown")
                hours = entry.get("hours", 0)

                ctk.CTkLabel(
                    row, text=client, font=ctk.CTkFont(size=13),
                    text_color=COLORS["text"], anchor="w",
                ).pack(side="left", fill="x", expand=True)

                ctk.CTkLabel(
                    row, text=f"{hours:.1f} hrs",
                    font=ctk.CTkFont(size=13, weight="bold"),
                    text_color=COLORS["primary"],
                ).pack(side="right")

            # Divider
            ctk.CTkFrame(card, fg_color=COLORS["border"], height=1).pack(
                fill="x", padx=16, pady=(8, 4)
            )

            # Total
            total_row = ctk.CTkFrame(card, fg_color="transparent")
            total_row.pack(fill="x", padx=16, pady=(4, 12))
            ctk.CTkLabel(
                total_row, text="Total",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=COLORS["text"], anchor="w",
            ).pack(side="left")
            ctk.CTkLabel(
                total_row, text=f"{total_hours:.1f} hrs",
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=COLORS["primary"],
            ).pack(side="right")
        else:
            ctk.CTkLabel(
                card,
                text="No time tracked yesterday\nDid you forget to track your time?",
                font=ctk.CTkFont(size=13),
                text_color=COLORS["warning"],
                justify="center",
            ).pack(padx=16, pady=24)

        # ── Status Badge ──
        status_map = {
            "draft": (COLORS["warning"], "Draft — not submitted"),
            "submitted": (COLORS["primary"], "Submitted — pending approval"),
            "approved": (COLORS["success"], "Approved ✓"),
            "unknown": (COLORS["text_muted"], "Status unknown"),
        }
        color, label = status_map.get(status, status_map["unknown"])
        ctk.CTkLabel(
            container, text=f"●  {label}",
            font=ctk.CTkFont(size=12), text_color=color, anchor="w",
        ).pack(fill="x", pady=(0, 16))

        # ── Buttons ──
        btn_frame = ctk.CTkFrame(container, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(4, 0))

        ctk.CTkButton(
            btn_frame, text="📝  Review Now", command=self._on_review,
            fg_color=COLORS["primary"], hover_color=COLORS["primary_hover"],
            height=44, font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(side="left", expand=True, fill="x", padx=(0, 4))

        ctk.CTkButton(
            btn_frame, text="⏰  Later", command=self._on_remind,
            fg_color=COLORS["bg_card"], hover_color=COLORS["bg_item"],
            height=44, font=ctk.CTkFont(size=13),
            text_color=COLORS["text_secondary"],
        ).pack(side="left", expand=True, fill="x", padx=(4, 4))

        ctk.CTkButton(
            btn_frame, text="Skip", command=self._on_dismiss,
            fg_color="transparent", hover_color=COLORS["bg_card"],
            height=44, font=ctk.CTkFont(size=13),
            text_color=COLORS["text_muted"],
        ).pack(side="left", expand=True, fill="x", padx=(4, 0))

        self.root.bind("<Escape>", lambda e: self._on_dismiss())
        self.root.bind("<Return>", lambda e: self._on_review())

    # ── Actions ──

    def _on_review(self):
        self.result = "review"
        mark_dismissed()
        yesterday = date.today() - timedelta(days=1)
        url = f"{self.web_url}/daily?date={yesterday.isoformat()}"

        try:
            webbrowser.open(url)
            print(f"[MORNING] Opened timesheet: {url}")
        except Exception as e:
            print(f"[MORNING] Failed to open browser: {e}")
        self._close()

    def _on_remind(self):
        self.result = "remind"
        set_remind_later(self.config.remind_later_minutes)
        print(f"[MORNING] Remind later in {self.config.remind_later_minutes} min")
        self._close()

    def _on_dismiss(self):
        self.result = "dismiss"
        mark_dismissed()
        print("[MORNING] Dismissed for today")
        self._close()

    def _close(self):
        try:
            if self.parent_root:
                self.root.grab_release()
                self.root.destroy()
            else:
                self.root.quit()
        except Exception:
            pass


# ============================================================
# Manager — integrates with the agent
# ============================================================
class MorningReviewManager:
    """
    Manages the morning review workflow.
    
    Usage in main.py:
        from morning_review import MorningReviewManager
        
        review_mgr = MorningReviewManager(api_base, api_key)
        
        # On startup (schedule on main thread via floating widget):
        review_mgr.schedule_check(floating_widget.root, delay_seconds=8)
        
        # Background checker for "remind me later" timers:
        review_mgr.start_background_checker(floating_widget.root)
    """

    def __init__(
        self,
        api_base: str,
        api_key: str,
        web_url: str = "https://timetracker.mavops.ai",
        config: MorningReviewConfig = None,
    ):
        self.api_base = api_base
        self.api_key = api_key
        self.web_url = web_url
        self.config = config or MorningReviewConfig()
        self._showing = False

    def check_and_show(self, parent_root=None) -> Optional[str]:
        """Check if review is due, show dialog if so. Returns result or None."""
        if not self.config.enabled or self._showing:
            return None

        if not should_show_review(self.config):
            return None

        self._showing = True
        try:
            summary = fetch_yesterday_summary(self.api_base, self.api_key)
            print(f"[MORNING] Yesterday summary: {summary}")

            dialog = MorningReviewDialog(
                summary=summary,
                web_url=self.web_url,
                config=self.config,
                parent_root=parent_root,
            )
            result = dialog.show()
            print(f"[MORNING] Dialog result: {result}")
            return result
        except Exception as e:
            print(f"[MORNING] Error: {e}")
            import traceback
            traceback.print_exc()
            return None
        finally:
            self._showing = False

    def schedule_check(self, parent_root, delay_seconds: int = 8):
        """Schedule a check on the main thread (safe from any thread)."""
        if not parent_root:
            return
        try:
            parent_root.after(
                delay_seconds * 1000,
                lambda: self.check_and_show(parent_root=parent_root),
            )
            print(f"[MORNING] Scheduled startup check in {delay_seconds}s")
        except Exception as e:
            print(f"[MORNING] Failed to schedule: {e}")

    def start_background_checker(self, parent_root, interval_seconds: int = 300):
        """
        Background thread that checks every N seconds for remind-later timers.
        Schedules the actual dialog on the main thread via .after().
        """
        def _loop():
            while True:
                time.sleep(interval_seconds)
                try:
                    if should_show_review(self.config):
                        if parent_root:
                            parent_root.after(
                                0,
                                lambda: self.check_and_show(parent_root),
                            )
                except Exception as e:
                    print(f"[MORNING] Background check error: {e}")

        t = threading.Thread(target=_loop, daemon=True)
        t.start()
        print(f"[MORNING] Background checker started (every {interval_seconds}s)")


# ============================================================
# Standalone Test
# ============================================================
if __name__ == "__main__":
    test_summary = {
        "date": (date.today() - timedelta(days=1)).isoformat(),
        "total_hours": 7.5,
        "status": "draft",
        "entries": [
            {"client_name": "Acme Corp", "hours": 3.5},
            {"client_name": "Beta Industries", "hours": 2.0},
            {"client_name": "Internal / Admin", "hours": 1.5},
            {"client_name": "Uncategorized", "hours": 0.5},
        ],
    }

    print("Testing Morning Review Dialog...")
    dialog = MorningReviewDialog(summary=test_summary)
    result = dialog.show()
    print(f"Result: {result}")

    print("\nTesting with no data...")
    dialog2 = MorningReviewDialog(summary=None)
    result2 = dialog2.show()
    print(f"Result: {result2}")