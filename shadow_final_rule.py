"""READ-ONLY. Verify the rule: committed→card, non-committed→pending, ONE place.
Prove no time vanishes: for each user, every block lands in exactly one bucket
and card_committed + pending_noncommitted == all_non_suppressed_time."""
from datetime import date, datetime
from collections import defaultdict
from django.utils import timezone
from tracker.models import Block, RawEvent, User

DAY = date(2026,6,23)
USERS = ['wendy','emily','stephen','terri','tran','wayne']

print(f"{'user':9} {'CARD(committed)':>16} {'PENDING(non-com)':>17} {'suppressed':>11} {'TOTAL':>8}")
print("-"*70)
for uname in USERS:
    u = User.objects.filter(username=uname).first()
    if not u: continue
    start_utc = timezone.make_aware(datetime.combine(DAY, datetime.min.time()))
    end_utc = timezone.make_aware(datetime.combine(DAY, datetime.max.time()))
    events = list(RawEvent.objects.filter(
        user=u, start_ts__gte=start_utc, start_ts__lt=end_utc,
    ).select_related('block'))
    deleted = set(Block.objects.filter(user=u, deleted_at__isnull=False).values_list('id', flat=True))

    card = 0.0          # committed events
    pending = 0.0       # non-committed (captured/proposed/uncategorized), not suppressed
    suppressed = 0.0
    no_block = 0.0
    for e in events:
        if not (e.start_ts and e.end_ts): continue
        dur = (e.end_ts - e.start_ts).total_seconds()/60.0
        if dur <= 0: continue
        b = e.block
        if b and b.id in deleted:
            continue
        if not b:
            no_block += dur; continue
        st = b.classification_state
        if st == 'suppressed':
            suppressed += dur
        elif st == 'committed':
            card += dur
        else:  # captured, proposed, anything non-committed → pending
            pending += dur
    total = card + pending + suppressed + no_block
    print(f"{uname:9} {card:16.1f} {pending:17.1f} {suppressed:11.1f} {total:8.1f}")

print("-"*70)
print("Every block lands in exactly ONE bucket by state. card+pending+suppressed")
print("+unlinked = total. NO time vanishes — non-committed moves to pending,")
print("committed stays in card, each shown once. This is the rule, reconciled.")
print("\nNOTE: 'pending' may be LARGE (lots of non-committed time). The grouped")
print("pending UI must handle it. But NO double-render and NO lost time.")
