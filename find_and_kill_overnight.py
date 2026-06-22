"""
READ-ONLY FIRST. Find EVERY non-suppressed block from Terri's overnight window
(midnight to 7am local) regardless of app/title — the full overnight pile that's
still being counted. Print them. Does NOT delete yet — APPLY=False.
"""
from datetime import datetime, timedelta, timezone as tz
from django.contrib.auth import get_user_model
from django.utils import timezone
from tracker.models import Block

User = get_user_model()
terri = User.objects.filter(first_name__icontains="terri", last_name__icontains="wall").first()

# Local Jun 22 00:00 -> 07:00 converted to UTC
local_tz = timezone.get_current_timezone()
night_start = timezone.make_aware(datetime(2026,6,22,0,0), local_tz).astimezone(tz.utc)
night_end   = timezone.make_aware(datetime(2026,6,22,7,0), local_tz).astimezone(tz.utc)

q = Block.objects.filter(user_id=terri.id, org_id=21, deleted_at__isnull=True,
                         start__gte=night_start, start__lt=night_end).order_by("start")

print("="*84)
print("ALL Terri blocks between 00:00-07:00 LOCAL (the overnight window):")
print("="*84)
nonsup = []
for b in q:
    st = b.start.astimezone() if b.start else None
    sup = b.classification_state == "suppressed"
    bill = "BILL" if b.is_billable else "non "
    mark = "[suppressed]" if sup else "  *COUNTING*"
    if not sup and (b.minutes or 0) > 0:
        nonsup.append(b)
    print(f"  {mark} id={b.id} | {st.strftime('%H:%M') if st else '??'} | min={b.minutes:>4} | "
          f"{bill} | {(b.app_name or '?')[:11]:11} | state={b.classification_state:9} | "
          f"{(b.window_title or '(empty)')[:28]}")
print("-"*84)
tot = sum((b.minutes or 0) for b in nonsup)
print(f"STILL COUNTING from overnight: {len(nonsup)} blocks = {tot}m ({tot//60}h{tot%60}m)")
print(f"  billable among them: {[b.id for b in nonsup if b.is_billable]}")
print(f"  non-billable among them: {[b.id for b in nonsup if not b.is_billable]}")
print("="*84)
print("Review: are the 06:34-06:47 ones (Outlook/QB/UltraTax) REAL early work,")
print("or also idle? Billable QB/UltraTax at 6:47am may be real. You decide which.")
print("="*84)
