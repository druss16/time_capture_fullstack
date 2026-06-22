"""
READ-ONLY. After the committed_only fix, does a block fall into BOTH the
committed branch (state in committed/proposed OR is_categorized) AND the
uncategorized branch (is_categorized=False, not suppressed)?

Overlap = proposed (or committed) blocks that are also is_categorized=False.
Those would be double-counted: once as billable/total, once as uncategorized
(which reports_summary then ADDS into total). We want this to be ~0.
"""
from datetime import date
from collections import Counter
from tracker.models import Block

ORG_ID = 21
DAY = date(2026, 6, 22)

q = Block.objects.filter(org_id=ORG_ID, deleted_at__isnull=True, start__date=DAY)

print("="*72)
print("classification_state x is_categorized cross-tab (org 21, Jun 22):")
print("="*72)
xt = Counter()
for cs, ic in q.values_list("classification_state", "is_categorized"):
    xt[(cs, ic)] += 1
print(f"{'state':16s} {'is_categorized':16s} {'count':>6s}")
print("-"*72)
for (cs, ic), c in sorted(xt.items()):
    print(f"{str(cs):16s} {str(ic):16s} {c:>6d}")
print("="*72)

# The committed branch matches:
committed_branch = q.filter(
    __import__('django').db.models.Q(classification_state__in=["committed","proposed"]) |
    __import__('django').db.models.Q(is_categorized=True)
)
# The uncategorized branch matches:
uncat_branch = q.filter(is_categorized=False).exclude(classification_state="suppressed")

cb_ids = set(committed_branch.values_list("id", flat=True))
ub_ids = set(uncat_branch.values_list("id", flat=True))
overlap = cb_ids & ub_ids

print(f"committed-branch blocks:   {len(cb_ids)}")
print(f"uncategorized-branch blocks:{len(ub_ids)}")
print(f"OVERLAP (in BOTH):         {len(overlap)}   <-- want this ~0")
print("="*72)
if overlap:
    print("Sample overlapping blocks (double-counted) [id|state|is_cat|billable|min|title]:")
    for b in q.filter(id__in=list(overlap))[:15]:
        print(f"  {b.id} | {b.classification_state} | {b.is_categorized} | "
              f"{b.is_billable} | {b.minutes}m | {(b.window_title or '')[:40]}")
    # how many minutes / billable minutes are double-counted?
    ov = q.filter(id__in=list(overlap))
    tot = sum((b.minutes or 0) for b in ov)
    bil = sum((b.minutes or 0) for b in ov if b.is_billable and b.client_id)
    print("-"*72)
    print(f"Double-counted total minutes:    {tot} ({tot//60}h{tot%60}m)")
    print(f"Double-counted billable minutes: {bil} ({bil//60}h{bil%60}m)")
else:
    print("No overlap — the two branches are disjoint. Dashboard math is safe.")
print("="*72)
