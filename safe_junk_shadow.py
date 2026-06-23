"""READ-ONLY. Find ONLY the unambiguous personal/idle junk in the pile — safe
to auto-non-billable. Conservative: must match a clear personal/idle pattern
AND have NO client hint. Leaves all real-work-looking blocks alone."""
from datetime import date, timedelta
from tracker.models import Block

since = date(2026,6,23)-timedelta(days=14)
qs = Block.objects.filter(org_id=21, deleted_at__isnull=True, start__date__gte=since,
    classification_state__in=['captured','proposed'], client_id__isnull=True)

# Unambiguous personal/idle/system — never billable, no client possible
SAFE_JUNK = (
    'idle/uncategorized', 'calculator', 'crossword', 'breitbart', 'cnn.com',
    'foxnews', 'espn', 'youtube', 'netflix', 'facebook', 'twitter', 'reddit',
    'instagram', 'amazon.com', 'ebay', 'weather', 'spotify',
    'new tab', 'untitled', 'sign in', 'log in', 'login',
)
# If ANY of these appear, it might be real work — EXCLUDE from auto-junk
CLIENT_HINTS = ('church', 'parish', 'reconciliation', 'tax', 'corp', 'inc', 'llc',
    '1040', '1120', '990', 'payroll', 'reimbursement', 'summary', 'client',
    'invoice', 'return', 'financ', 'budget', 'quickbooks', '.xlsx', 'franciscan')

safe=[]; total_min=0
for b in qs:
    if (b.minutes or 0) < 2: continue
    t=(b.window_title or '').lower()
    if any(h in t for h in SAFE_JUNK) and not any(c in t for c in CLIENT_HINTS):
        safe.append((b.id,(b.window_title or '')[:45])); total_min += (b.minutes or 0)

print("="*64)
print(f"SAFE personal/idle junk (auto-non-billable candidates): {len(safe)} blocks, {total_min}min")
print("="*64)
for bid,t in safe[:40]:
    print(f"  {bid} | {t}")
print("="*64)
print("These name no client + match a clear personal/idle pattern + have no")
print("client hint. Safe to auto-non-billable. Everything else stays for review.")
print("="*64)
