"""
Tracks the floating widget's classification state based on whether the
active window's title/path/URL contains the current client's name or aliases.

State machine:
  committed     — title matched current client recently → green dot
  proposed      — no match for N minutes → yellow dot with "?"
  captured      — no match for N+M minutes → gray dot

Purely agent-side. No backend round-trip. Pushes state to the floating
widget via `floating_widget.update_client(client_id, client_name, state)`.

Hooked into the same window-change events that the AI client switcher uses,
so it costs nothing extra in CPU.
"""

import re
import time
from typing import Optional, List


# Time thresholds — how long without a match before downgrading state.
COMMITTED_TO_PROPOSED_SECONDS = 30      # 5 min: brief tab-switches OK
PROPOSED_TO_CAPTURED_SECONDS = 30 # 10 more min (15 total before gray)


class WidgetStateTracker:
    """State machine for the floating widget's color indicator."""

    def __init__(self):
        self._state = "captured"  # committed | proposed | captured
        self._last_match_time = 0.0    # epoch seconds of last successful title match
        self._last_state_change = time.time()

    @property
    def state(self) -> str:
        return self._state

    def on_user_set_client(self):
        """User explicitly picked a client — start fresh in committed state."""
        self._state = "committed"
        self._last_match_time = time.time()
        self._last_state_change = time.time()

    def on_window_change(
        self,
        window_title: Optional[str],
        file_path: Optional[str],
        url: Optional[str],
        current_client_name: Optional[str],
        current_client_aliases: Optional[List[str]] = None,
    ) -> str:
        """
        Called when the active window changes.

        Updates state based on whether the new window matches the current
        client. Returns the resulting state.
        """
        if not current_client_name:
            self._state = "captured"
            return self._state

        if self._title_matches_client(
            window_title, file_path, url,
            current_client_name, current_client_aliases or [],
        ):
            if self._state != "committed":
                self._state = "committed"
                self._last_state_change = time.time()
            self._last_match_time = time.time()
        else:
            self._evaluate_timed_demotion()

        return self._state

    def tick(self) -> str:
        """
        Called periodically (e.g., from the agent's dwell loop) to demote
        based on elapsed time. Useful when the user stays on a non-matching
        window for a long time without window-change events firing.
        """
        self._evaluate_timed_demotion()
        return self._state

    def _evaluate_timed_demotion(self):
        """Demote state based on elapsed time since last match."""
        if self._state == "committed":
            elapsed = time.time() - self._last_match_time
            if elapsed >= COMMITTED_TO_PROPOSED_SECONDS:
                self._state = "proposed"
                self._last_state_change = time.time()
        elif self._state == "proposed":
            elapsed = time.time() - self._last_match_time
            if elapsed >= COMMITTED_TO_PROPOSED_SECONDS + PROPOSED_TO_CAPTURED_SECONDS:
                self._state = "captured"
                self._last_state_change = time.time()

    @staticmethod
    def _title_matches_client(
        window_title: Optional[str],
        file_path: Optional[str],
        url: Optional[str],
        client_name: str,
        aliases: List[str],
    ) -> bool:
        """
        Check if any client signal appears in title, path, or URL.

        Uses flexible boundary matching that ignores common separators
        (whitespace, underscores, hyphens, dots, ampersands) so
        "Smith & Co" matches "smith_co" and "smith-co.pdf".
        """
        haystack = " ".join(filter(None, [
            (window_title or "").lower(),
            (file_path or "").lower(),
            (url or "").lower(),
        ]))
        if not haystack:
            return False

        needles = [client_name] + list(aliases or [])
        for needle in needles:
            n = (needle or "").strip()
            if len(n) < 3:
                continue
            escaped = re.escape(n.lower())
            # Allow common separators between original word boundaries
            flex = re.sub(r'[\\\s_\-\.&]+', r'[\\s_\\-.&]*', escaped)
            pattern = re.compile(
                r'(?:^|[\s\-_/\\.,()&])' + flex + r'(?:$|[\s\-_/\\.,()&])',
                re.IGNORECASE,
            )
            if pattern.search(haystack):
                return True
        return False


# Convenience singleton-like factory — most callers just need ONE instance.
_singleton: Optional[WidgetStateTracker] = None


def get_widget_state_tracker() -> WidgetStateTracker:
    """Return the process-wide WidgetStateTracker instance."""
    global _singleton
    if _singleton is None:
        _singleton = WidgetStateTracker()
    return _singleton