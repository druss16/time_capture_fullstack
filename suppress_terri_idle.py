"""
SCOPED MUTATION — suppress Terri's 19 VERIFIED overnight idle blocks.

This version is PINNED to the exact 19 block IDs you reviewed in the dry-run.
It will not select by signature and cannot touch any other block. It also
re-checks each ID is still non-billable / no-client before suppressing, and
hard-aborts if any ID has changed into real work.

APPLY=True (armed). Run once:
  docker compose exec -T api python manage.py shell < suppress_terri_idle.py
"""
from collections import Counter
from tracker.models import Block

# ── The exact 19 IDs verified in the dry-run (all overnight, empty title,
#    billable=False, no client). Pinned so nothing else can be affected. ──
VERIFIED_IDS = [
    43481, 43485, 43482, 43483, 43484, 43486, 43487, 43489, 43488, 43490,
    43491, 43493, 43492, 43494, 43497, 43496, 43499, 43498, 43531,
]

APPLY = True   # set False to re-dry-run

qs = Block.objects.filter(id__in=VERIFIED_IDS)

print("="*78)
print(f"Suppressing Terri's verified overnight-idle blocks ({len(VERIFIED_IDS)} IDs):")
print("="*78)

found = list(qs)
found_ids = {b.id for b in found}
missing = set(VERIFIED_IDS) - found_ids
if missing:
    print(f"NOTE: {len(missing)} ID(s) not found (already gone?): {sorted(missing)}")

# Safety re-check: refuse if any target became billable / got a client / is
# no longer empty-title since the dry-run.
unsafe = []
for b in found:
    title = (b.window_title or "").strip().lower()
    if b.client_id or b.is_billable or title not in ("", "program manager"):
        unsafe.append((b.id, b.client_id, b.is_billable, (b.window_title or "")[:30]))

for b in found:
    st = b.start.astimezone() if b.start else None
    print(f"  id={b.id} | {st.strftime('%H:%M') if st else '??'} | min={b.minutes} | "
          f"billable={b.is_billable} | client={b.client_id} | state={b.classification_state} | "
          f"title={(b.window_title or '(empty)')[:24]}")
print("-"*78)

if unsafe:
    print("ABORT: one or more target IDs are now billable / client-attributed /")
    print("       non-empty-title. Refusing to suppress. Investigate:")
    for u in unsafe:
        print(f"   id={u[0]} client={u[1]} billable={u[2]} title={u[3]!r}")
    raise SystemExit

already = [b.id for b in found if b.classification_state == "suppressed"]
if already:
    print(f"(Already suppressed, will skip: {already})")

to_do = [b.id for b in found if b.classification_state != "suppressed"]
print(f"Will suppress {len(to_do)} block(s): {to_do}")
print("="*78)

if not APPLY:
    print(">>> DRY RUN. Nothing changed. Set APPLY=True to apply.")
    raise SystemExit

# Suppress ONLY the verified, still-safe IDs.
n = Block.objects.filter(id__in=to_do).update(classification_state="suppressed")
print(f">>> APPLIED: set classification_state='suppressed' on {n} blocks.")

after = Block.objects.filter(id__in=VERIFIED_IDS).values_list("classification_state", flat=True)
print(">>> Post-state across all 19 IDs:", dict(Counter(after)))
print(">>> Done. These now disappear from Categorize, Daily Review, and Reports.")
print("="*78)
