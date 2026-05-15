from tracker.models import Block
from django.db.models import Count

print("=== TL Wall (org 21) ai_category distribution ===")
rows = (Block.objects
        .filter(org_id=21)
        .values('ai_category')
        .annotate(n=Count('id'))
        .order_by('-n'))
for c in rows:
    cat = c['ai_category'] if c['ai_category'] else '(empty)'
    print(str(c['n']).rjust(6), ' ', repr(cat))

print()
print("=== TL Wall (org 21) TaskTypes that exist ===")
from tracker.models import TaskType
for tt in TaskType.objects.filter(org_id=21).order_by('sort_order', 'name'):
    print('  ', tt.code.ljust(12), tt.name)
