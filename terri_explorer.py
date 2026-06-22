"""
READ-ONLY. Inspect Terri Wall's 'Explorer' uncategorized blocks on Jun 22 to
confirm they're overnight-idle artifacts (and design a safe filter that won't
catch legitimate Explorer file-browsing for a client).
"""
from datetime import date
from django.contrib.auth import get_user_model
from tracker.models import Block

ORG_ID, DAY = 21, date(2026, 6, 22)
User = get_user_model()
terri = User.objects.filter(first_name__icontains="terri", last_name__icontains="wall").first() \
        or User.objects.filter(username__icontains="terri").first()
if not terri:
    print("Terri not found"); raise SystemExit
print(f"Terri = id {terri.id} ({terri.get_full_name()})")

q = Block.objects.filter(org_id=ORG_ID, user_id=terri.id, deleted_at__isnull=True,
                         start__date=DAY).order_by("start")

print("="*78)
print("ALL Terri blocks where app looks like Explorer:")
print("="*78)
exp = [b for b in q if "explor" in (b.app_name or "").lower()]
tot = 0
for b in exp:
    span = ((b.end-b.start).total_seconds()/60) if (b.start and b.end) else None
    tot += b.minutes or 0
    st = b.start.astimezone() if b.start else None
    print(f"  id={b.id} | {st.strftime('%H:%M') if st else '??'} | "
          f"min={b.minutes} span={round(span) if span else '?'} | "
          f"client={b.client_id} | cat_state={b.classification_state} | "
          f"billable={b.is_billable} | title={(b.window_title or '(empty)')[:40]}")
print("-"*78)
print(f"Explorer blocks: {len(exp)}  total minutes: {tot} ({tot//60}h{tot%60}m)")
print("="*78)

# Time-of-day spread — is it overnight / continuous?
if exp:
    times = sorted([b.start.astimezone() for b in exp if b.start])
    print(f"earliest: {times[0].strftime('%H:%M')}  latest: {times[-1].strftime('%H:%M')}")
    # are they back-to-back (idle) or scattered (real use)?
    gaps = []
    for i in range(1, len(times)):
        gaps.append((times[i]-times[i-1]).total_seconds()/60)
    if gaps:
        print(f"median gap between Explorer blocks: {sorted(gaps)[len(gaps)//2]:.0f} min")
print("="*78)
print("Filter design check: how many have client=None AND empty/generic title?")
idle_like = [b for b in exp if not b.client_id and (not b.window_title or
             (b.window_title or '').strip().lower() in ('','explorer','file explorer','program manager'))]
print(f"  client=None + empty/generic title: {len(idle_like)} blocks, "
      f"{sum((b.minutes or 0) for b in idle_like)}m")
print("  ^ these are safe to treat as idle. Real file-browsing has a client or real title.")
print("="*78)
