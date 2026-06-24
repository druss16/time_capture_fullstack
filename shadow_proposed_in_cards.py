"""READ-ONLY. Going forward: do PROPOSED blocks still leak their events into
CARDS (while also showing in pending) = double render? Check terri: are any
proposed blocks' events being counted in card category totals?"""
from datetime import date, datetime
from collections import defaultdict
from django.utils import timezone
from tracker.models import RawEvent, Block, User

DAY = date(2026,6,23)
terri = User.objects.filter(username='terri').first()
start_utc = timezone.make_aware(datetime.combine(DAY, datetime.min.time()))
end_utc = timezone.make_aware(datetime.combine(DAY, datetime.max.time()))

events = list(RawEvent.objects.filter(
    user=terri, start_ts__gte=start_utc, start_ts__lt=end_utc,
).exclude(block__classification_state='suppressed').select_related('block'))

# How much PROPOSED-block time is currently rolling into cards?
proposed_in_card = 0.0
proposed_blocks_in_card = set()
committed_in_card = 0.0
for e in events:
    if not (e.start_ts and e.end_ts): continue
    dur = (e.end_ts - e.start_ts).total_seconds()/60.0
    if dur <= 0: continue
    b = e.block
    if not b: continue
    if b.classification_state == 'proposed':
        proposed_in_card += dur
        proposed_blocks_in_card.add(b.id)
    elif b.classification_state == 'committed':
        committed_in_card += dur

print("="*72)
print(f"terri today — event rollup into CARDS:")
print("="*72)
print(f"  committed-block time in cards:  {committed_in_card:.1f}m  (correct — should be in cards)")
print(f"  PROPOSED-block time in cards:   {proposed_in_card:.1f}m  ({len(proposed_blocks_in_card)} blocks)")
print()
if proposed_in_card > 0:
    print(f"  ✗ DOUBLE RENDER STILL HAPPENS: {proposed_in_card:.1f}m of proposed-block")
    print(f"    time shows in CARDS while those blocks ALSO show in pending.")
    print(f"    → The red-clock rule (exclude proposed events from cards) is still needed.")
    print(f"    Sample proposed blocks leaking into cards: {sorted(proposed_blocks_in_card)[:8]}")
else:
    print(f"  ✓ NO double render: proposed blocks do NOT leak into cards.")
    print(f"    Nothing more to fix — committed→card, proposed→pending already separate.")
print("="*72)
