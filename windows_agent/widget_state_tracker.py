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

import os
import json
import threading
import time as _time

def _safe_print(*args, **kwargs):
    """Print that survives a closed stdout (happens when GUI parent detaches)."""
    try:
        print(*args, **kwargs)
    except (ValueError, OSError):
        pass

try:
    import customtkinter as ctk
    WIDGET_AVAILABLE = True
except ImportError:
    WIDGET_AVAILABLE = False

# Time thresholds — how long without a match before downgrading state.
COMMITTED_TO_PROPOSED_SECONDS = 300      # 5 min: brief tab-switches OK
PROPOSED_TO_CAPTURED_SECONDS = 600 # 10 more min (15 total before gray)


class WidgetStateTracker:
    """State machine for the floating widget's color indicator."""

    def __init__(self):
        self._state = "captured"  # committed | proposed | captured
        self._last_match_time = 0.0
        self._last_state_change = time.time()
        # Cache last-seen window context so tick() can re-evaluate
        self._last_title: Optional[str] = None
        self._last_path: Optional[str] = None
        self._last_url: Optional[str] = None
        self._last_client_name: Optional[str] = None
        self._last_aliases: List[str] = []

    @property
    def state(self) -> str:
        return self._state

    def on_user_set_client(self, client_name: Optional[str] = None,
                           aliases: Optional[List[str]] = None):
        """User explicitly picked a client — start fresh in committed state.

        Updates the tracker's cached client name AND aliases so subsequent
        tick() calls check against the NEW client (not the stale one from
        before the pick). Without this, tick() would re-evaluate against
        the previously-active client's name and immediately demote to
        proposed/captured, making the widget appear stuck in yellow even
        right after a manual pick.
        """
        self._state = "committed"
        self._last_match_time = time.time()
        self._last_state_change = time.time()
        if client_name is not None:
            self._last_client_name = client_name
        if aliases is not None:
            self._last_aliases = aliases

    def on_window_change(self, window_title, file_path, url,
                         current_client_name, current_client_aliases=None):
        # Cache for tick() re-evaluation
        self._last_title = window_title
        self._last_path = file_path
        self._last_url = url
        self._last_client_name = current_client_name
        self._last_aliases = current_client_aliases or []
        
        # DEBUG: print what we got + match result
        try:
            matched = self._title_matches_client(
                window_title, file_path, url,
                current_client_name, self._last_aliases
            ) if current_client_name else False
            _safe_print(
                f"[WIDGET-DBG] on_window_change "
                f"client={current_client_name!r} "
                f"matched={matched} "
                f"title={(window_title or '')[:60]!r} "
                f"path={(file_path or '')[:60]!r} "
                f"url={(url or '')[:60]!r}"
            )
        except Exception:
            pass

        if not current_client_name:
            self._state = "captured"
            return self._state

        if self._title_matches_client(window_title, file_path, url,
                                      current_client_name, self._last_aliases):
            if self._state != "committed":
                self._state = "committed"
                self._last_state_change = time.time()
            self._last_match_time = time.time()
        else:
            self._evaluate_timed_demotion()

        return self._state

    def tick(self) -> str:
        # Re-evaluate against last-seen context. If it still matches the
        # current client, refresh _last_match_time so demotion never fires.
        prev_state = self._state
        if self._last_client_name:
            matched = self._title_matches_client(
                self._last_title, self._last_path, self._last_url,
                self._last_client_name, self._last_aliases,
            )
            if matched:
                if self._state != "committed":
                    self._state = "committed"
                    self._last_state_change = time.time()
                self._last_match_time = time.time()
                return self._state

        self._evaluate_timed_demotion()

        # Diagnostic: log when tick demotes us, with the cached values it
        # was checking. Lets us see WHY a match failed for files/folders
        # that obviously contain the client name.
        if prev_state != self._state:
            try:
                import sys
                print(
                    f"[WIDGET-TRACKER] tick demoted {prev_state}→{self._state} "
                    f"client={self._last_client_name!r} "
                    f"title={(self._last_title or '')[:80]!r} "
                    f"path={(self._last_path or '')[:80]!r}",
                    file=sys.stdout, flush=True
                )
            except Exception:
                pass

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

    # Tokens that should never count as a "distinctive" partial-word match.
    # If a client name reduces to only these after stop-word filtering, fall
    # back to full-name match instead of partial-word.
    _STOP_WORDS = {
        "and", "the", "for", "inc", "llc", "ltd", "corp", "co", "company",
        "group", "tax", "firm", "cpas", "cpa", "associates", "partners",
        "services", "shop", "pet", "store", "inc.", "llc.",
    }

    @staticmethod
    def _strip_punct(s: str) -> str:
        """Lowercase + remove apostrophes for tolerant matching."""
        return (s or "").lower().replace("'", "").replace("\u2019", "")

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

        Three matching modes (any one wins):
          1. Full-name flexible match (ignores spaces/underscores/hyphens)
             so "Smith & Co" matches "smith_co" and "smith-co.pdf".
          2. Apostrophe-tolerant substring so "Lola's Pet Shop" matches
             "lolas pet shop" / "lolas_pet_shop".
          3. Partial-word match on distinctive tokens (5+ chars, not a
             stop word) so "Lola's Pet Shop" matches "Lolas_AR_Aging.xlsx"
             via the "lolas" token.
        """
        # Build raw + apostrophe-stripped haystacks.
        # URL-decode each input — browser URL bars show paths like
        # 'Dauphin%20&%20Fantacone' which would otherwise break boundary matching.
        from urllib.parse import unquote
        raw_hay = " ".join(filter(None, [
            unquote(window_title or "").lower(),
            unquote(file_path or "").lower(),
            unquote(url or "").lower(),
        ]))
        if not raw_hay:
            return False
        stripped_hay = WidgetStateTracker._strip_punct(raw_hay)

        needles = [client_name] + list(aliases or [])
        for needle in needles:
            n = (needle or "").strip()
            if len(n) < 3:
                continue

            # Mode 1: flexible full-name match against the raw haystack
            escaped = re.escape(n.lower())
            flex = re.sub(r'[\\\s_\-\.&]+', r'[\\s_\\-.&]*', escaped)
            pattern = re.compile(
                r'(?:^|[\s\-_/\\.,()&])' + flex + r'(?:$|[\s\-_/\\.,()&])',
                re.IGNORECASE,
            )
            if pattern.search(raw_hay):
                return True

            # Mode 2: apostrophe-stripped substring match
            n_stripped = WidgetStateTracker._strip_punct(n)
            if n_stripped and n_stripped in stripped_hay:
                return True

            # Mode 3: partial-word match on distinctive tokens
            tokens = re.split(r'[\s_\-.,&/\\\']+', n_stripped)
            distinctive = [
                t for t in tokens
                if len(t) >= 5 and t not in WidgetStateTracker._STOP_WORDS
            ]
            for tok in distinctive:
                tok_pattern = re.compile(
                    r'(?:^|[\s\-_/\\.,()&])' + re.escape(tok) + r'(?:[\s\-_/\\.,()&]|$|[a-z0-9])',
                    re.IGNORECASE,
                )
                if tok_pattern.search(stripped_hay):
                    return True
            
            # Mode 4: acronym match (e.g. "DF" matches "Dauphin & Fantacone").
            # Build acronym from first letter of each non-stopword token >=2 chars.
            # Acronym must be at least 2 letters and appear as its own token in the haystack.
            sig_tokens = [
                t for t in tokens
                if len(t) >= 2 and t not in WidgetStateTracker._STOP_WORDS
            ]
            if len(sig_tokens) >= 2:
                acronym = "".join(t[0] for t in sig_tokens).lower()
                if len(acronym) >= 2:
                    # Match acronym as a standalone token (separator on both sides
                    # OR followed by underscore/digit which is common in filenames)
                    acro_pattern = re.compile(
                        r'(?:^|[\s\-_/\\.,()&])' + re.escape(acronym) + r'(?:[\s\-_/\\.,()&]|$|[0-9])',
                        re.IGNORECASE,
                    )
                    if acro_pattern.search(stripped_hay):
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