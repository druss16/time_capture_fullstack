"""
READ-ONLY. Reconcile Terri's dashboard non-billable (9h36m) against actual
blocks. Previous query filtered start__date=2026-06-22 (LOCAL) — if overnight
blocks have a UTC date boundary issue, they'd be missed. This widens the net:
pull ALL her non-billable blocks in a UTC window spanning the full local day
+ buffer, and explicitly hunt for empty-title / Explorer / Program Manager
blocks that might still be counted.
"""
from datetime import date, datetime, timedelta, timezone as tz
from django.contrib.auth import get_user_model
from django.utils import timezone
from tracker.models import Block

User = get_user_model()
terri = User.objects.filter(first_name__icontains="terri", last_name__icontains="wall").first()

# Wide UTC window: local Jun 22 00:00 minus 6h, to local Jun 23 00:00 plus 6h
local_tz = timezone.get_current_timezone()
start_local = timezone.make_aware(datetime(2026,6,22,0,0), local_tz)
end_local = timezone.make_aware(datetime(2026,6,23,0,0), local_tz)
start_utc = (start_local - timedelta(hours=6)).astimezone(tz.utc)
end_utc = (end_local + timedelta(hours=6)).astimezone(tz.utc)

q = Block.objects.filter(user_id=terri.id, org_id=21, deleted_at__isnull=True,
                         start__gte=start_utc, start__lt=end_utc).order_by("start")

print("="*82)
print(f"ALL Terri blocks in wide UTC window. Total in query: {q.count()}")
print("="*82)

# Categorize every block by state + billable, find suspect idle still counting
nonbill_counted = 0
suspect_idle = []   # empty title / explorer / program manager / Idle, NOT suppressed
states = {}
for b in q:
    states[b.classification_state] = states.get(b.classification_state, 0) + 1
    if b.classification_state == "suppressed":
        continue
    m = b.minutes or 0
    if m <= 0:
        continue
    title = (b.window_title or "").strip().lower()
    app = (b.app_name or "").lower()
    is_idle_like = (title in ("", "program manager", "explorer", "file explorer", "idle/uncategorized")
                    or app in ("idle", "explorer", "explorer.exe"))
    if not b.is_billable:
        nonbill_counted += m
        if is_idle_like:
            suspect_idle.append(b)

print(f"Non-billable minutes (non-suppressed): {nonbill_counted} = {nonbill_counted//60}h{nonbill_counted%60}m")
print(f"State distribution: {states}")
print("="*82)
print(f"SUSPECT idle-like blocks STILL counted in non-billable: {len(suspect_idle)}")
print("-"*82)
sus_tot = 0
for b in suspect_idle:
    st = b.start.astimezone() if b.start else None
    utc = b.start if b.start else None
    sus_tot += b.minutes or 0
    print(f"  id={b.id} | local={st.strftime('%m-%d %H:%M') if st else '??'} | "
          f"UTC_date={utc.date() if utc else '?'} | min={b.minutes} | "
          f"state={b.classification_state} | app={(b.app_name or '?')[:10]} | "
          f"title={(b.window_title or '(empty)')[:24]}")
print("-"*82)
print(f"SUSPECT idle total: {sus_tot}m ({sus_tot//60}h{sus_tot%60}m)")
print(f"SUSPECT IDs: {[b.id for b in suspect_idle]}")
print("="*82)
print("If suspect total is large and these are empty/Explorer/Idle, THESE are")
print("the ones still in non-billable — suppress this exact ID list.")
print("="*82)
