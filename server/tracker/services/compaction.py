# tracker/services/compaction.py
from datetime import timedelta
from django.utils import timezone
from .models import RawEvent, Block

IDLE_CAP = timedelta(minutes=30)   # cap long gaps (e.g., lunch)
MIN_BLOCK = timedelta(seconds=30)  # drop tiny blips

def build_blocks_for_day(user, day, hostname=None):
    # Get events in order
    qs = RawEvent.objects.filter(
        user=user,
        ts_utc__date=day
    ).order_by('ts_utc')
    if hostname:
        qs = qs.filter(hostname=hostname)

    rows = list(qs)
    blocks = []
    for i, row in enumerate(rows):
        start = row.ts_utc
        next_ts = rows[i+1].ts_utc if i+1 < len(rows) else timezone.now()
        # true duration = until next event; clamp to idle cap; never negative
        dur = max(timedelta(0), min(next_ts - start, IDLE_CAP))
        if dur < MIN_BLOCK:
            continue
        blocks.append({
            "start": start,
            "end": start + dur,
            "minutes": dur.total_seconds() / 60.0,
            "app_name": row.app_name,
            "bundle_id": row.bundle_id,
            "window_title": row.window_title or "",
            "url": row.url,
            "file_path": row.file_path,
            "hostname": row.hostname,
        })

    # Optional: coalesce adjacent identical signatures
    coalesced = []
    for b in blocks:
        if coalesced and all([
            coalesced[-1]["app_name"] == b["app_name"],
            coalesced[-1]["bundle_id"] == b["bundle_id"],
            coalesced[-1]["window_title"] == b["window_title"],
            (b["start"] - coalesced[-1]["end"]) <= timedelta(seconds=5),
        ]):
            coalesced[-1]["end"] = b["end"]
            coalesced[-1]["minutes"] += b["minutes"]
        else:
            coalesced.append(b)
    return coalesced