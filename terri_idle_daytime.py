"""
READ-ONLY. Terri's non-billable is still 9h19m. The 19 overnight Explorer
blocks are suppressed. So what's inflating non-billable now? Isolate the
app='Idle' / 'Idle/Uncategorized' sentinel blocks — those are agent idle
markers and should NOT count as non-billable work.
"""
from collections import Counter
from datetime import date
from django.contrib.auth import get_user_model
from tracker.models import Block

User = get_user_model()
terri = User.objects.filter(first_name__icontains="terri", last_name__icontains="wall").first()
DAY = date(2026,6,22)

q = Block.objects.filter(user_id=terri.id, org_id=21, deleted_at__isnull=True,
                         start__date=DAY).exclude(classification_state="suppressed")

# Bucket all non-suppressed blocks by what they are
idle_sentinel = []   # app=Idle or title Idle/Uncategorized
real = []
for b in q:
    app = (b.app_name or "").lower()
    title = (b.window_title or "").strip().lower()
    if app == "idle" or "idle/uncategorized" in title or title == "idle":
        idle_sentinel.append(b)
    else:
        real.append(b)

print("="*74)
print("IDLE SENTINEL blocks (app=Idle / title Idle/Uncategorized) — should NOT count:")
print("="*74)
idle_sentinel.sort(key=lambda b: b.start or 0)
tot_idle = 0
for b in idle_sentinel:
    st = b.start.astimezone() if b.start else None
    tot_idle += b.minutes or 0
    print(f"  id={b.id} | {st.strftime('%H:%M') if st else '??'} | min={b.minutes} | "
          f"state={b.classification_state} | billable={b.is_billable} | client={b.client_id} | "
          f"title={(b.window_title or '(empty)')[:26]}")
print("-"*74)
print(f"  Idle-sentinel total: {len(idle_sentinel)} blocks = {tot_idle}m ({tot_idle//60}h{tot_idle%60}m)")
print(f"  IDs: {[b.id for b in idle_sentinel]}")
print("="*74)
print(f"Safety: any idle-sentinel that is billable or has a client? (should be NONE)")
bad = [(b.id, b.is_billable, b.client_id) for b in idle_sentinel if b.is_billable or b.client_id]
print("  ", bad if bad else "none — all safe to suppress")
print("="*74)
nb_real = [b for b in real if not b.is_billable and (b.minutes or 0) > 0]
nb_real_tot = sum((b.minutes or 0) for b in nb_real)
print(f"Remaining REAL non-billable (after removing idle sentinels): "
      f"{nb_real_tot}m ({nb_real_tot//60}h{nb_real_tot%60}m) across {len(nb_real)} blocks")
print("  ^ this is what her non-billable SHOULD be once idle sentinels are gone")
print("="*74)
