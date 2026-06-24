"""READ-ONLY. Map how block classification_state maps to display surfaces,
so we understand the intended/actual behavior before changing anything.

For wendy today, categorize every block by state and whether it would appear
in: (a) the event-based CARD, (b) the PENDING list (proposed_inline), (c) both."""
from datetime import date
from collections import Counter, defaultdict
from tracker.models import Block, User

DAY = date(2026,6,23)
wendy = User.objects.filter(username='wendy').first()

blocks = Block.objects.filter(user=wendy, day=DAY, deleted_at__isnull=True).select_related('client','proposed_client')

print("="*72)
print(f"wendy {DAY}: {blocks.count()} blocks — state × display surface")
print("="*72)

state_counts = Counter()
# proposed_inline criteria (from views.py ~4611):
#   state='proposed', not categorized_by in (manual,correction),
#   AND ('second-pass' in reasoning OR has proposed_client_id)
def in_pending(b):
    if b.classification_state != 'proposed': return False
    if b.categorized_by in ('manual','correction'): return False
    r = (getattr(b,'proposed_reasoning','') or '')
    return ('second-pass' in r) or bool(b.proposed_client_id)

# card criteria: has events in range (we approximate: any block with minutes
# and not suppressed shows via its events regardless of state)
def in_card(b):
    return b.classification_state != 'suppressed' and (b.minutes or 0) > 0

rows = defaultdict(list)
for b in blocks:
    state_counts[b.classification_state] += 1
    card = in_card(b)
    pend = in_pending(b)
    if card and pend: surface = "BOTH (card + pending)"
    elif card:        surface = "card only"
    elif pend:        surface = "pending only"
    else:             surface = "neither"
    rows[surface].append((b.id, b.classification_state, b.minutes,
                          b.client.name if b.client_id else (b.proposed_client.name if b.proposed_client_id else 'none'),
                          b.categorized_by))

print("\nState counts:", dict(state_counts))
print("\nBy display surface:")
for surface, items in rows.items():
    print(f"\n  [{surface}] — {len(items)} blocks:")
    for bid, st, mn, cl, by in items[:8]:
        print(f"     {bid}: state={st:9} {mn:3}m  client={cl[:25]:25} by={by}")
    if len(items) > 8:
        print(f"     ... +{len(items)-8} more")

print("\n" + "="*72)
print("KEY QUESTION for next session:")
print(" - Blocks in 'BOTH' are the ones appearing in a card AND pending list.")
print(" - Is that intended (preview the guess in-card + offer confirm)?")
print("   Or should 'proposed' show in exactly ONE place?")
print(" - This decides the fix. Don't change until the intended model is clear.")
print("="*72)
