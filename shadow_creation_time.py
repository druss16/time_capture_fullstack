"""READ-ONLY. When was block 44767 actually CREATED (row inserted)?
created_at vs categorized_at tells us if it predates the recategorize or
was born from it. Also check if there's a compaction/split job."""
from tracker.models import Block, RawEvent

for bid in [44763, 44767]:
    b = Block.objects.filter(id=bid).first()
    print(f"block {bid}:")
    # try every possible creation/modification field
    for f in ['created_at','created','inserted_at','categorized_at','state_changed_at','updated_at','modified_at']:
        v = getattr(b, f, 'NO_FIELD')
        if v != 'NO_FIELD':
            print(f"    {f}: {v}")
    print(f"    bundle_id: {getattr(b,'bundle_id',None)}")
    print(f"    minutes: {b.minutes}")
    print(f"    events: {list(RawEvent.objects.filter(block_id=bid).values_list('id', flat=True))}")
    print()

# Key question: do 44763 and 44767 share a bundle_id (= came from same
# original block that got split)?
b1 = Block.objects.filter(id=44763).first()
b2 = Block.objects.filter(id=44767).first()
print(f"44763 bundle_id: {getattr(b1,'bundle_id',None)}")
print(f"44767 bundle_id: {getattr(b2,'bundle_id',None)}")
print(f"Same bundle? {getattr(b1,'bundle_id',None) == getattr(b2,'bundle_id',None) and getattr(b1,'bundle_id',None) is not None}")

# What's the model's actual fields?
print("\nBlock model date/time fields:")
for fld in Block._meta.get_fields():
    if 'date' in fld.name.lower() or 'time' in fld.name.lower() or 'created' in fld.name.lower() or fld.name in ('start','end'):
        print(f"  {fld.name}")
