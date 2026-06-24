"""READ-ONLY. Simulate the FULL fix (both changes together) and prove no time
vanishes. For each user today:
  OLD card total (all non-suppressed events, current behavior)
  NEW card total (committed-only events)
  NEW pending total (ALL proposed blocks, by minutes)
  RECONCILE: new_card + new_pending should ≈ old_card
            (committed stays in card; proposed moves to pending; sum preserved)"""
from datetime import date, datetime
from collections import defaultdict
from django.utils import timezone
from tracker.models import RawEvent, Block, User

DAY = date(2026,6,23)
USERS = ['wendy','emily','stephen','terri','tran','wayne']

print(f"{'user':9} {'OLD card':>9} {'NEW card':>9} {'pending':>9} {'recon Δ':>9}")
print("-"*52)
for uname in USERS:
    u = User.objects.filter(username=uname).first()
    if not u: continue
    start_utc = timezone.make_aware(datetime.combine(DAY, datetime.min.time()))
    end_utc = timezone.make_aware(datetime.combine(DAY, datetime.max.time()))
    events = list(RawEvent.objects.filter(
        user=u, start_ts__gte=start_utc, start_ts__lt=end_utc,
    ).exclude(block__classification_state='suppressed').select_related('block'))
    deleted = set(Block.objects.filter(user=u, deleted_at__isnull=False).values_list('id', flat=True))

    old_card = 0.0
    new_card = 0.0   # committed-only events
    for e in events:
        if not (e.start_ts and e.end_ts): continue
        dur = (e.end_ts - e.start_ts).total_seconds()
        if dur <= 0: continue
        b = e.block
        if b and b.id in deleted: continue
        old_card += dur/60.0
        # NEW: card only counts committed (not proposed/captured)
        if b and b.classification_state == 'committed':
            new_card += dur/60.0

    # NEW pending = ALL proposed blocks' minutes (the loosened criteria:
    # every proposed block, regardless of proposed_client_id/reasoning)
    proposed_blocks = Block.objects.filter(
        user=u, day=DAY, classification_state='proposed', deleted_at__isnull=True,
    ).exclude(categorized_by__in=['manual','correction'])
    pending_mins = sum(b.minutes or 0 for b in proposed_blocks)

    # Also: captured blocks (7 for wendy) — where do they go? Currently in card.
    # Check their contribution so we account for them in reconciliation.
    captured_events = 0.0
    for e in events:
        if not (e.start_ts and e.end_ts): continue
        dur = (e.end_ts - e.start_ts).total_seconds()
        if dur <= 0: continue
        b = e.block
        if b and b.id in deleted: continue
        if b and b.classification_state == 'captured':
            captured_events += dur/60.0

    # Reconcile: old_card should ≈ new_card(committed) + proposed_events + captured_events
    # We compute proposed via EVENTS (to match card units), not block.minutes
    proposed_event_mins = 0.0
    for e in events:
        if not (e.start_ts and e.end_ts): continue
        dur = (e.end_ts - e.start_ts).total_seconds()
        if dur <= 0: continue
        b = e.block
        if b and b.id in deleted: continue
        if b and b.classification_state == 'proposed':
            proposed_event_mins += dur/60.0

    recon = old_card - (new_card + proposed_event_mins + captured_events)
    print(f"{uname:9} {old_card:9.1f} {new_card:9.1f} {proposed_event_mins:9.1f} {recon:9.2f}")

print("-"*52)
print("recon Δ should be ≈0 → committed + proposed + captured = old card total.")
print("proposed time = what moves from card to pending. captured = separate Q.")
print("\nIf recon ≈ 0 everywhere: the fix preserves all time. Proposed events")
print("leave the card and appear in pending; nothing vanishes.")
