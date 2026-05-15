"""
catalogue_vocabularies.py — Plan B Step 0

Finds and prints every CPA-category vocabulary in the codebase so we can
design ONE canonical list. Run inside the container:

    docker compose exec api python manage.py shell -c "exec(open('/app/catalogue_vocabularies.py').read())"
"""

print("=" * 70)
print("VOCABULARY CATALOGUE — every category list a CPA org touches")
print("=" * 70)

# ---- 1. The defined lists in industry_categories.py ----
try:
    from tracker import industry_categories as ic

    print("\n[1] CPA_CATEGORIES (main list, used by build_ai_prompt_for_industry)")
    for c in getattr(ic, 'CPA_CATEGORIES', []):
        print(f"      {c}")

    print("\n[2] CPA_TASK_TYPES (seed task types)")
    for tt in getattr(ic, 'CPA_TASK_TYPES', []):
        print(f"      {tt.get('code'):8s} {tt.get('name')}  billable={tt.get('is_billable')}")

    print("\n[3] _get_allowed_categories('cpa') (what Stage 10 actually uses)")
    try:
        for c in ic._get_allowed_categories('cpa'):
            print(f"      {c}")
    except Exception as e:
        print(f"      ERROR calling _get_allowed_categories: {e}")

    print("\n[4] INTERNAL_CATEGORIES (used when client == Internal)")
    for c in getattr(ic, 'INTERNAL_CATEGORIES', []):
        print(f"      {c}")

    print("\n[5] CPA_TOOL_DETECTION — distinct category values")
    tool_cats = set()
    for tool, cfg in getattr(ic, 'CPA_TOOL_DETECTION', {}).items():
        tool_cats.add(cfg.get('category'))
    for c in sorted(tool_cats):
        print(f"      {c}")

    print("\n[6] get_combined_tool_detection('cpa') — distinct category values")
    combined_cats = set()
    for tool, cfg in ic.get_combined_tool_detection('cpa').items():
        combined_cats.add(cfg.get('category'))
    for c in sorted(combined_cats):
        print(f"      {c}")

    print("\n[7] validate_and_fix_ai_response KNOWN_FIXES — target category names")
    # KNOWN_FIXES is local to the function; re-declare by inspecting source isn't
    # reliable, so just note it must be reconciled too.
    print("      (KNOWN_FIXES dict is inside validate_and_fix_ai_response —")
    print("       must be reconciled by hand against the canonical list)")

except Exception as e:
    print(f"ERROR importing industry_categories: {e}")

# ---- 8. What's ACTUALLY in the database — every org ----
print("\n" + "=" * 70)
print("[8] ACTUAL DATA — distinct ai_category strings per org")
print("=" * 70)
from tracker.models import Block, Organization, TaskType
from django.db.models import Count

for org in Organization.objects.all().order_by('id'):
    blocks = Block.objects.filter(org=org)
    if not blocks.exists():
        continue
    print(f"\n  ORG {org.id}: {org.name}  (industry={org.industry_type})")
    cats = (blocks.values('ai_category')
                  .annotate(n=Count('id'))
                  .order_by('-n'))
    for c in cats:
        label = c['ai_category'] if c['ai_category'] else '(empty)'
        print(f"      {str(c['n']).rjust(6)}  {label}")

# ---- 9. TaskTypes actually in the database, per org ----
print("\n" + "=" * 70)
print("[9] ACTUAL DATA — TaskTypes per org")
print("=" * 70)
for org in Organization.objects.all().order_by('id'):
    tts = TaskType.objects.filter(org=org)
    if not tts.exists():
        continue
    print(f"\n  ORG {org.id}: {org.name}")
    for tt in tts.order_by('sort_order', 'name'):
        print(f"      {tt.code:10s} {tt.name}  active={tt.is_active}")

print("\n" + "=" * 70)
print("END CATALOGUE")
print("=" * 70)
