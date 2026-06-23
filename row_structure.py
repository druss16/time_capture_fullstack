"""READ-ONLY. Settle whether one review row = one block or many.
Look at how today-time groups blocks: do multiple blocks share a title
within one client+category? That determines the grouped-move fix."""
from tracker.models import Block
from collections import defaultdict

# Look at a client+category with multiple same-title blocks (like Mets was)
# Pick any client with email blocks to see the grouping
blocks = Block.objects.filter(org_id=21, deleted_at__isnull=True,
    client_id__isnull=False, classification_state__in=['proposed','committed']
    ).exclude(category_hours={}).order_by('-start')[:200]

# Group by (client, category, title) to see if rows aggregate
groups = defaultdict(list)
for b in blocks:
    cat = list(b.category_hours.keys())[0] if b.category_hours else '?'
    title = (b.window_title or '').strip()[:50]
    groups[(b.client_id, cat, title)].append(b.id)

print("="*70)
print("Title-groups with MULTIPLE blocks (would a single row = many blocks?):")
print("="*70)
multi = {k:v for k,v in groups.items() if len(v) > 1}
if not multi:
    print("  NONE — every (client,cat,title) maps to exactly ONE block.")
    print("  → Each review row IS one block. 'click to move' moving one block")
    print("    is correct; the (9m) you saw was likely ONE 9m block.")
else:
    for (cid,cat,title), ids in list(multi.items())[:10]:
        print(f"  client={cid} cat={cat[:20]} title={title[:35]!r}")
        print(f"    → {len(ids)} blocks: {ids}")
    print()
    print("  → Rows CAN represent multiple blocks. Grouped-move must move all IDs.")
print("="*70)
