"""
second_pass.py — automated categorizer for blocks the first pass left
uncategorized. Safe by design:
  - COMMIT only in the non-billable direction (junk/personal/idle).
  - Client guesses are written as PROPOSALS (proposed_client + flagged,
    is_billable=False). They NEVER auto-commit and NEVER bill — a human
    confirms in Daily Review (and Approvals gates billing downstream).
  - Never overwrites a human decision (categorized_by in manual/correction).

Place at: server/tracker/services/second_pass.py
"""
import re
from datetime import timedelta
from collections import defaultdict
from django.utils import timezone
from tracker.models import Block, Client

GENERIC = {'saint','church','catholic','parish','cemetery','school','inc','llc','corp',
  'co','company','services','foundation','center','ministries','the','and','of'}

GENERIC_TITLE = ('select reconciliation','begin reconciliation','reconciliation report',
  'preview paycheck','print checks','print preview','past transactions','preparer options',
  'quickbooks accountant desktop','(primary) quickbooks','(secondary) quickbooks',
  'special paycheck','missing client info','account spreadsheet','enter memorized',
  'save print output',
  # QuickBooks modal/chrome dialogs — identical across every client & user, so
  # same-title matching on them cross-contaminates clients (a committed
  # "QuickBooks Desktop Information" for one client was stamping New School onto
  # everyone else's identically-titled block). These carry no client identity.
  'quickbooks desktop information','select checks to print','delete transaction',
  'print checks - confirmation','write checks','create invoice','receive payment',
  'make deposit','pay bills','transfer funds','memorized transaction','chart of accounts',
  'quickbooks information','recording transaction','create item receipts')

JUNK = ('idle/uncategorized','calculator','crossword','breitbart','milb.com',
  'overall standings','gwen stefani','google search','windows shell experience',
  'timetracker','support.taxwise.com','/mfa.aspx','sfs support','solution center',
  '\\\\192.168','new missed call')

PERSONAL_LOW = ('las vegas','espn','youtube','netflix','facebook','twitter','reddit',
  'instagram','weather','spotify','amazon.com','ebay','bing travel','flights from',
  'train ticket','bus and train','birthday parties','big don','sky city','maverik',
  'custom portal','monkey go happy')

# If ANY of these appear, the block may be real billable work — never auto-commit.
WORKHINT = ('.pdf','.xlsx','statement','reconcil','return','1040','1120','990','fica',
  'payroll','invoice','church','parish','cemetery','reimbursement','tax','client',
  'deposit','bank','escrow')

NONBILL_CAT = 'Personal/Non-Billable'


def _norm(s):
    s = (s or '').lower()
    s = re.sub(r'\bst\.?\s', 'saint ', s)
    s = s.replace("'", "").replace("&", " and ")
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def _build_client_forms(org_id):
    forms = []
    for c in Client.objects.filter(org_id=org_id, is_active=True):
        n = _norm(c.name)
        if len(n) < 8:
            continue
        distinct = [t for t in n.split() if t not in GENERIC and len(t) >= 4]
        if not distinct:
            continue
        fset = {n}
        w = n.split()
        while w and w[-1] in GENERIC:
            w = w[:-1]
        if len(' '.join(w)) >= 8 and any(t in distinct for t in w):
            fset.add(' '.join(w))
        forms.append((c.id, c.name, fset, set(distinct)))
    return forms


def _build_title_index(org_id, since):
    """Map (user_id, window_title) -> {client_ids that user committed it to}.

    Keyed by USER, not just title: another user's committed title carries no
    attribution weight for this user, and org-wide keying let a shared title
    (esp. generic QB dialogs) cross-contaminate clients across users.
    """
    committed = Block.objects.filter(
        org_id=org_id, deleted_at__isnull=True, start__date__gte=since,
        classification_state='committed', client_id__isnull=False
    ).values('user_id', 'window_title', 'client_id')
    idx = defaultdict(set)
    for c in committed:
        t = (c['window_title'] or '').strip().lower()
        if t:
            idx[(c['user_id'], t)].add(c['client_id'])
    return idx


def classify_block(block, client_forms, title_index):
    """Return (action, client_id, confidence, reasoning).
    action in: 'commit_nb', 'propose_high', 'propose_needs', 'skip'."""
    raw = (block.window_title or '')
    t = _norm(raw)
    tl = raw.lower()
    tset = set(t.split())

    # Auto-commit junk (non-billable, safe direction)
    if any(j in tl for j in JUNK) and not any(w in tl for w in WORKHINT):
        return ('commit_nb', None, 0.0, 'second-pass: system/idle junk')

    # High-confidence client proposal: name in title
    for cid, cname, fset, distinct in client_forms:
        if any(len(f) >= 8 and f in t for f in fset) and (distinct & tset):
            return ('propose_high', cid, 0.85, f'second-pass: name in title ({cname})')

    # High-confidence: same title as a block THIS USER previously committed
    # (non-generic only). Same-user scoped — another user's committed title is
    # not evidence for this block, and org-wide matching cross-contaminated
    # clients on shared/generic titles.
    if not any(g in tl for g in GENERIC_TITLE):
        cids = title_index.get((block.user_id, raw.strip().lower()))
        if cids and len(cids) == 1:
            return ('propose_high', list(cids)[0], 0.80, 'second-pass: matches your committed same-title')

    # Affirmatively personal -> commit non-billable
    if any(p in tl for p in PERSONAL_LOW) and not any(w in tl for w in WORKHINT):
        return ('commit_nb', None, 0.0, 'second-pass: personal browsing')

    # Work-like but no client match -> flag needs-client
    if any(w in tl for w in WORKHINT):
        return ('propose_needs', None, 0.30, 'second-pass: looks like client work, no match')

    if not t.strip():
        return ('skip', None, 0.0, 'blank title')

    return ('propose_needs', None, 0.20, 'second-pass: unrecognized')


def run_second_pass(org_id, days=14, dry_run=True):
    """Categorize uncategorized blocks. Returns a summary dict.
    dry_run=True computes without writing."""
    since = (timezone.now() - timedelta(days=days)).date()
    client_forms = _build_client_forms(org_id)
    title_index = _build_title_index(org_id, since)

    pile = Block.objects.filter(
        org_id=org_id, deleted_at__isnull=True, start__date__gte=since,
        classification_state__in=['captured', 'proposed'], client_id__isnull=True
    ).exclude(minutes__lt=2)

    summary = {'commit_nb': 0, 'propose_high': 0, 'propose_needs': 0, 'skip': 0, 'billed': 0}

    for b in pile:
        # Never override a human decision
        if b.categorized_by in ('manual', 'correction'):
            continue

        action, cid, conf, reason = classify_block(b, client_forms, title_index)
        summary[action] = summary.get(action, 0) + 1

        if dry_run:
            continue

        if action == 'commit_nb':
            mins = b.minutes or 0
            b.category_hours = {NONBILL_CAT: round(mins / 60.0, 4)}
            b.client = None
            b.is_billable = False
            b.categorized_by = 'correction'
            b.categorized_at = timezone.now()
            b.is_categorized = True
            b.classification_state = 'committed'
            b.save(force_update=True)

        elif action in ('propose_high', 'propose_needs'):
            b.proposed_client_id = cid
            b.proposed_confidence = conf
            b.proposed_reasoning = reason
            b.is_billable = False              # NEVER bill a guess
            b.classification_state = 'proposed'
            b.save(force_update=True)
            # safety assertion
            if b.is_billable:
                summary['billed'] += 1

    return summary