"""READ-ONLY. Wayne's current uncategorized blocks — what are they, and does
the classifier have ANY guess for each? Shows what a second-pass would have
to work with (proposed_client/confidence already computed, or nothing)."""
from datetime import date, timedelta
from tracker.models import Block, User

# find Wayne
wayne = User.objects.filter(username__icontains='wayne').first()
if not wayne:
    print("no wayne user found by username; listing org 21 uncat instead")
since = date(2026,6,23)-timedelta(days=14)
qs = Block.objects.filter(org_id=21, deleted_at__isnull=True, start__date__gte=since,
    classification_state__in=['captured','proposed'], client_id__isnull=True
    ).filter(minutes__gte=2)
if wayne:
    qs = qs.filter(user=wayne)
qs = qs.order_by('-start')

print("="*72)
print(f"Uncategorized (no client) blocks: {qs.count()}")
print("="*72)
for b in qs[:20]:
    pcid = getattr(b,'proposed_client_id',None)
    pconf = getattr(b,'proposed_confidence',None)
    pcat = getattr(b,'proposed_category',None)
    sigs = getattr(b,'proposed_signals',None) or []
    sigtypes = [s.get('type') for s in sigs if isinstance(s,dict)]
    print(f"  {b.id} | {b.minutes}m | state={b.classification_state}")
    print(f"      title: {(b.window_title or '')[:55]}")
    print(f"      best-guess: client={pcid} conf={pconf} cat={pcat}")
    print(f"      signals available: {sigtypes}")
print("="*72)
print("If 'best-guess client' is populated → second-pass can surface it as a")
print("flagged proposal. If empty + no signals → genuinely nothing to guess from.")
print("="*72)
