# tracker/services/billing_totals.py
"""
Single source of truth for Billable / Non-billable / Total / Needs-Review time.

WHY THIS EXISTS
---------------
Daily Review (`views.today_time`) and Reports (`views_reports.reports_summary`)
used to compute these four numbers independently, with DIFFERENT rules — four
different `is_billable` definitions, different block-state filters, and two
different data sources (RawEvent intervals vs Block.minutes). Result: the same
person/day showed different billable/non-bill/total on the two screens.

This module is the ONE computation everything should go through. The canonical
per-block math already lives (battle-tested) as the module-level helpers in
`tracker.views_reports` — `_block_queryset`, `_aggregate`, `_is_billable_block`,
`_pending_review_by_group`, `is_pending_review_block`, plus the anomaly /
materiality guards. Rather than fork that logic (and risk drift), this service
is a thin facade over those helpers, exposing a clean, request-free API that any
caller can use.

Product decisions encoded here (locked with the owner):
  1. Billable  = `is_billable` DB flag AND client_id AND not-internal-client
     (`_is_billable_block`). NOT category-based.
  2. Only CONFIRMED (committed) blocks count toward billable/non-billable/total.
     Unconfirmed captured/proposed blocks are Needs-Review only, via
     `is_pending_review_block`. Suppressed blocks are excluded everywhere.
  3. Block-based totals (sum Block.minutes), keeping the >6h anomaly guard and
     the sub-2-min immaterial handling. No event de-overlap.

IMPORT-CYCLE NOTE
-----------------
`views_reports` imports request helpers from `tracker.views`, and `tracker.views`
imports from `views_reports`. To stay clear of that cycle, this module does NOT
import `views_reports` at module load — every function imports the canonical
helpers lazily, at call time, when all modules are fully initialised.
"""
from __future__ import annotations

from collections import defaultdict


def committed_block_qs(org, start_utc, end_utc, *, user_id=None, can_see_all=True):
    """The confirmed-time block queryset for a window — the exact set Reports and
    Daily Review both count. Thin wrapper over `_block_queryset(committed_only=True)`.

    can_see_all=False + user_id → scoped to that one user (Daily Review's case).
    """
    from tracker.views_reports import _block_queryset
    return _block_queryset(
        org, start_utc, end_utc, can_see_all, user_id, committed_only=True
    )


def compute_totals(org, start_utc, end_utc, *, user_id=None, can_see_all=True) -> dict:
    """Canonical Billable / Non-billable / Total / Needs-Review for a window.

    Returns hours (2-dp, exactly as Reports rounds them) so callers match the
    Reports numbers byte-for-byte:
        {billable_hours, non_billable_hours, total_hours,
         needs_review_hours, needs_review_min}

    total_hours / non_billable_hours already fold in sub-2-min immaterial time,
    matching `_aggregate`'s totals block. Needs-Review (captured/proposed pending)
    is NOT added into total_hours here — that's a Reports presentation choice;
    Daily Review keeps Total = confirmed time.
    """
    from tracker.views_reports import _aggregate, _pending_review_by_group

    blocks = list(committed_block_qs(
        org, start_utc, end_utc, user_id=user_id, can_see_all=can_see_all
    ))
    totals = _aggregate(blocks, "employee")["totals"]
    review_min, _ = _pending_review_by_group(
        org, start_utc, end_utc, can_see_all, user_id, "employee"
    )
    return {
        "billable_hours": totals["billable_hours"],
        "non_billable_hours": totals["non_billable_hours"],
        "total_hours": totals["total_hours"],
        "needs_review_hours": round(review_min / 60, 2),
        "needs_review_min": review_min,
    }


def compute_client_cards(org, start_utc, end_utc, *, user_id, can_see_all=False) -> list:
    """Per-client cards for the Daily Review summary, built from the SAME
    committed block set and the SAME per-block inclusion rules as `compute_totals`
    / `_aggregate`, so the cards reconcile with the header totals.

    Card shape (unchanged frontend contract — see DailyReview.tsx / CategorySummary.tsx):
        {client_id, client, total_hours,
         categories: [{name, hours, block_count, unique_activities,
                       sample_activities, task_type_code, task_type_name}]}

    `sample_activities` preserve the load-bearing "[id:1,2] Title (5m)" prefix the
    frontend parses for click-to-move. Built from block fields (not RawEvents),
    exactly like the old block-based fallback did.
    """
    from tracker.views_reports import (
        _block_minutes, _dominant_category, _is_billable_block, _is_material,
        _EXCLUDE_CATEGORIES,
    )
    from tracker.utils.display_names import format_block_for_display, format_duration

    blocks = list(committed_block_qs(
        org, start_utc, end_utc, user_id=user_id, can_see_all=can_see_all
    ))

    data = defaultdict(lambda: {
        "client_id": None,
        "total_min": 0.0,
        "billable_min": 0.0,
        "non_billable_min": 0.0,
        "categories": defaultdict(lambda: {
            "minutes": 0.0,
            "block_count": 0,
            "by_activity": {},
        }),
    })

    for b in blocks:
        minutes = _block_minutes(b)          # 0 if anomalous (>6h) — dropped
        if minutes <= 0:
            continue

        cat_raw = _dominant_category(b)
        cat = cat_raw.lower()
        # Mirror _aggregate (views_reports.py:515): drop idle/uncategorized noise
        # UNLESS it's billable-with-client (real AI-proposed billable time).
        if cat in _EXCLUDE_CATEGORIES and not (b.is_billable and b.client_id):
            continue

        client_name = b.client.name if b.client_id else "Unassigned"
        d = data[client_name]
        d["client_id"] = b.client_id

        billable = _is_billable_block(b)
        # Immaterial (sub-2min) NON-billable slivers count in the client's ledger
        # total but get no category row — matches _aggregate's immaterial fold.
        if not _is_material(b) and not billable:
            d["total_min"] += minutes
            d["non_billable_min"] += minutes
            continue

        d["total_min"] += minutes
        d["billable_min" if billable else "non_billable_min"] += minutes
        cd = d["categories"][cat_raw]
        cd["minutes"] += minutes
        cd["block_count"] += 1

        formatted = format_block_for_display({
            "app_name": b.app_name or "",
            "window_title": b.window_title or "",
            "url": b.url or "",
            "minutes": minutes,
        }, client_name=client_name)
        clean_title = formatted["title"]

        if clean_title in cd["by_activity"]:
            cd["by_activity"][clean_title]["minutes"] += minutes
            if b.id is not None:
                cd["by_activity"][clean_title]["ids"].append(b.id)
        else:
            cd["by_activity"][clean_title] = {
                "id": b.id,
                "ids": [b.id] if b.id is not None else [],
                "title": clean_title,
                "minutes": minutes,
            }

    result = []
    for client_name in sorted(data.keys()):
        client_data = data[client_name]
        categories = []
        for cat_name in sorted(client_data["categories"].keys()):
            cd = client_data["categories"][cat_name]
            minutes = cd["minutes"]

            samples = []
            for clean_title, info in sorted(
                cd["by_activity"].items(), key=lambda x: -x[1]["minutes"]
            )[:10]:
                time_str = format_duration(info["minutes"])
                ids = info.get("ids") or ([info["id"]] if info.get("id") else [])
                seen = set()
                ids = [i for i in ids if not (i in seen or seen.add(i))]
                if ids:
                    id_str = ",".join(str(i) for i in ids)
                    samples.append(f"[id:{id_str}] {clean_title} ({time_str})")
                else:
                    samples.append(f"{clean_title} ({time_str})")

            task_type_code = None
            task_type_name = None
            try:
                from tracker.services.task_type_resolver import resolve_task_type_for_category
                tt = resolve_task_type_for_category(org, cat_name)
                if tt:
                    task_type_code = tt.code
                    task_type_name = tt.name
            except Exception:
                pass

            categories.append({
                "name": cat_name,
                "hours": round(minutes / 60, 2),
                "block_count": cd["block_count"],
                "unique_activities": len(cd["by_activity"]),
                "sample_activities": samples,
                "task_type_code": task_type_code,
                "task_type_name": task_type_name,
            })

        result.append({
            "client_id": client_data["client_id"],
            "client": client_name,
            "total_hours": round(client_data["total_min"] / 60, 2),
            "billable_hours": round(client_data["billable_min"] / 60, 2),
            "non_billable_hours": round(client_data["non_billable_min"] / 60, 2),
            "categories": categories,
        })

    return result


def is_pending_review_block(b) -> bool:
    """Re-export of the canonical Needs-Review predicate so per-block callers can
    depend on this service instead of reaching into views_reports."""
    from tracker.views_reports import is_pending_review_block as _impl
    return _impl(b)
