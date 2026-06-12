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
import logging

from django.shortcuts import get_object_or_404
from django.utils import timezone

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tracker.models import Block, RawEvent, Client
from tracker.auth import AgentKeyAuthentication, BearerTokenAuthentication

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
# Surrounding context (v0.1) — temporal neighbor advice for nameless blocks
# =============================================================================
#
# Many blocks have no client identity in their own title (QuickBooks splash /
# modal screens like "Preview Paycheck", "Select Date Range", or the bare
# "QuickBooks Accountant Desktop Plus 2024"). The classifier correctly refuses
# to guess and parks them non-billable. But a human can often tell who the
# work was for by looking at what client they were on immediately before and
# after — especially when it's the SAME app (e.g. QuickBooks both sides).
#
# This helper surfaces that context as ADVICE, never as an auto-commit. It
# returns the nearest attributed neighbor on each side, the gap, whether the
# neighbor shares the block's app (strong continuity signal), and a weighted
# suggestion the UI can offer as a one-click assign.

# QuickBooks process names (mirror the agent / classifier vocabulary)
_QB_APPS = {"qbw", "qbw.exe", "qbw32", "qbw32.exe"}

# Only look this far for an attributed neighbor on either side.
_NEIGHBOR_WINDOW_SECONDS = 30 * 60


def _app_key(app_name: str) -> str:
    return (app_name or "").strip().lower()


def _is_qb(app_name: str) -> bool:
    return _app_key(app_name) in _QB_APPS


def _neighbor_payload(neighbor: Block, target: Block, side: str) -> Dict[str, Any]:
    """Serialize one neighboring attributed block for the context panel."""
    if side == "before":
        gap = max(0, int((target.start - neighbor.end).total_seconds())) \
            if (target.start and neighbor.end) else None
        edge = neighbor.end
    else:  # after
        gap = max(0, int((neighbor.start - target.end).total_seconds())) \
            if (target.end and neighbor.start) else None
        edge = neighbor.start

    same_app = _app_key(neighbor.app_name) == _app_key(target.app_name) \
        and bool(_app_key(target.app_name))
    same_qb_session = _is_qb(neighbor.app_name) and _is_qb(target.app_name)

    return {
        "block_id": neighbor.id,
        "client_id": neighbor.client_id,
        "client_name": neighbor.client.name if neighbor.client else None,
        "at": edge.isoformat() if edge else None,
        "gap_seconds": gap,
        "app_name": neighbor.app_name or "",
        "window_title": (neighbor.window_title or "")[:80],
        "same_app": same_app,
        "same_qb_session": same_qb_session,
    }


def _build_surrounding(block: Block) -> Optional[Dict[str, Any]]:
    """
    Find nearest attributed blocks before/after `block` and derive a
    read-only suggestion. Returns None when the block already has a client
    (no help needed) or when there are no attributed neighbors at all.
    """
    # Block already attributed — context panel not needed.
    if block.client_id:
        return None
    if not block.start or not block.end:
        return None

    win_start = block.start - timezone.timedelta(seconds=_NEIGHBOR_WINDOW_SECONDS)
    win_end = block.end + timezone.timedelta(seconds=_NEIGHBOR_WINDOW_SECONDS)

    # Nearest attributed block ending at/before this block starts.
    before = (
        Block.objects
        .filter(user=block.user, org=block.org,
                client_id__isnull=False,
                end__lte=block.start, end__gte=win_start)
        .exclude(id=block.id)
        .select_related("client")
        .order_by("-end")
        .first()
    )
    # Nearest attributed block starting at/after this block ends.
    after = (
        Block.objects
        .filter(user=block.user, org=block.org,
                client_id__isnull=False,
                start__gte=block.end, start__lte=win_end)
        .exclude(id=block.id)
        .select_related("client")
        .order_by("start")
        .first()
    )

    if not before and not after:
        return None

    before_p = _neighbor_payload(before, block, "before") if before else None
    after_p = _neighbor_payload(after, block, "after") if after else None

    suggestion = _derive_context_suggestion(before_p, after_p)

    return {
        "before": before_p,
        "after": after_p,
        "suggestion": suggestion,
    }


def _derive_context_suggestion(
    before: Optional[Dict[str, Any]],
    after: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Turn before/after neighbors into a single weighted suggestion.

    Confidence tiers (advice only — UI offers, human confirms):
      high   — both sides agree on the same client
      high   — one side, same QuickBooks session (e.g. QB splash → named QB file)
      medium — one side, same app (non-QB)
      low    — one side, different app  (weak; show context, soft suggest)
      none   — sides disagree and neither is a same-app continuation

    Same-app/same-QB continuity matters more than raw time proximity: a QB
    block two minutes from a named QB file is far stronger evidence than an
    Outlook block two minutes away.
    """
    b_cid = before["client_id"] if before else None
    a_cid = after["client_id"] if after else None

    def _suggest(cid, name, tier, reason):
        return {"client_id": cid, "client_name": name,
                "confidence": tier, "reason": reason}

    # Both sides agree → strongest.
    if b_cid and a_cid and b_cid == a_cid:
        return _suggest(
            b_cid, before["client_name"], "high",
            f"You were on {before['client_name']} both just before and just after this block.",
        )

    # Sides disagree: prefer a same-QB-session continuation if exactly one exists.
    if b_cid and a_cid and b_cid != a_cid:
        qb_sides = [s for s in (before, after) if s and s["same_qb_session"]]
        if len(qb_sides) == 1:
            s = qb_sides[0]
            return _suggest(
                s["client_id"], s["client_name"], "medium",
                f"Same QuickBooks session as {s['client_name']} "
                f"{'just after' if s is after else 'just before'} this block.",
            )
        # Genuine ambiguity — no confident pick. UI shows both, suggests nothing.
        return None

    # Exactly one side has a client.
    side = before if b_cid else after
    if not side:
        return None
    where = "just before" if side is before else "just after"

    if side["same_qb_session"]:
        return _suggest(
            side["client_id"], side["client_name"], "high",
            f"Same QuickBooks session as {side['client_name']} {where} this block.",
        )
    if side["same_app"]:
        return _suggest(
            side["client_id"], side["client_name"], "medium",
            f"Same application ({side['app_name']}) as {side['client_name']} {where}.",
        )
    return _suggest(
        side["client_id"], side["client_name"], "low",
        f"{side['client_name']} was the nearest attributed work, {where} this block.",
    )

# =============================================================================
# Endpoint
# =============================================================================

@api_view(["GET"])
@authentication_classes([AgentKeyAuthentication, BearerTokenAuthentication])
@permission_classes([IsAuthenticated])
def block_evidence(request, block_id: int):
    """
    GET /api/blocks/{block_id}/evidence/

    Returns the raw events backing this block, plus per-event signal
    detection results, plus a summary roll-up by suggested client.
    """
    user = request.user

    # ── Fetch block ──
    block = get_object_or_404(
        Block.objects.select_related("client", "org", "user"),
        id=block_id,
    )

    # ── Authorization: user must be a member of the block's org ──
    # Use the membership relation (NOT user.organization_id, which doesn't
    # exist on this User model — confirmed via Django shell earlier).
    # MavOps admins and Django superusers can see any block.
    is_member = user.memberships.filter(organization_id=block.org_id).exists()
    is_mavops_admin = getattr(user, "is_mavops_admin", False) or user.is_superuser

    if not is_member and not is_mavops_admin:
        return Response({"error": "forbidden"}, status=403)

    # ── Fetch the client list once for signal matching ──
    org_clients = list(
        Client.objects.filter(org=block.org).values("id", "name", "aliases")
    )

    # ── Fetch raw events for this block ──
    events_list = list(
        RawEvent.objects.filter(block=block).order_by("start_ts")
    )

    if not events_list:
        return Response({
            "block": _serialize_block(block),
            "suggestion": _serialize_suggestion(block),
            "surrounding": _build_surrounding(block),
            "events": [],
            "summary": {"total_events": 0, "events_per_client": {}},
        })

    block_start = block.start
    serialized_events = []
    per_client_rollup: Dict[int, Dict[str, Any]] = {}

    for ev in events_list:
        # Calculate offset relative to block start (always >= 0)
        offset_seconds = max(0, int((ev.start_ts - block_start).total_seconds()))
        duration_seconds = (
            max(0, int((ev.end_ts - ev.start_ts).total_seconds()))
            if ev.end_ts else 0
        )

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
            "end_ts": ev.end_ts.isoformat() if ev.end_ts else None,
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

    return Response({
        "block": _serialize_block(block),
        "suggestion": _serialize_suggestion(block),
        "surrounding": _build_surrounding(block),
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