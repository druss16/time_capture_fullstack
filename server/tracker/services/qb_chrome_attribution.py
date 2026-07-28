"""
QB-chrome attribution — attribute unattributed QuickBooks dialog/chrome blocks
to the client whose company file was concurrently open.

QuickBooks Desktop keeps ONE company file open at a time, so a chrome dialog
("Preview Paycheck", "Print Checks", "Save Print Output As", empty titles) at
time T belongs to whichever client's committed Qbw.Exe block overlaps T. The
generic Stage Sandwich can't catch these because it requires NON-overlapping
"bread", but the attributed QB work OVERLAPS the chrome.

This is a SECOND-PASS signal: it depends on the surrounding QB blocks already
being committed with a client, which is only guaranteed once a day has settled.
It therefore runs nightly (tracker.tasks.attribute_qb_chrome_all) over a
trailing window, NOT inline in the real-time classifier.

Tiers per target block:
  OVERLAP    exactly one committed-billable Qbw client overlaps in time -> commit
  NEAR       no overlap, exactly one such client within `gap` min       -> propose
  AMBIGUOUS  >1 distinct client overlaps/near                           -> abstain
  NONE       no committed Qbw anchor                                    -> abstain

Every write is stamped proposed_reasoning startswith '[qb-chrome]', so the whole
effect is reversible with a single filtered query.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from django.db import transaction

from tracker.models import Block, Client
from tracker.services.classification_service import (
    ClassificationService as C,
    GENERIC_HAYSTACK_WORDS,
)

QB_APP = "Qbw.Exe"
MARK = "[qb-chrome] inherits concurrently-open QuickBooks company file"

# Ordinary accounting nouns that look distinctive but never name a client.
# Only used by the (currently unused) chrome-title heuristic; kept for callers
# that want to restrict to pure chrome. The default target set is "any
# unattributed QB block" because being unattributed already means the title
# failed to name a client.
_COMMON_STOPWORDS = {
    "plus", "with", "account", "used", "born", "park", "health", "being",
    "resource", "credit", "sale", "sales", "corporate", "corp", "paycheck",
    "payroll", "reconciliation", "report", "reports", "print", "printing",
}


def _has_client_token(title: str) -> bool:
    n = C._normalize_name(title or "")
    return any(
        len(t) >= 4 and t not in GENERIC_HAYSTACK_WORDS and t not in _COMMON_STOPWORDS
        for t in n.split()
    )


def classify_targets(org, start: dt.date, end: dt.date, gap: int = 10):
    """Return {tier: [(block, client_id_or_None, reason), ...]} for the window.

    Read-only. `apply_attribution` consumes this.
    """
    q = (Block.objects
         .filter(org=org, app_name__iexact=QB_APP, client__isnull=True,
                 approved=False, day__gte=start, day__lte=end)
         .exclude(classification_state__in=["committed", "suppressed"]))
    targets = [b for b in q if b.start and b.end]

    anchors_by_ud: dict[tuple, list] = defaultdict(list)
    anchor_qs = (Block.objects
                 .filter(org=org, app_name__iexact=QB_APP, client__isnull=False,
                         is_billable=True, classification_state="committed",
                         day__gte=start, day__lte=end)
                 .only("id", "user_id", "start", "end", "client_id", "day"))
    for a in anchor_qs:
        if a.start and a.end:
            anchors_by_ud[(a.user_id, a.start.date())].append(a)

    results = {"OVERLAP": [], "NEAR": [], "AMBIGUOUS": [], "NONE": []}
    for b in targets:
        anchors = anchors_by_ud.get((b.user_id, b.start.date()), [])
        overlap = {a.client_id for a in anchors if a.start < b.end and a.end > b.start}
        if len(overlap) == 1:
            results["OVERLAP"].append((b, next(iter(overlap)), "overlap"))
            continue
        if len(overlap) > 1:
            results["AMBIGUOUS"].append((b, None, f"{len(overlap)} clients overlap"))
            continue
        near = set()
        for a in anchors:
            if a.end <= b.start:
                g = (b.start - a.end).total_seconds() / 60
            elif a.start >= b.end:
                g = (a.start - b.end).total_seconds() / 60
            else:
                g = 0
            if g <= gap:
                near.add(a.client_id)
        if len(near) == 1:
            results["NEAR"].append((b, next(iter(near)), f"within {gap}m"))
        elif len(near) > 1:
            results["AMBIGUOUS"].append((b, None, f"{len(near)} clients near"))
        else:
            results["NONE"].append((b, None, "no QB anchor"))
    return results


def _mins(rows):
    return sum((b.minutes or 0) for b, _, _ in rows)


def run_qb_chrome_attribution(org, start: dt.date, end: dt.date,
                              gap: int = 10, apply: bool = False) -> dict:
    """Classify and (optionally) write. Returns a stats dict.

    apply=False -> read-only (dry run).
    apply=True  -> commit OVERLAP (billable), propose NEAR; abstain otherwise.
    """
    results = classify_targets(org, start, end, gap)
    stats = {
        "org_id": org.id,
        "targets": sum(len(v) for v in results.values()),
        "overlap": len(results["OVERLAP"]),
        "near": len(results["NEAR"]),
        "ambiguous": len(results["AMBIGUOUS"]),
        "none": len(results["NONE"]),
        "overlap_min": _mins(results["OVERLAP"]),
        "near_min": _mins(results["NEAR"]),
        "committed": 0,
        "proposed": 0,
        "skipped_protected": 0,
    }
    if not apply:
        stats["dry_run"] = True
        return stats

    with transaction.atomic():
        for b, cid, why in results["OVERLAP"]:
            if b.is_protected():
                stats["skipped_protected"] += 1
                continue
            b.client_id = cid
            b.proposed_client_id = cid
            b.is_billable = True
            b.is_categorized = True
            b.categorized_by = "ai"
            b.classification_state = "committed"
            b.state_changed_by = "rule"
            b.proposed_reasoning = f"{MARK} [{why}]"
            b.save(update_fields=[
                "client", "proposed_client", "is_billable", "is_categorized",
                "categorized_by", "classification_state", "state_changed_by",
                "proposed_reasoning",
            ])
            stats["committed"] += 1
        for b, cid, why in results["NEAR"]:
            if b.is_protected():
                stats["skipped_protected"] += 1
                continue
            b.proposed_client_id = cid
            b.classification_state = "proposed"
            b.state_changed_by = "rule"
            b.proposed_reasoning = f"{MARK} [{why}]"
            b.save(update_fields=[
                "proposed_client", "classification_state",
                "state_changed_by", "proposed_reasoning",
            ])
            stats["proposed"] += 1
    return stats
