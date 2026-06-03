"""
Floating widget state tracker.

v1.4 (inference architecture):
  The committed/proposed/captured state is now derived from the inference
  cache's confidence level instead of a separate title-matching state machine.
  This eliminates the duplication where AIClientSwitcher state and inference
  confidence would fight over the widget color.

Mapping:
  confidence >= 0.70 → committed (green)
  confidence >= 0.40 → proposed (yellow)
  confidence  < 0.40 → captured (gray)
  no client_id       → captured (gray)

The _title_matches_client static method is preserved because the inference
engine's collectors (Tier 1: title_alias_match) use it for evidence matching.

Pre-v1.4 docstring (kept for context):
  State machine:
    committed     — title matched current client recently → green dot
    proposed      — no match for N minutes → yellow dot with "?"
    captured      — no match for N+M minutes → gray dot

  v1.3.47 introduced on_demote_to_captured callback to clear stale client
  state when widget went gray. In v1.4 this is no longer needed because
  inference confidence decays linearly to zero over 15 min — there's no
  "stale current_client" to clear. The callback hook is preserved as a
  no-op for backwards compatibility.
"""

import re
from typing import Optional, List, Callable
from urllib.parse import unquote


def _safe_print(*args, **kwargs):
    """Print that survives a closed stdout (happens when GUI parent detaches)."""
    try:
        print(*args, **kwargs)
    except (ValueError, OSError):
        pass


# Confidence thresholds for widget color mapping.
COMMITTED_CONFIDENCE_THRESHOLD = 0.70  # green dot
PROPOSED_CONFIDENCE_THRESHOLD = 0.40   # yellow dot
# < PROPOSED_CONFIDENCE_THRESHOLD → captured (gray)


class WidgetStateTracker:
    """
    v1.4: Thin wrapper around inference_cache.

    The state property reads inference confidence and maps it to widget color.
    on_window_change and tick are no-ops that simply re-read inference state.

    Title-matching logic (_title_matches_client) is preserved because the
    inference engine's title_alias_match collector uses it.
    """

    def __init__(self, on_demote_to_captured: Optional[Callable[[Optional[str]], None]] = None):
        self._on_demote_to_captured = on_demote_to_captured
        self._last_computed_state = "captured"
        self._last_client_name: Optional[str] = None

    @property
    def state(self) -> str:
        return self._compute_state()

    def _compute_state(self) -> str:
        """Read inference cache and map confidence to widget state.

        v1.4.4: Hysteresis. Once committed, stay committed until confidence
        falls below the captured threshold. Without this, decay between
        heartbeats (~60s) causes flicker: committed → proposed → committed
        while the user is on the same client window. Linear decay over
        15 min would push confidence through the 0.70 threshold ~3 min in,
        but the next heartbeat refreshes it — making 'proposed' a transient
        state that briefly flashes between heartbeats.

        With hysteresis: committed sticks until confidence drops below
        0.40 (which only happens after ~8 min of NO new inference, i.e.
        the user has clearly left the client context).
        """
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
            return "captured"

        if not inf:
            return "captured"

        client_id = inf.get("client_id")
        confidence = inf.get("confidence", 0.0) or 0.0

        if client_id is None or confidence < PROPOSED_CONFIDENCE_THRESHOLD:
            return "captured"

        # Hysteresis: once committed, stay committed until confidence
        # drops below the captured threshold. Prevents flicker during
        # normal decay between heartbeats.
        if self._last_computed_state == "committed":
            return "committed"

        # Fresh transition (captured → proposed or → committed):
        if confidence < COMMITTED_CONFIDENCE_THRESHOLD:
            return "proposed"
        return "committed"

    def set_on_demote_to_captured(self, callback: Callable[[Optional[str]], None]) -> None:
        """Late-bind demote callback (preserved for backwards compatibility)."""
        self._on_demote_to_captured = callback

    def on_user_set_client(self, client_name: Optional[str] = None,
                           aliases: Optional[List[str]] = None):
        """
        User explicitly picked a client. Force state to 'committed' since
        the user made an explicit choice — independent of what the inference
        cache currently shows. The cache may or may not have been updated
        yet in the same call chain; either way a manual pick should always
        render the widget as committed (green) immediately.

        v1.4.3: Defensive against the stale-state race that caused
        floating widget to show captured for ~1 minute after a manual
        pick (cache was updated AFTER the widget refresh in main.py
        pre-v1.4.3).
        """
        if client_name is not None:
            self._last_client_name = client_name
        self._last_computed_state = "committed"

    def on_window_change(self, window_title, file_path, url,
                         current_client_name, current_client_aliases=None):
        """
        v1.4: no-op for state machine purposes.

        Inference engine has already evaluated this window and updated
        the inference cache by the time the agent's event handler runs.
        We just check for a captured-edge transition for the demote callback.
        """
        if current_client_name is not None:
            self._last_client_name = current_client_name

        prev_state = self._last_computed_state
        new_state = self._compute_state()
        self._last_computed_state = new_state

        if prev_state != "captured" and new_state == "captured":
            self._fire_demote_callback()

        return new_state

    def tick(self) -> str:
        """
        v1.4: re-evaluate state from inference cache.

        Called periodically by the agent. Inference confidence decays
        linearly to zero over 15 min, so state transitions
        committed → proposed → captured as evidence ages.
        """
        prev_state = self._last_computed_state
        new_state = self._compute_state()
        self._last_computed_state = new_state

        if prev_state != "captured" and new_state == "captured":
            self._fire_demote_callback()

        return new_state

    def _fire_demote_callback(self):
        """
        v1.4: hook preserved for backwards compatibility.

        In the old architecture, this cleared the agent's stale current_client.
        With inference decay, current_client is the highest-confidence client
        in the cache, which naturally drops to None as evidence ages — so
        nothing needs to be cleared.

        The hook still fires so existing callers that log demote events
        continue to work.
        """
        stale = self._last_client_name
        _safe_print(
            f"[WIDGET-TRACKER v1.4] State demoted to captured "
            f"(confidence dropped below {PROPOSED_CONFIDENCE_THRESHOLD}). "
            f"Stale client: {stale!r}"
        )
        if self._on_demote_to_captured:
            try:
                self._on_demote_to_captured(stale)
            except Exception as e:
                _safe_print(f"[WIDGET-TRACKER v1.4] demote callback raised: {e!r}")

    # ─── Title matching (preserved from v1.3 — used by inference collectors) ───

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
        Used by inference engine's title_alias_match collector. Preserved
        unchanged from v1.3.

        Four matching modes (any one wins):
          1. Full-name flexible match
          2. Apostrophe-tolerant substring
          3. Partial-word match on distinctive tokens (5+ chars, not stop)
          4. Acronym match (e.g. "DF" for "Dauphin & Fantacone")
        """
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

            # Mode 1: flexible full-name match
            escaped = re.escape(n.lower())
            flex = re.sub(r'[\\\s_\-\.&]+', r'[\\s_\\-.&]*', escaped)
            pattern = re.compile(
                r'(?:^|[\s\-_/\\.,()&])' + flex + r'(?:$|[\s\-_/\\.,()&])',
                re.IGNORECASE,
            )
            if pattern.search(raw_hay):
                return True

            # Mode 2: apostrophe-stripped substring
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

            # Mode 4: acronym match
            sig_tokens = [
                t for t in tokens
                if len(t) >= 2 and t not in WidgetStateTracker._STOP_WORDS
            ]
            if len(sig_tokens) >= 2:
                acronym = "".join(t[0] for t in sig_tokens).lower()
                if len(acronym) >= 2:
                    acro_pattern = re.compile(
                        r'(?:^|[\s\-_/\\.,()&])' + re.escape(acronym) + r'(?:[\s\-_/\\.,()&]|$|[0-9])',
                        re.IGNORECASE,
                    )
                    if acro_pattern.search(stripped_hay):
                        return True

        return False


# Convenience singleton-like factory — most callers just need ONE instance.
_singleton: Optional[WidgetStateTracker] = None


def get_widget_state_tracker(
    on_demote_to_captured: Optional[Callable[[Optional[str]], None]] = None,
) -> WidgetStateTracker:
    """Return the process-wide WidgetStateTracker instance."""
    global _singleton
    if _singleton is None:
        _singleton = WidgetStateTracker(on_demote_to_captured=on_demote_to_captured)
    elif on_demote_to_captured is not None and _singleton._on_demote_to_captured is None:
        _singleton.set_on_demote_to_captured(on_demote_to_captured)
    return _singleton