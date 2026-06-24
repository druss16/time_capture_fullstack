"""READ-ONLY. Were the duplicate Print Checks blocks created by ONE action
(seconds apart = bug) or separate actions (far apart = not a dup)?
Check created/modified timestamps and what events each holds."""
from tracker.models import Block, RawEvent

for bid in [44763, 44767]:
    b = Block.objects.filter(id=bid).first()
    if not b: 
        print(f"{bid} not found"); continue
    print(f"block {bid}:")
    print(f"  category_hours: {b.category_hours}")
    print(f"  categorized_by: {b.categorized_by}")
    print(f"  categorized_at: {b.categorized_at}")
    print(f"  state_changed_at: {getattr(b,'state_changed_at',None)}")
    print(f"  created/start: {getattr(b,'start',None)}")
    print(f"  app_name: {getattr(b,'app_name',None)}")
    print(f"  title: {getattr(b,'title',None)}")
    print(f"  window_title: {(b.window_title or '')[:50]}")
    evs = RawEvent.objects.filter(block=b)
    print(f"  RawEvents: {evs.count()}")
    for e in evs[:5]:
        print(f"     ev{e.id} start_ts={e.start_ts} title='{(e.window_title or '')[:35]}'")
    print()

print("="*60)
print("If 44767 has app_name='manual_entry' → it was a MANUAL Add Time,")
print("  not a category switch. The 'duplicate' is a manual entry + an")
print("  auto-captured block of the same activity.")
print("If both have real RawEvents and were modified seconds apart → the")
print("  category switch genuinely split/duplicated.")
