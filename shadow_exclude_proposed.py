"""READ-ONLY. Show the impact of excluding PROPOSED-block events from the
event-based card rollup. Proposed blocks belong in the pending list ONLY,
not also as committed card rows. This confirms:
  - committed time is UNCHANGED
  - only proposed-block events are removed from cards (they stay in pending)
Tests across a few users on today."""
from datetime import date, datetime
from collections import defaultdict
from django.utils import timezone
from tracker.models import RawEvent, Block, User

DAY = date(2026,6,23)
USERS = ['wendy','emily','stephen','terri','tran','wayne']

for uname in USERS:
    u = User.objects.filter(username=uname).first()
    if not u: continue
    start_utc = timezone.make_aware(datetime.combine(DAY, datetime.min.time()))
    end_utc = timezone.make_aware(datetime.combine(DAY, datetime.max.time()))
    events = list(RawEvent.objects.filter(
        user=u, start_ts__gte=start_utc, start_ts__lt=end_utc,
    ).exclude(block__classification_state='suppressed').select_related('block','block__client'))
    deleted = set(Block.objects.filter(user=u, deleted_at__isnull=False).values_list('id', flat=True))

    cur = defaultdict(float)    # current: all events
    fixed = defaultdict(float)  # fixed: exclude proposed-block events
    for e in events:
        if not (e.start_ts and e.end_ts): continue
        dur = (e.end_ts - e.start_ts).total_seconds()
        if dur <= 0: continue
        b = e.block
        if b and b.id in deleted: b = None
        cid = b.client_id if b else None
        name = (b.client.name if (b and b.client) else 'Unassigned')
        cur[(cid,name)] += dur/60.0
        # FIX: skip events whose block is still proposed
        if b and b.classification_state == 'proposed':
            continue
        fixed[(cid,name)] += dur/60.0

    # Show only clients where the number CHANGES
    changed = []
    allkeys = set(cur) | set(fixed)
    for k in allkeys:
        if abs(cur[k] - fixed[k]) > 0.05:
            changed.append((k, cur[k], fixed[k]))
    if changed:
        print(f"\n{uname}: clients whose card total CHANGES (proposed events removed):")
        for (cid,name), c, f in sorted(changed, key=lambda x:-(x[1]-x[2])):
            print(f"   {name[:35]:35} {c:6.1f}m → {f:6.1f}m   (−{c-f:.1f}m moves to pending-only)")
    else:
        print(f"\n{uname}: no change (no proposed-block events in cards)")

print("\n" + "="*72)
print("READ: every −Xm is proposed time that will now show ONLY in the pending")
print("list, not double-rendered as a card row. Committed time stays identical.")
print("Wendy/St James should show NO change IF 44733 is committed (it is now).")
print("To see the bug's effect we'd need a still-proposed block.")
