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
import json
import hashlib
import logging
import urllib.request
from datetime import timedelta
from collections import defaultdict
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from tracker.models import Block, Client

logger = logging.getLogger(__name__)

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

# Browser apps (normalized: lowercased, ".exe" stripped). Only browser blocks are
# eligible for web auto-file — a no-signal Word/Excel/QuickBooks block is NOT
# "browsing" and must never be swept by this path.
BROWSER_APPS = {'msedge','msedgewebview2','edge','chrome','google chrome','chromium',
  'firefox','mozilla firefox','safari','brave','opera','vivaldi','arc','iexplore',
  'internet explorer','duckduckgo'}

# Professional web tools / client portals. Their window titles frequently carry NO
# work keyword (Edge shows e.g. "Home - Personal - Microsoft Edge" for QuickBooks
# Online), so WORKHINT misses them and they land in the "unrecognized" bucket. If
# any of these appear in the title OR url we treat the block as client work and
# route it to needs-client — it is NEVER auto-filed non-billable. Matched against
# title+url, so both "Onvio - Work" and "qbo.intuit.com" are caught.
# Specific tool/portal identifiers only — deliberately NOT generic work WORDS like
# "payroll"/"employer" (those live in WORKHINT and route to "client work"). Keeping
# this list to concrete product/portal tokens avoids mislabeling and overlap.
WORK_TOOL_HINT = ('onvio','cocounsel','thomsonreuters','thomson reuters','quickbooks',
  'qbo.intuit','intuit','adp.com','runpayroll','paychex','viva - paychex','gusto',
  'pinnacle employee','employee check stub','check stubs','paystub','pay stub',
  'ultratax','proconnect','proseries','lacerte','drake','bill.com','xero','sage ',
  'netsuite','workday','cbna.com','business connect',
  'quickbooks online','onedrive','sharepoint','sage intacct','freshbooks')

# Consumer news outlets (title or url). Matched with word-ish boundaries where a
# bare token would be risky. NOTE: "reuters" alone is excluded on purpose — it
# collides with Thomson Reuters (a work tool); we only match "reuters.com/world"
# style news paths, and Thomson products are caught by WORK_TOOL_HINT first.
NEWS_HINT = ('fox news','foxnews.com','cnn.com','msnbc','nbc news','nbcnews',
  'abcnews','cbsnews','nytimes','new york times','washingtonpost','washington post',
  'breitbart','daily mail','dailymail','huffpost','huffington','bbc news','bbc.com/news',
  'the guardian','usatoday','usa today','newsmax','thehill.com','politico','buzzfeed',
  'yahoo news','msn.com/en-us/news','people.com','tmz','newsweek','vox.com',
  'axios','npr.org','the daily beast','realclearpolitics')

# Additional leisure / personal domains observed in the wild (supplements
# PERSONAL_LOW). Consumer shopping, games, food, music, sports scores.
PERSONAL_EXTRA = ('iheart','crazygames','monkeyhappy','prankdial','prankcaller',
  'wegmans','dunkin','doordash','grubhub','wayfair','etsy','pinterest','tiktok',
  'crossword','wordle','sudoku','ticketmaster','stubhub','zillow','realtor.com',
  'tripadvisor','expedia','airbnb','pandora','soundcloud')

NONBILL_CAT = 'Personal/Non-Billable'


def _norm_app(app_name):
    a = (app_name or '').strip().lower()
    if a.endswith('.exe'):
        a = a[:-4]
    return a.strip()


def _is_browser(app_name):
    return _norm_app(app_name) in BROWSER_APPS


def web_autofile_enabled(org_id):
    """Master gate for the web auto-file behavior. Disabled => second_pass keeps
    today's exact behavior. Requires an OpenAI key (the LLM fallback is core to
    the design) and the SECOND_PASS_WEB_AUTOFILE flag; an optional org-id allowlist
    scopes rollout."""
    if not getattr(settings, 'OPENAI_API_KEY', ''):
        return False
    if not getattr(settings, 'SECOND_PASS_WEB_AUTOFILE', False):
        return False
    allow = getattr(settings, 'SECOND_PASS_WEB_AUTOFILE_ORG_IDS', None) or []
    if allow:
        return org_id in allow
    return True


def llm_web_verdict(block):
    """Ask gpt-4o-mini whether an unrecognized *browser* block is personal/news
    (non-billable) or plausibly client work.

    Returns one of 'personal' | 'work' | 'unsure'. Deliberately asymmetric and
    conservative: only a confident 'personal' verdict may move a block to
    non-billable. Missing key, network/parse error, or any doubt => 'unsure',
    which leaves the block in Needs You (today's behavior). Verdicts are cached
    (title+url signature) so nightly reruns never re-call the model."""
    title = (block.window_title or '').strip()
    url = (block.url or '').strip()
    if not title and not url:
        return 'unsure'

    api_key = getattr(settings, 'OPENAI_API_KEY', '') or ''
    if not api_key:
        return 'unsure'

    sig = hashlib.md5(f'{title}|{url}'.encode('utf-8')).hexdigest()
    ckey = f'sp_web_verdict:v1:{sig}'
    cached = cache.get(ckey)
    if cached:
        return cached

    model = getattr(settings, 'AI_CLASSIFY_MODEL', 'gpt-4o-mini')
    system = (
        "You label ONE browser activity from an accounting/tax/bookkeeping firm's "
        "time tracker as either professional client work or personal browsing. "
        "Respond with strict JSON: {\"label\":\"work\"|\"personal\",\"confidence\":0..1}. "
        "personal = news, opinion, politics, sports scores, entertainment, celebrity, "
        "music/radio, streaming, video games, online shopping, food ordering, travel, "
        "real estate browsing, weather, and general web searches unrelated to "
        "accounting. work = accounting, tax, payroll, bookkeeping, audit, financial "
        "software, client/employer/bank portals, government tax sites, or anything "
        "plausibly billable to a client. When uncertain, answer \"work\"."
    )
    user = f"Title: {title}\nURL: {url}"
    payload = json.dumps({
        'model': model,
        'temperature': 0.0,
        'max_tokens': 40,
        'response_format': {'type': 'json_object'},
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
        ],
    }).encode('utf-8')

    verdict = 'unsure'
    try:
        req = urllib.request.Request(
            'https://api.openai.com/v1/chat/completions',
            data=payload,
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        )
        timeout = float(getattr(settings, 'OPENAI_TIMEOUT_SEC', 8) or 8)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode('utf-8'))
        content = body['choices'][0]['message']['content']
        data = json.loads(content)
        label = str(data.get('label', '')).strip().lower()
        try:
            conf = float(data.get('confidence') or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        if label == 'personal' and conf >= 0.75:
            verdict = 'personal'
        elif label == 'work':
            verdict = 'work'
        else:
            verdict = 'unsure'
    except Exception as e:  # network/parse/quota — degrade to "keep nagging"
        logger.warning('second_pass llm_web_verdict failed: %s', e)
        return 'unsure'  # do NOT cache transient failures

    cache.set(ckey, verdict, getattr(settings, 'AI_CLASSIFY_CACHE_TTL', 86400 * 7))
    return verdict


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


def classify_block(block, client_forms, title_index, web_autofile=False):
    """Return (action, client_id, confidence, reasoning).
    action in: 'commit_nb', 'propose_high', 'propose_needs', 'llm_web_check', 'skip'.

    'llm_web_check' is returned only when web_autofile is on and the block is an
    otherwise-unrecognized browser block; run_second_pass resolves it via the LLM.
    classify_block itself stays pure/cheap (no network) so dry-run stays free."""
    raw = (block.window_title or '')
    t = _norm(raw)
    tl = raw.lower()
    tset = set(t.split())
    # title + url haystack (url is often the only signal that a bland title is a
    # work portal vs personal site). Empty when the browser plugin didn't capture.
    hay = tl + ' ' + (getattr(block, 'url', '') or '').lower()

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

    # ---- Web auto-file guardrails (only when enabled) ----------------------
    # Protect known professional web tools / client portals FIRST. Their titles
    # often lack any work keyword, so without this they'd be swept as "personal".
    # They need a human to pick the client, but must never be auto-non-billable.
    if web_autofile and _is_browser(block.app_name) and any(wt in hay for wt in WORK_TOOL_HINT):
        return ('propose_needs', None, 0.30, 'second-pass: work tool, needs client')

    # Affirmatively personal -> commit non-billable
    if any(p in tl for p in PERSONAL_LOW) and not any(w in tl for w in WORKHINT):
        return ('commit_nb', None, 0.0, 'second-pass: personal browsing')

    # Expanded consumer news / leisure detection (title+url). Gated so flag-off
    # behavior is unchanged. WORKHINT guard keeps anything work-like out.
    if web_autofile and any(p in hay for p in (NEWS_HINT + PERSONAL_EXTRA)) and not any(w in tl for w in WORKHINT):
        return ('commit_nb', None, 0.0, 'second-pass: personal/news browsing')

    # Work-like but no client match -> flag needs-client
    if any(w in tl for w in WORKHINT):
        return ('propose_needs', None, 0.30, 'second-pass: looks like client work, no match')

    if not t.strip():
        return ('skip', None, 0.0, 'blank title')

    # Residual: a browser block with no signal at all (e.g. a bare news headline
    # with no captured URL). Hand to the LLM in run_second_pass. Non-browser
    # residuals (Word/Excel/QuickBooks with an odd title) keep nagging as before.
    if web_autofile and _is_browser(block.app_name):
        return ('llm_web_check', None, 0.20, 'second-pass: web unrecognized (AI pending)')

    return ('propose_needs', None, 0.20, 'second-pass: unrecognized')


def run_second_pass(org_id, days=14, dry_run=True):
    """Categorize uncategorized blocks. Returns a summary dict.
    dry_run=True computes without writing."""
    since = (timezone.now() - timedelta(days=days)).date()
    client_forms = _build_client_forms(org_id)
    title_index = _build_title_index(org_id, since)
    web_autofile = web_autofile_enabled(org_id)
    # Bound LLM calls per run so the unbounded nightly all-orgs loop can't fan out
    # into a large OpenAI bill; verdicts are cached so steady-state calls are only
    # genuinely-new browser blocks anyway.
    llm_budget = int(getattr(settings, 'SECOND_PASS_LLM_MAX_CALLS', 300) or 300)

    pile = Block.objects.filter(
        org_id=org_id, deleted_at__isnull=True, start__date__gte=since,
        classification_state__in=['captured', 'proposed'], client_id__isnull=True
    ).exclude(minutes__lt=2)

    summary = {'commit_nb': 0, 'propose_high': 0, 'propose_needs': 0, 'skip': 0,
               'billed': 0, 'llm_web_check': 0, 'llm_personal': 0, 'llm_budget_skipped': 0}

    for b in pile:
        # Never override a human decision
        if b.categorized_by in ('manual', 'correction'):
            continue

        action, cid, conf, reason = classify_block(b, client_forms, title_index,
                                                    web_autofile=web_autofile)

        # Resolve the LLM handoff for residual unrecognized browser blocks. The
        # verdict may ONLY move a block to non-billable ('personal'); 'work' and
        # 'unsure' fall through to the normal nag. dry_run never calls the model.
        if action == 'llm_web_check':
            summary['llm_web_check'] += 1
            if dry_run:
                continue
            if llm_budget > 0:
                llm_budget -= 1
                verdict = llm_web_verdict(b)
                if verdict == 'personal':
                    summary['llm_personal'] += 1
                    action, cid, conf, reason = ('commit_nb', None, 0.0,
                                                 'second-pass: personal/news (AI)')
                else:
                    action, cid, conf, reason = ('propose_needs', None, 0.20,
                                                 'second-pass: unrecognized')
            else:
                summary['llm_budget_skipped'] += 1
                action, cid, conf, reason = ('propose_needs', None, 0.20,
                                             'second-pass: unrecognized')
            summary[action] = summary.get(action, 0) + 1
        else:
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