"""
READ-ONLY. Two questions:
  1. Did Terri's 19 idle blocks actually get suppressed?
  2. Do the day-view endpoints (today_time / get_categorization_data) EXCLUDE
     suppressed blocks, or will suppressed idle still show in her timecard?
"""
from collections import Counter
from tracker.models import Block

VERIFIED_IDS = [43481,43485,43482,43483,43484,43486,43487,43489,43488,43490,
                43491,43493,43492,43494,43497,43496,43499,43498,43531]

print("="*72)
print("1. Current state of the 19 target blocks:")
states = Block.objects.filter(id__in=VERIFIED_IDS).values_list("classification_state", flat=True)
print("   ", dict(Counter(states)))
print("   (want: {'suppressed': 19}. If still 'committed', the apply didn't run.)")
print("="*72)

# 2. How does the codebase query day-view? Grep the views for suppressed handling.
import subprocess, os
def grep(pattern, path):
    try:
        out = subprocess.run(["grep","-rn",pattern,path], capture_output=True, text=True, timeout=20)
        return out.stdout.strip()
    except Exception as e:
        return f"(grep failed: {e})"

base = None
for cand in ("/app/tracker", "tracker"):
    if os.path.isdir(cand):
        base = cand; break
print(f"2. Does day-view exclude suppressed?  (searching {base})")
print("-"*72)
print("today_time / get_categorization_data references to 'suppressed':")
print(grep("suppressed", base) or "   (no matches — suppressed NOT filtered anywhere!)")
print("="*72)
