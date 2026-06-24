"""READ-ONLY. Syracuse Fire shows a COMMITTED card row '990 - Message' AND a
PENDING row 'syr fire supplemental - Message'. Are these the same block (double
render) or two different blocks? Trace them."""
from datetime import date
from tracker.models import Block, User

DAY = date(2026,6,23)
# Find Syracuse Fire blocks (client) — search across users since unsure who
print("="*72)
print("Blocks mentioning 'syr fire' / '990' / Syracuse Fire today:")
print("="*72)
for kw in ['syr fire', '990 - Message', 'Syracuse Fire']:
    bs = Block.objects.filter(day=DAY, window_title__icontains=kw, deleted_at__isnull=True).select_related('client','proposed_client','user')
    for b in bs[:6]:
        print(f"  {b.id} | {b.user.username} | state={b.classification_state} min={b.minutes}")
        print(f"     client={b.client.name if b.client_id else None} "
              f"proposed={b.proposed_client.name if b.proposed_client_id else None}")
        print(f"     cat={list((b.category_hours or {}).keys())} billable={b.is_billable} by={b.categorized_by}")
        print(f"     title='{(b.window_title or '')[:50]}'")
        print()

print("="*72)
print("If the COMMITTED '990' block and the PROPOSED 'syr fire' block are")
print("DIFFERENT block ids → they're two real blocks (not a double-render of one).")
print("If SAME block appears as both committed-in-card AND proposed-in-pending →")
print("that's the double-render: today_time puts its events in the card AND the")
print("proposed_inline query lists it as pending.")
