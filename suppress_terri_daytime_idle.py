"""
SCOPED MUTATION — suppress Terri's 4 daytime Idle-sentinel blocks.

Pinned to the exact 4 verified IDs (app=Idle, title 'Idle/Uncategorized',
billable=False, client=None). Re-checks each before suppressing; aborts if any
became real work. Removes them from total + non-billable across all views.

APPLY=True (armed). Run once:
  docker compose exec -T api python manage.py shell < suppress_terri_daytime_idle.py
"""
from collections import Counter
from tracker.models import Block

VERIFIED_IDS = [43525, 43628, 44094, 44240]
APPLY = True   # set False to re-dry-run

found = list(Block.objects.filter(id__in=VERIFIED_IDS))
print("="*72)
print(f"Daytime Idle-sentinel blocks to suppress ({len(VERIFIED_IDS)} IDs):")
print("="*72)

# Safety re-check: must be idle-sentinel, non-billable, no client.
unsafe = []
for b in found:
    title = (b.window_title or "").strip().lower()
    app = (b.app_name or "").lower()
    is_idle = (app == "idle") or ("idle/uncategorized" in title) or (title == "idle")
    if b.client_id or b.is_billable or not is_idle:
        unsafe.append((b.id, b.client_id, b.is_billable, b.app_name, (b.window_title or "")[:24]))

for b in found:
    st = b.start.astimezone() if b.start else None
    print(f"  id={b.id} | {st.strftime('%H:%M') if st else '??'} | min={b.minutes} | "
          f"app={b.app_name} | state={b.classification_state} | "
          f"billable={b.is_billable} | client={b.client_id} | "
          f"title={(b.window_title or '(empty)')[:24]}")
print("-"*72)

if unsafe:
    print("ABORT: a target is billable / client-attributed / not idle. Investigate:")
    for u in unsafe:
        print(f"   {u}")
    raise SystemExit

already = [b.id for b in found if b.classification_state == "suppressed"]
to_do = [b.id for b in found if b.classification_state != "suppressed"]
if already:
    print(f"(Already suppressed, skipping: {already})")
print(f"Will suppress {len(to_do)}: {to_do}")
print("="*72)

if not APPLY:
    print(">>> DRY RUN. Nothing changed.")
    raise SystemExit

n = Block.objects.filter(id__in=to_do).update(classification_state="suppressed")
print(f">>> APPLIED: suppressed {n} blocks.")
after = Block.objects.filter(id__in=VERIFIED_IDS).values_list("classification_state", flat=True)
print(">>> Post-state:", dict(Counter(after)))
print(">>> Done. ~1h44m of daytime idle removed from total + non-billable.")
print("="*72)
