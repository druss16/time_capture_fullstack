# tracker/views_block_evidence.py
"""
Block evidence endpoint — v0.

Returns the raw events backing a Block, plus the signals each event
contributes toward client attribution. Used by:
  - AI suggestion banner "Show details" expansion (user-facing)
  - MavOpsAdmin block detail view (admin debugging)

v0 signals shipped:
  - agent_selection: the client_id the agent had selected when the
    event was captured (from RawEvent.current_client_id)
  - title_alias: when an event's window_title contains a client name
    or alias substring

NOT in v0 (deferred to v1):
  - mail/calendar matches (require Stage 7 metadata storage)
  - AI category from Stage 10 (need to persist per-event, not per-block)
  - learned-rule and CPA-file-convention matches

The endpoint is intentionally pure-read; it never mutates blocks,
events, or classifications. Safe to call from anywhere, any number
of times.
"""

from __future__ import annotations
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
import os
import re

from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.views.decorators.cache import never_cache

from tracker.models import Block, RawEvent, Client
from tracker.auth import BearerTokenAuthentication  # adjust to your auth path

import logging
logger = logging.getLogger(__name__)


# =============================================================================
# Helpers
# =============================================================================

def _url_host(url: str) -> Optional[str]:
    """Extract just the host (no path, no query) — privacy + display."""
    if not url:
        return None
    try:
        parsed = urlparse(url if "://" in url else f"http://{url}")
        host = (parsed.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host or None
    except Exception:
        return None


def _file_basename(file_path: str) -> Optional[str]:
    """Just the filename, no directory — privacy + display."""
    if not file_path:
        return None
    normalized = file_path.replace("\\", "/")
    base = os.path.basename(normalized)
    return base or None


def _normalize_for_match(s: str) -> str:
    """Lowercase + collapse whitespace for substring matching."""
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def _find_alias_matches(
    window_title: str,
    clients: List[Dict[str, Any]],
    exclude_client_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    For each client, check whether its name or any alias appears as a
    substring of the window_title. Returns a list of match dicts:
    {client_id, client_name, matched_token, match_position, confidence}

    This is a deliberately simple substring check — NOT the full
    title_alias logic from ai_client_switcher.py. v0 prioritizes
    "ship something useful" over "perfect parity with classifier."
    A v1 refactor can swap in the real detect_signals() once the
    classifier is restructured.
    """
    if not window_title:
        return []

    title_norm = _normalize_for_match(window_title)
    hits = []

    for client in clients:
        cid = client["id"]
        if exclude_client_id is not None and cid == exclude_client_id:
            # Don't flag a "match" for the client the agent already had
            # selected — that's covered by agent_selection, separately.
            continue

        candidates = [client["name"]] + list(client.get("aliases", []) or [])
        for needle in candidates:
            if not needle or len(needle) < 3:
                continue
            needle_norm = _normalize_for_match(needle)
            if not needle_norm:
                continue

            pos = title_norm.find(needle_norm)
            if pos < 0:
                continue

            # Map back to the original (non-normalized) title position
            # for highlighting. Approximation: use the normalized pos
            # directly; close enough for highlighting purposes since
            # whitespace differences are rare in window titles.
            orig_pos = window_title.lower().find(needle.lower())
            if orig_pos < 0:
                orig_pos = pos

            confidence = 0.85 if needle == client["name"] else 0.80

            hits.append({
                "type": "title_alias",
                "client_id": cid,
                "client_name": client["name"],
                "matched_token": needle,
                "match_position": [orig_pos, orig_pos + len(needle)],
                "confidence": confidence,
                "description": (
                    f"Title contains '{needle}'"
                    + (f" (alias for {client['name']})" if needle != client["name"] else "")
                ),
            })
            break  # only count the first matching needle per client

    return hits


# =============================================================================
# Endpoint
# =============================================================================

@require_GET
@never_cache
def block_evidence(request, block_id: int):
    """
    GET /api/blocks/{block_id}/evidence/

    Returns the raw events backing this block, plus per-event signal
    detection results, plus a summary roll-up by suggested client.
    """
    # ── Auth ──
    auth = BearerTokenAuthentication()
    try:
        user_auth = auth.authenticate(request)
    except Exception as e:
        return JsonResponse({"error": "auth_failed", "detail": str(e)}, status=401)

    if not user_auth:
        return JsonResponse({"error": "unauthorized"}, status=401)

    user, _ = user_auth

    # ── Fetch block, scoped to user's org ──
    block = get_object_or_404(
        Block.objects.select_related("client", "org", "user"),
        id=block_id,
    )

    # Authorization: user must be in the block's org, OR be a MavOps admin
    if block.org_id != getattr(user, "organization_id", None):
        # Check MavOps admin override
        if not getattr(user, "is_mavops_admin", False):
            return JsonResponse({"error": "forbidden"}, status=403)

    # ── Fetch the client list once for signal matching ──
    org_clients_qs = Client.objects.filter(org=block.org).values(
        "id", "name", "aliases"
    )
    org_clients = list(org_clients_qs)

    # ── Fetch raw events for this block ──
    events_qs = RawEvent.objects.filter(block=block).order_by("start_ts")
    events_list = list(events_qs)

    if not events_list:
        return JsonResponse({
            "block": _serialize_block(block),
            "suggestion": _serialize_suggestion(block),
            "events": [],
            "summary": {"total_events": 0, "events_per_client": {}},
        })

    block_start = block.start
    serialized_events = []
    per_client_rollup: Dict[int, Dict[str, Any]] = {}

    for ev in events_list:
        # Calculate offset relative to block start (always >= 0)
        offset_seconds = max(0, int((ev.start_ts - block_start).total_seconds()))
        duration_seconds = max(0, int((ev.end_ts - ev.start_ts).total_seconds()))

        # ── Collect signals for this event ──
        signals: List[Dict[str, Any]] = []

        # Signal 1: agent_selection (what current_client_id was set to)
        if ev.current_client_id:
            sel_client = next(
                (c for c in org_clients if c["id"] == ev.current_client_id),
                None,
            )
            if sel_client:
                signals.append({
                    "type": "agent_selection",
                    "client_id": sel_client["id"],
                    "client_name": sel_client["name"],
                    "description": f"Agent had {sel_client['name']} selected",
                })

        # Signal 2: title_alias matches (excluding the agent_selection client
        # so we don't double-credit it)
        alias_hits = _find_alias_matches(
            ev.window_title or "",
            org_clients,
            exclude_client_id=ev.current_client_id,
        )
        signals.extend(alias_hits)

        serialized_events.append({
            "id": ev.id,
            "offset_seconds": offset_seconds,
            "start_ts": ev.start_ts.isoformat(),
            "end_ts": ev.end_ts.isoformat(),
            "duration_seconds": duration_seconds,
            "app_name": ev.app_name or "",
            "window_title": ev.window_title or "",
            "url_host": _url_host(ev.url),
            "file_basename": _file_basename(ev.file_path),
            "signals": signals,
        })

        # ── Build the per-client rollup ──
        # Attribute this event's duration to whichever client has the
        # highest-confidence signal on it. Ties broken by signal order
        # (agent_selection first, then alias).
        winning_client_id = None
        winning_confidence = -1.0

        for sig in signals:
            sig_conf = sig.get("confidence", 1.0)  # agent_selection has no conf
            if sig_conf > winning_confidence:
                winning_confidence = sig_conf
                winning_client_id = sig["client_id"]

        if winning_client_id:
            entry = per_client_rollup.setdefault(winning_client_id, {
                "name": next(
                    (c["name"] for c in org_clients if c["id"] == winning_client_id),
                    "?",
                ),
                "event_count": 0,
                "duration_seconds": 0,
            })
            entry["event_count"] += 1
            entry["duration_seconds"] += duration_seconds

    return JsonResponse({
        "block": _serialize_block(block),
        "suggestion": _serialize_suggestion(block),
        "events": serialized_events,
        "summary": {
            "total_events": len(serialized_events),
            "events_per_client": {
                str(cid): data for cid, data in per_client_rollup.items()
            },
        },
    })


def _serialize_block(block: Block) -> Dict[str, Any]:
    return {
        "id": block.id,
        "start": block.start.isoformat() if block.start else None,
        "end": block.end.isoformat() if block.end else None,
        "minutes": block.minutes,
        "app_name": block.app_name or "",
        "window_title": block.window_title or "",
        "current_client": (
            {
                "id": block.client_id,
                "name": block.client.name if block.client else None,
                "source": getattr(block, "categorized_by", None) or "unknown",
            }
            if block.client_id
            else None
        ),
    }


def _serialize_suggestion(block: Block) -> Optional[Dict[str, Any]]:
    """
    If the block has a pending AI suggestion (Stage 8/10), serialize it.
    Returns None if no suggestion exists.

    Reads from block.hints / block.proposed_client_id / wherever your
    suggestion metadata lives. Adjust field names to match your schema.
    """
    proposed_id = getattr(block, "proposed_client_id", None)
    if not proposed_id:
        return None

    try:
        proposed_client = Client.objects.only("id", "name").get(id=proposed_id)
    except Client.DoesNotExist:
        return None

    hints = getattr(block, "hints", {}) or {}

    return {
        "suggested_client": {
            "id": proposed_client.id,
            "name": proposed_client.name,
        },
        "confidence": hints.get("proposal_confidence"),
        "method": hints.get("proposal_method"),
        "ai_category": hints.get("ai_category"),  # {label, confidence, rationale}
    }