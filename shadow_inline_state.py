"""READ-ONLY shadow. For a given user/day, show:
  1. Each proposed (second-pass) block: title, minutes, guessed client
  2. Whether that guessed client ALSO has committed time today (→ has a card)
     or has NO other time (→ would need a synthetic card)
  3. Duplicate-title counts (for grouping)
This tells us the rendering paths we must handle BEFORE writing code."""
from datetime import date
from collections import defaultdict
from tracker.models import Block, User

# EDIT these to the user/day you're viewing
USERNAME = 'wayne'
DAY = date(2026, 6, 23)

u = User.objects.filter(username=USERNAME).first()
if not u:
    print(f"no user {USERNAME}"); raise SystemExit

# Proposed second-pass blocks (what shows in the pending card)
props = Block.objects.filter(
    user=u, day=DAY, classification_state='proposed', deleted_at__isnull=True,
).exclude(categorized_by__in=['manual','correction']).select_related('proposed_client')

# Committed blocks today → which clients already have a card
committed = Block.objects.filter(
    user=u, day=DAY, classification_state='committed', deleted_at__isnull=True,
    client__isnull=False,
).select_related('client')
clients_with_cards = set(committed.values_list('client_id', flat=True))

print("="*72)
print(f"{USERNAME} {DAY}: {props.count()} proposed blocks")
print("="*72)

by_guess = defaultdict(list)
for b in props:
    r = getattr(b,'proposed_reasoning','') or ''
    if 'second-pass' not in r and not b.proposed_client_id:
        continue
    by_guess[b.proposed_client_id].append(b)

for gcid, blocks in by_guess.items():
    if gcid is None:
        print(f"\n[NO GUESS] {len(blocks)} blocks (stay under 'No Client'):")
    else:
        name = blocks[0].proposed_client.name if blocks[0].proposed_client_id else '?'
        has_card = "HAS existing card" if gcid in clients_with_cards else "NO card → would need synthetic"
        print(f"\n[GUESS → {name} (id={gcid})] {len(blocks)} blocks — {has_card}:")
    # group by title to show duplicate accumulation
    by_title = defaultdict(lambda: {'count':0,'mins':0,'ids':[]})
    for b in blocks:
        t = (b.window_title or '').strip()
        by_title[t]['count'] += 1
        by_title[t]['mins'] += (b.minutes or 0)
        by_title[t]['ids'].append(b.id)
    for t, agg in sorted(by_title.items(), key=lambda x:-x[1]['mins']):
        print(f"   {agg['count']:2d}x  {agg['mins']:3d}m  {t[:50]}  ids={agg['ids'][:5]}{'...' if len(agg['ids'])>5 else ''}")

print("\n" + "="*72)
print(f"Clients with existing cards today: {sorted(clients_with_cards)}")
print("="*72)
