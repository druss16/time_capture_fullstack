"""
READ-ONLY. The UI shows 'Explorer (6.4h)' but DB has no such block — the 19
suppressed Explorer blocks sum to ~6.4h. So the daily-review/categorize
endpoint is NOT excluding suppressed. Find which view feeds the timecard and
whether it filters classification_state='suppressed'.
"""
import subprocess, os
base = "/app/tracker" if os.path.isdir("/app/tracker") else "tracker"

def grep(pat, *extra):
    try:
        return subprocess.run(["grep","-rn",pat,base], capture_output=True, text=True, timeout=20).stdout.strip()
    except Exception as e:
        return f"(err {e})"

print("="*78)
print("Endpoints that build the daily timecard (today_time / categorization):")
print("="*78)
for fn in ("def today_time", "def get_categorization_data", "def daily", "def get_day"):
    hits = grep(fn)
    if hits:
        print(f"\n### {fn}\n{hits}")
print("="*78)
print("Do those views exclude suppressed? (grep 'suppressed' in views.py):")
print(grep("suppressed") or "  NONE — suppressed not filtered in views.py!")
print("="*78)

# Confirm the math: sum of Terri's suppressed Explorer = 6.4h?
from datetime import date
from django.contrib.auth import get_user_model
from tracker.models import Block
User = get_user_model()
terri = User.objects.filter(first_name__icontains="terri", last_name__icontains="wall").first()
sup = Block.objects.filter(user_id=terri.id, org_id=21, deleted_at__isnull=True,
                           start__date=date(2026,6,22), classification_state="suppressed")
explorer_sup = [b for b in sup if "explor" in (b.app_name or "").lower()]
tot = sum((b.minutes or 0) for b in explorer_sup)
print(f"Terri's SUPPRESSED Explorer blocks: {len(explorer_sup)} = {tot}m ({tot/60:.1f}h)")
print(f"  ^ if this is ~6.4h, the UI is counting suppressed blocks. Fix = exclude them in the view.")
print("="*78)
