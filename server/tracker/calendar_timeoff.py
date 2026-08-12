"""Derive TimeOff (PTO / holidays) from synced calendar events — Phase B of the
work-calendar capacity model.

An event marks time away when Microsoft reports it as out-of-office
(`show_as == 'oof'`), or when it's an all-day event whose title reads like leave
(PTO / vacation / holiday / OOO). We upsert one TimeOff per source event
(`source='calendar'`, keyed on the event's external_id) so re-syncs are
idempotent, and prune calendar-derived rows whose source event no longer
qualifies (e.g. a cancelled vacation).

Manual TimeOff (source='manual') is never touched here.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Q

PTO_KEYWORDS = (
    "pto", "vacation", "holiday", "out of office", "ooo", "leave",
    "time off", "vacay", "annual leave", "day off",
)


def _looks_like_time_off(title: str, show_as: str, is_all_day: bool) -> bool:
    if (show_as or "").lower() == "oof":
        return True
    if is_all_day:
        t = (title or "").lower()
        return any(kw in t for kw in PTO_KEYWORDS)
    return False


def _kind_for(title: str) -> str:
    t = (title or "").lower()
    if "holiday" in t:
        return "holiday"
    if "sick" in t:
        return "sick"
    return "pto"


def derive_time_off_for_user(org, user) -> int:
    """Upsert calendar-derived TimeOff for one user. Returns rows kept."""
    from tracker.models import CalendarEvent, TimeOff

    events = (CalendarEvent.objects
              .filter(org=org, user=user)
              .filter(Q(show_as__iexact="oof") | Q(is_all_day=True))
              .only("external_id", "title", "show_as", "is_all_day", "start", "end"))

    seen: set[str] = set()
    for e in events:
        if not _looks_like_time_off(e.title, e.show_as, e.is_all_day):
            continue
        if not e.external_id:
            continue
        start_d = e.start.date()
        end_d = e.end.date()
        # Graph all-day events end at the *next* midnight (exclusive) — pull the
        # end back a day so a single-day OOO isn't counted as two.
        if e.is_all_day and end_d > start_d:
            end_d = end_d - timedelta(days=1)
        if end_d < start_d:
            end_d = start_d

        TimeOff.objects.update_or_create(
            org=org, user=user, source="calendar", external_id=e.external_id,
            defaults={
                "start_date": start_d,
                "end_date": end_d,
                "kind": _kind_for(e.title),
                "note": (e.title or "")[:255],
            },
        )
        seen.add(e.external_id)

    # Prune calendar-derived rows whose source event no longer qualifies/exists.
    (TimeOff.objects
     .filter(org=org, user=user, source="calendar")
     .exclude(external_id__in=seen)
     .delete())
    return len(seen)
