"""
READ-ONLY: how good are the classifier's per-block suggestions?

Decides what the redesigned card should surface:
  - If CATEGORY suggestions are accurate -> show the specific suggested category
  - If weak -> show only a safe lean (work/personal/unclear) or nothing
  - CLIENT suggestions: measure how often proposed + how calibrated (expected weak)

Method: look at blocks that are NOW categorized (we know the "settled" answer),
and compare against whatever the classifier originally SUGGESTED. We try a few
likely field names for where the original suggestion was stored, since the
schema has drifted across versions — script reports which it found.

Run:
  docker compose exec -T api python manage.py shell < suggestion_quality.py

Writes NOTHING.
"""
from collections import Counter
from datetime import timedelta
from django.utils import timezone
from tracker.models import Block

ORG_ID = 21
LOOKBACK_DAYS = 45

now = timezone.now()
since = now - timedelta(days=LOOKBACK_DAYS)

# ---- discover what suggestion-related fields actually exist on Block ----
field_names = {f.name for f in Block._meta.get_fields()}
candidate_cat_fields = [f for f in (
    "suggested_category", "ai_suggested_category", "proposed_category",
    "ai_category", "classifier_category", "suggestion_category",
) if f in field_names]
candidate_client_fields = [f for f in (
    "suggested_client_id", "ai_proposed_client_id", "proposed_client_id",
    "ai_client_id", "classifier_client_id",
) if f in field_names]
candidate_conf_fields = [f for f in (
    "ai_confidence", "suggestion_confidence", "confidence", "classifier_confidence",
) if f in field_names]

print("="*70)
print("SUGGESTION-RELATED FIELDS DETECTED ON Block:")
print(f"  category-suggestion fields: {candidate_cat_fields or 'NONE FOUND'}")
print(f"  client-suggestion fields:   {candidate_client_fields or 'NONE FOUND'}")
print(f"  confidence fields:          {candidate_conf_fields or 'NONE FOUND'}")
print(f"  categorized_by present:     {'categorized_by' in field_names}")
print("="*70)

# Also dump all field names containing hints, so we can see what's really there
hint = sorted([f for f in field_names if any(k in f.lower() for k in
        ("suggest","propose","ai_","classif","confidence","categor","client"))])
print("ALL fields mentioning suggest/propose/ai/classif/confidence/category/client:")
for f in hint:
    print(f"   - {f}")
print("="*70)

cat_field = candidate_cat_fields[0] if candidate_cat_fields else None
conf_field = candidate_conf_fields[0] if candidate_conf_fields else None

# ---- categorized blocks in window ----
catd = (Block.objects
        .filter(org_id=ORG_ID, is_categorized=True, deleted_at__isnull=True)
        .filter(start__gte=since))

total_catd = catd.count()
print(f"Categorized blocks in last {LOOKBACK_DAYS}d for org {ORG_ID}: {total_catd}")

# distribution of how they got categorized (tells us human vs ai share)
if "categorized_by" in field_names:
    by = Counter(catd.values_list("categorized_by", flat=True))
    print("-"*70)
    print("HOW categorized (categorized_by):")
    for k, v in by.most_common():
        print(f"   {str(k):20s} {v:5d}  ({100*v/total_catd:.0f}%)")

# ---- category suggestion accuracy, if we can find the field ----
if cat_field:
    print("-"*70)
    print(f"CATEGORY SUGGESTION ACCURACY  (comparing final `category` vs `{cat_field}`)")
    have_sugg = catd.exclude(**{f"{cat_field}__isnull": True}).exclude(**{cat_field: ""})
    n = have_sugg.count()
    if n == 0:
        print("   no rows have a stored category suggestion to compare.")
    else:
        match = 0
        confusion = Counter()
        for b in have_sugg.values("category", cat_field)[:5000]:
            final = (b["category"] or "").strip().lower()
            sugg = (b[cat_field] or "").strip().lower()
            if final == sugg:
                match += 1
            else:
                confusion[(sugg or "(blank)", final or "(blank)")] += 1
        checked = min(n, 5000)
        print(f"   rows with a suggestion: {n}  (checked {checked})")
        print(f"   exact-match accuracy:   {100*match/checked:.0f}%  ({match}/{checked})")
        print("   top mismatches [suggested -> actual : count]:")
        for (sugg, final), c in confusion.most_common(12):
            print(f"      {sugg[:28]:28s} -> {final[:28]:28s}  {c}")
else:
    print("-"*70)
    print("No stored category-suggestion field found on Block.")
    print("Suggestions may live in a separate table (e.g. Suggestion model)")
    print("or be computed on the fly in the categorization endpoint.")
    print("If so, accuracy can't be measured from Block alone — tell me where")
    print("suggestions are stored and I'll re-aim the query.")

# ---- client suggestion behavior ----
client_field = candidate_client_fields[0] if candidate_client_fields else None
if client_field:
    print("-"*70)
    print(f"CLIENT SUGGESTION BEHAVIOR (`{client_field}`)")
    proposed = catd.exclude(**{f"{client_field}__isnull": True})
    np = proposed.count()
    print(f"   blocks where a client was proposed: {np}  ({100*np/total_catd:.0f}% of categorized)")
    if client_field and "client_id" in field_names and np:
        pass
    # simple agreement: proposed == final client
    if np:
        agree = 0
        for b in proposed.values(client_field, "client_id")[:5000]:
            if b[client_field] and b[client_field] == b["client_id"]:
                agree += 1
        print(f"   proposed client == final client: {agree}/{min(np,5000)}  ({100*agree/min(np,5000):.0f}%)")
else:
    print("-"*70)
    print("No stored client-suggestion field found on Block.")

print("="*70)
print("DONE — paste this whole output back.")
print("="*70)
