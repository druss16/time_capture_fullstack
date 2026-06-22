"""
READ-ONLY. Terri's overnight blocks may have been manually re-categorized as
non-billable, which would have overwritten the 'suppressed' state and pulled
them back into her total/non-billable hours. Check current state.
"""
from collections import Counter
from datetime import date
from django.contrib.auth import get_user_model
from tracker.models import Block

VERIFIED_IDS = [43481,43485,43482,43483,43484,43486,43487,43489,43488,43490,
                43491,43493,43492,43494,43497,43496,43499,43498,43531]

print("="*74)
print("1. The 19 idle blocks — current state (did manual cat overwrite suppress?):")
print("="*74)
for b in Block.objects.filter(id__in=VERIFIED_IDS).order_by("start"):
    st = b.start.astimezone() if b.start else None
    print(f"  id={b.id} | {st.strftime('%H:%M') if st else '??'} | min={b.minutes} | "
          f"state={b.classification_state} | is_cat={b.is_categorized} | "
          f"billable={b.is_billable} | client={b.client_id} | "
          f"cat={(b.category_hours if b.category_hours else '(none)')}")
states = Block.objects.filter(id__in=VERIFIED_IDS).values_list("classification_state", flat=True)
print("-"*74)
print("  state counts:", dict(Counter(states)))
print("  ^ if these are now 'committed'/is_categorized=True, manual cat un-suppressed them")
print("="*74)

# 2. Terri's full day breakdown — where is the 9h19m non-billable coming from?
User = get_user_model()
terri = User.objects.filter(first_name__icontains="terri", last_name__icontains="wall").first()
DAY = date(2026,6,22)
print(f"2. Terri's non-billable blocks on {DAY} (what's making up 9h19m?):")
print("-"*74)
nb = Block.objects.filter(user_id=terri.id, org_id=21, deleted_at__isnull=True,
                          start__date=DAY).exclude(classification_state="suppressed")
nb = [b for b in nb if not b.is_billable and (b.minutes or 0) > 0]
nb.sort(key=lambda b: -(b.minutes or 0))
tot = 0
for b in nb[:25]:
    st = b.start.astimezone() if b.start else None
    tot_app = (b.app_name or "?")
    tot += b.minutes or 0
    print(f"  id={b.id} | {st.strftime('%H:%M') if st else '??'} | min={b.minutes} | "
          f"app={tot_app[:14]} | state={b.classification_state} | "
          f"title={(b.window_title or '(empty)')[:30]}")
nb_total = sum((b.minutes or 0) for b in nb)
print("-"*74)
print(f"  non-billable blocks: {len(nb)}  total: {nb_total}m ({nb_total//60}h{nb_total%60}m)")
print("="*74)
