"""
Floating widget state tracker.

v1.4.5 (sticky widget):
  The widget retains the last committed client for 5 min after the user
  leaves the recognized context (sticky green), then 5 more min in yellow ?
  (Phase 2 will add confirmation buttons), then transitions to captured.

  This is *stickiness*, not decay. Inference may say "no client" the moment
  user lands on an unrecognized window, but the widget keeps showing the
  previous client per user mental model: "I'm still working on Aurelia."

  Instant switch to a different recognized client overrides sticky. User
  idle 10+ min clears sticky (no auto-restore).

State machine:
  [Strong inference (cid + conf ≥ 0.40)]
    → COMMITTED, instant switch if new client, refresh if same
  [No inference, recently committed]
    → COMMITTED (sticky) for 5 min
    → PROPOSED (yellow ?) for 5 more min
    → CAPTURED after 10 min total
  [Idle 10+ min] → CAPTURED, clear sticky (no auto-restore)
  [User denied via ❌ (Phase 2)] → CAPTURED, no auto-restore
"""

import re
import time
from typing import Optional, List, Callable
from urllib.parse import unquote


def _safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except (ValueError, OSError):
        pass


COMMITTED_CONFIDENCE_THRESHOLD = 0.70
PROPOSED_CONFIDENCE_THRESHOLD = 0.40

# v1.4.5 sticky thresholds
STICKY_COMMITTED_S = 5 * 60    # green for first 5 min after leaving
STICKY_PROPOSED_S = 10 * 60    # yellow ? from 5–10 min, then captured


class WidgetStateTracker:
    """v1.4.5: sticky state on top of inference-driven base."""

    def __init__(self, on_demote_to_captured: Optional[Callable[[Optional[str]], None]] = None):
        self._on_demote_to_captured = on_demote_to_captured
        self._last_computed_state = "captured"
        self._last_client_name: Optional[str] = None

        # v1.4.5 sticky state
        self._last_committed_client_id: Optional[int] = None
        self._last_committed_client_name: Optional[str] = None
        self._unrecognized_since: Optional[float] = None  # epoch seconds
        self._user_denied: bool = False  # Phase 2 — red X clicked

    @property
    def state(self) -> str:
        return self._compute_state()

    @property
    def displayed_client_id(self) -> Optional[int]:
        """Sticky-aware client_id for widget display."""
        state = self._compute_state()
        if state in ("committed", "proposed"):
            return self._last_committed_client_id
        return None

    @property
    def displayed_client_name(self) -> Optional[str]:
        """Sticky-aware client name for widget display."""
        state = self._compute_state()
        if state in ("committed", "proposed"):
            return self._last_committed_client_name
        return None

    def _compute_state(self) -> str:
        """Sticky state machine reading inference cache."""
        try:
            from inference_cache import get_current_inference
        except ImportError:
            try:
                from windows_agent.inference_cache import get_current_inference
            except ImportError:
                return "captured"

        try:
            inf = get_current_inference()
        except Exception:
            inf = None

        now = time.time()
        cid = inf.get("client_id") if inf else None
        conf = (inf.get("confidence", 0.0) if inf else 0.0) or 0.0

        # Path 1: Strong current inference → instant switch (or refresh)
        if cid is not None and conf >= PROPOSED_CONFIDENCE_THRESHOLD:
            if cid != self._last_committed_client_id:
                # New recognized client → reset
                self._last_committed_client_id = cid
            # v1.5.1: pull name directly from inference dict
            # (get_current_inference includes 'client_name' field per
            # inference_cache.py line 109). This makes Path 1 self-
            # contained — no longer depends on on_window_change being
            # called with current_client_name to set the sticky name.
            inf_name = inf.get('client_name') if inf else None
            if inf_name:
                self._last_committed_client_name = inf_name
            self._unrecognized_since = None
            self._user_denied = False
            return "committed"

        # Path 2: User denied → captured
        if self._user_denied:
            return "captured"

        # Path 3: No prior sticky → captured
        if self._last_committed_client_id is None:
            return "captured"

        # Path 4: Sticky window — track elapsed time on unrecognized
        if self._unrecognized_since is None:
            self._unrecognized_since = now

        elapsed = now - self._unrecognized_since
        if elapsed < STICKY_COMMITTED_S:
            return "committed"  # sticky green
        elif elapsed < STICKY_PROPOSED_S:
            return "proposed"   # yellow ? — Phase 2 will add buttons
        else:
            # Timed out → clear sticky
            self._last_committed_client_id = None
            self._last_committed_client_name = None
            self._unrecognized_since = None
            return "captured"

    def set_on_demote_to_captured(self, callback: Callable[[Optional[str]], None]) -> None:
        self._on_demote_to_captured = callback

    def on_user_set_client(self,
                           client_id: Optional[int] = None,
                           client_name: Optional[str] = None,
                           aliases: Optional[List[str]] = None):
        """User explicitly picked a client. Lock sticky to this; clear denial."""
        if client_id is not None:
            self._last_committed_client_id = client_id
        if client_name is not None:
            self._last_client_name = client_name
            self._last_committed_client_name = client_name
        self._unrecognized_since = None
        self._user_denied = False
        self._last_computed_state = "committed"

    def on_window_change(self, window_title, file_path, url,
                         current_client_name, current_client_aliases=None,
                         current_client_id: Optional[int] = None):
        """
        v1.4.5: Update sticky NAME when inference identifies a client.
        client_id is updated in _compute_state based on inference cache.
        """
        if current_client_name is not None:
            self._last_client_name = current_client_name

        prev_state = self._last_computed_state
        new_state = self._compute_state()

        # If we just landed on a committed state with a known name, persist it
        if new_state == "committed" and current_client_name is not None:
            self._last_committed_client_name = current_client_name
            if current_client_id is not None:
                self._last_committed_client_id = current_client_id

        self._last_computed_state = new_state

        if prev_state != "captured" and new_state == "captured":
            self._fire_demote_callback()
        return new_state

    def tick(self) -> str:
        """Periodic re-evaluation. Handles sticky timer transitions."""
        prev_state = self._last_computed_state
        new_state = self._compute_state()
        self._last_computed_state = new_state

        if prev_state != "captured" and new_state == "captured":
            self._fire_demote_callback()
        return new_state

    def on_idle(self) -> None:
        """User went idle 10+ min. Clear sticky — no auto-restore on resume."""
        _safe_print("[WIDGET-TRACKER v1.4.5] on_idle — clearing sticky state")
        self._last_committed_client_id = None
        self._last_committed_client_name = None
        self._last_client_name = None
        self._unrecognized_since = None
        self._user_denied = False
        prev_state = self._last_computed_state
        self._last_computed_state = "captured"

        try:
            from inference_cache import clear_manual_override
            clear_manual_override()
        except ImportError:
            try:
                from windows_agent.inference_cache import clear_manual_override
                clear_manual_override()
            except ImportError:
                pass

        if prev_state != "captured":
            self._fire_demote_callback()

    def confirm_continue(self) -> None:
        """Phase 2: user clicked ✅ — reset 5-min timer, stay on current client."""
        self._unrecognized_since = None
        self._user_denied = False
        self._last_computed_state = "committed"

    def confirm_deny(self) -> None:
        """Phase 2: user clicked ❌ — clear sticky, no auto-restore."""
        self._user_denied = True
        self._last_committed_client_id = None
        self._last_committed_client_name = None
        self._unrecognized_since = None
        self._last_computed_state = "captured"
        try:
            from inference_cache import clear_manual_override
            clear_manual_override()
        except ImportError:
            try:
                from windows_agent.inference_cache import clear_manual_override
                clear_manual_override()
            except ImportError:
                pass
        self._fire_demote_callback()

    def _fire_demote_callback(self):
        stale = self._last_client_name
        _safe_print(
            f"[WIDGET-TRACKER v1.4.5] State demoted to captured. "
            f"Last client: {stale!r}"
        )
        if self._on_demote_to_captured:
            try:
                self._on_demote_to_captured(stale)
            except Exception as e:
                _safe_print(f"[WIDGET-TRACKER v1.4.5] demote callback raised: {e!r}")

    # ─── Title matching (unchanged from v1.4.5 pre-edit, used by collectors) ───

    _STOP_WORDS = {
        "and", "the", "for", "inc", "llc", "ltd", "corp", "co", "company",
        "group", "tax", "firm", "cpas", "cpa", "associates", "partners",
        "services", "shop", "pet", "store", "inc.", "llc.",
    }

    @staticmethod
    def _strip_punct(s: str) -> str:
        return (s or "").lower().replace("'", "").replace("\u2019", "")

    @staticmethod
    def _title_matches_client(
        window_title: Optional[str],
        file_path: Optional[str],
        url: Optional[str],
        client_name: str,
        aliases: List[str],
    ) -> bool:
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

            escaped = re.escape(n.lower())
            flex = re.sub(r'[\\\s_\-\.&]+', r'[\\s_\\-.&]*', escaped)
            pattern = re.compile(
                r'(?:^|[\s\-_/\\.,()&])' + flex + r'(?:$|[\s\-_/\\.,()&])',
                re.IGNORECASE,
            )
            if pattern.search(raw_hay):
                return True

            n_stripped = WidgetStateTracker._strip_punct(n)
            if n_stripped and n_stripped in stripped_hay:
                return True

            # Mode 3: partial-word match on distinctive tokens
            tokens = re.split(r'[\s_\-.,&/\\\']+', n_stripped)
            distinctive = [
                t for t in tokens
                if len(t) >= 5 and t not in WidgetStateTracker._STOP_WORDS
            ]
            # v1.5.9: Mode 3 fires only when the client name reduces to
            # a single MEANINGFUL token (>= 3 chars, non-stopword), not
            # just a single distinctive (>= 5 chars) token. v1.5.8's
            # distinctive-only gate was fooled by possessive-s:
            # "St. Mary's of the Lake" tokenizes to ['st','marys','of',
            # 'the','lake'] where only 'marys' (5) crosses the distinctive
            # threshold, falsely promoting a 5-token name to single-token
            # status. Counting all 3+ char non-stopword tokens (here
            # ['marys','lake']) correctly identifies it as multi-token.
            # Surname-only clients like "Bousselot" still match via Mode 3.
            meaningful_tokens = [
                t for t in tokens
                if len(t) >= 3 and t not in WidgetStateTracker._STOP_WORDS
            ]
            if len(meaningful_tokens) <= 1:
                for tok in distinctive:
                    tok_pattern = re.compile(
                        r'(?:^|[\s\-_/\\.,()&])' + re.escape(tok) + r'(?:[\s\-_/\\.,()&]|$)',
                        re.IGNORECASE,
                    )
                    if tok_pattern.search(stripped_hay):
                        return True

            sig_tokens = [
                t for t in tokens
                if len(t) >= 2 and t not in WidgetStateTracker._STOP_WORDS
            ]
            if len(sig_tokens) >= 2:
                acronym = "".join(t[0] for t in sig_tokens).lower()
                if len(acronym) >= 3:
                    # v1.5.7: tighten trailing boundary same as Mode 3.
                    # No letter or digit can follow the acronym.
                    acro_pattern = re.compile(
                        r'(?:^|[\s\-_/\\.,()&])' + re.escape(acronym) + r'(?:[\s\-_/\\.,()&]|$)',
                        re.IGNORECASE,
                    )
                    if acro_pattern.search(stripped_hay):
                        return True

        return False


_singleton: Optional[WidgetStateTracker] = None


def get_widget_state_tracker(
    on_demote_to_captured: Optional[Callable[[Optional[str]], None]] = None,
) -> WidgetStateTracker:
    global _singleton
    if _singleton is None:
        _singleton = WidgetStateTracker(on_demote_to_captured=on_demote_to_captured)
    elif on_demote_to_captured is not None and _singleton._on_demote_to_captured is None:
        _singleton.set_on_demote_to_captured(on_demote_to_captured)
    return _singleton