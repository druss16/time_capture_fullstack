"""
READ-ONLY. Her total is 12h51m but she worked ~5-6h. The inflation is long
blocks where the agent kept counting while she was away (idle detection not
firing). Show ALL her non-suppressed blocks sorted by DURATION so we can see
which long blocks are implausible. Decide together — don't auto-delete.
"""
from datetime import date
from django.contrib.auth import get_user_model
from tracker.models import Block

User = get_user_model()
terri = User.objects.filter(first_name__icontains="terri", last_name__icontains="wall").first()
DAY = date(2026,6,22)

q = Block.objects.filter(user_id=terri.id, org_id=21, deleted_at__isnull=True,
                         start__date=DAY).exclude(classification_state="suppressed")
blocks = [b for b in q if (b.minutes or 0) > 0]
blocks.sort(key=lambda b: -(b.minutes or 0))

total = sum((b.minutes or 0) for b in blocks)
print("="*84)
print(f"Terri non-suppressed blocks by DURATION. Total: {total}m ({total//60}h{total%60}m)")
print(f"(She says real work ~5-6h. Excess = idle-inflated long blocks.)")
print("="*84)
cum = 0
for b in blocks:
    st = b.start.astimezone() if b.start else None
    en = b.end.astimezone() if b.end else None
    span = round((b.end-b.start).total_seconds()/60) if (b.start and b.end) else None
    cum += b.minutes or 0
    bill = "BILL" if b.is_billable else "non "
    print(f"  {b.minutes:>4}m | span={span if span else '?':>4} | {bill} | "
          f"{(st.strftime('%H:%M') if st else '??')}-{(en.strftime('%H:%M') if en else '??')} | "
          f"{(b.app_name or '?')[:11]:11} | id={b.id} | {(b.window_title or '(empty)')[:30]}")
print("-"*84)
print(f"Top 10 longest blocks = {sum((b.minutes or 0) for b in blocks[:10])}m of the {total}m total")
print("="*84)
print("Blocks where minutes==span (no gaps) AND >30m are prime idle-inflation")
print("suspects: one window held for 30-60min straight is rarely real active work.")
print("="*84)
