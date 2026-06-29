"""
tracker/utils/content_classifier.py

Lightweight, deterministic content classifier for RawEvents.

Used by compaction.py to split blocks by content type, so that personal
browsing (news, social media, streaming, restaurants, games) doesn't get
merged with legitimate client work that happens to share the same
app/client/session.

DESIGN PRINCIPLES
=================
- Cheap: no AI, no DB, no I/O. Pure string matching.
- WORK WINS TIES. The work-allowlist is checked FIRST. A page that is clearly
  professional software, a known work host, a client document, or billable
  tax research can never be misclassified as personal — that protected
  precedence is what makes the aggressive personal set safe.
- Conservative on the residual: after work and personal checks, anything left
  is 'unknown' (kept separate, client retained, flagged for review — never
  silently billed or silently dropped).
- Deterministic: same input → same output.

CLASSIFICATION ORDER (v2 — 2026-06-29, tuned to org-21 corpus)
==============================================================
  0. WORK ALLOWLIST (NEW, runs first):
       - content_identity present (qbo:customer=, file=, paychex:company=, ...)
       - known work host (irs.gov, dol.gov, ssa.gov, qbo, onvio, paychex, banks)
       - work app marker in title/app (quickbooks, ultratax, onvio, ' - excel')
       - a *.pdf document title (church/bank statements, scans)
     → 'work'. Nothing below can override this.
  1. PERSONAL by URL host (expanded)
  2. PERSONAL by MSN content-path (msn.com/en-us/<news|sports|...>/)
  3. PERSONAL by title marker (expanded: news, food, games, movies, travel)
  4. PERSONAL by structural headline (no work signal + headline-shaped)
  5. WORK app marker (secondary, e.g. titles that reach here)
  6. 'unknown'
"""

from urllib.parse import urlparse
import re


# =============================================================================
# WORK ALLOWLIST — checked FIRST. Protects billable work from false-personal.
# =============================================================================

# Known work hosts. Substring match on hostname. These are SPAs and reference
# sites your preparers use for real client work — including tax-research sites
# that would otherwise look like generic browsing.
WORK_HOSTS = frozenset([
    # Tax authority / research (billable research, NOT personal)
    'irs.gov', 'dol.gov', 'ssa.gov', 'dot.ny.gov', 'dot.gov', 'nhtsa.dot.gov',
    'vpic.nhtsa.dot.gov', 'ny.gov', 'tax.ny.gov',
    # CPA platforms / SPAs
    'qbo.intuit.com', 'quickbooks.intuit.com', 'accounts.intuit.com',
    'onvio.us', 'thomsonreuters.com', 'cocounsel.thomsonreuters.com',
    'auth.thomsonreuters.com', 'taxwise.com', 'returnquery.taxwise.com',
    'support.taxwise.com', 'cchaxcess.com', 'swswebapi.cchaxcess.com',
    'support.cch.com', 'natptax.com', 'wolterskluwer.com',
    # Payroll / HR
    'paychex.com', 'myapps.paychex.com', 'flex.paychex.com',
    'reporting.flex.paychex.com', 'payroll.flex.paychex.com',
    'prismhr.com', 'pin.prismhr.com', 'adp.com',
    # Banking / financial (client bookkeeping work)
    'onlinebanking.mtb.com', 'login.mtb.com', 'secure.chase.com',
    'chase.com', 'key.com', 'ibx.key.com', 'navyfederal.org',
    'digitalomni.navyfederal.org', 'pathfinderbank.com',
    'pathfinderbank.ebanking-services.com', 'mystreetscape.com',
    'pathfinderbank.biz-business.online-banking',
    # Firm's own site + client portals
    'tlwallaccounting.com', 'medentmobile.com', 'launchny.powerappsportals.com',
    'powerappsportals.com',
])

# Work app markers (title OR app_name substring). From the original classifier,
# kept intact.
WORK_APP_MARKERS = frozenset([
    'ultratax', 'lacerte', 'taxwise', 'drake tax', 'drake software',
    'proseries', 'atx ',
    'cs professional', 'cs connect', 'onvio', 'workpapers cs',
    'fixed assets cs', 'accounting cs', 'practice cs',
    'quickbooks', 'qbo', 'xero', 'sage ', 'freshbooks', 'wave accounting',
    'paychex', 'adp ', 'gusto', 'rippling', 'prismhr', 'pinnacle employee',
    ' - excel', ' - word', ' - powerpoint', ' - outlook',
    'adobe acrobat', 'adobe reader',
    'cch axcess', 'thomson reuters', 'wolters kluwer',
    'internal revenue service', 'department of labor',  # gov reference work
    'remote desktop web client', 'rdweb',               # RDP to client envs
])

# A *.pdf in the title = an open document (church/bank statement, scan, report).
# These are client work, never personal. Matches "...something.pdf..." anywhere.
_PDF_IN_TITLE_RE = re.compile(r'\.pdf\b', re.IGNORECASE)

# Scanner batch files and similar.
_SCAN_RE = re.compile(r'\b(SKMBT_\d+|CCF\d+|DOC\d+)', re.IGNORECASE)


# =============================================================================
# PERSONAL — DOMAINS (expanded from original with corpus findings)
# =============================================================================

PERSONAL_DOMAINS = frozenset([
    # National news
    'foxnews.com', 'cnn.com', 'msnbc.com', 'nytimes.com', 'wsj.com',
    'washingtonpost.com', 'reuters.com', 'apnews.com', 'usatoday.com',
    'nbcnews.com', 'abcnews.go.com', 'cbsnews.com', 'huffpost.com',
    'thehill.com', 'politico.com', 'axios.com', 'vox.com', 'slate.com',
    'theatlantic.com', 'newyorker.com', 'theguardian.com', 'bbc.com',
    'bbc.co.uk', 'aljazeera.com', 'breitbart.com', 'dailywire.com',
    'salon.com', 'motherjones.com', 'newsmax.com', 'oann.com',
    'nypost.com', 'dailymail.co.uk', 'mirror.co.uk', 'people.com',
    'tmz.com', 'pagesix.com',
    # corpus additions
    'dailycaller.com', 'drudgereport.com', 'japantimes.co.jp', 'zeit.de',
    'ft.com', 'thesun.co.uk', 'thetimes.co.uk', 'independent.co.uk',
    'weather.com',

    # Local news (Syracuse area)
    'syracuse.com', '9wsyr.com', 'cnycentral.com', 'localsyr.com',
    'wstm.com', 'wsyr.com',

    # Sports
    'espn.com', 'sports.yahoo.com', 'bleacherreport.com', 'cbssports.com',
    'foxsports.com', 'nfl.com', 'nba.com', 'mlb.com', 'nhl.com',
    'pgatour.com', 'athletic.com', 'theathletic.com', 'milb.com',

    # Social media
    'twitter.com', 'x.com', 'facebook.com', 'instagram.com', 'tiktok.com',
    'snapchat.com', 'pinterest.com', 'tumblr.com', 'mastodon.social',
    'threads.net', 'bsky.app',

    # Entertainment / streaming / music
    'netflix.com', 'hulu.com', 'disneyplus.com', 'hbomax.com', 'max.com',
    'primevideo.com', 'spotify.com', 'open.spotify.com', 'pandora.com',
    'soundcloud.com', 'twitch.tv', 'iheart.com', 'anghami.com', 'play.anghami.com',

    # Games / time-wasters (corpus: heavy monkeyhappy + prank sites)
    'monkeyhappy.com', 'prankdial.com', 'prankcaller.io',

    # Movies / tickets (corpus: heavy)
    'regmovies.com', 'fandango.com', 'marcustheatres.com',

    # Local recreation (corpus: bigdons, topgolf, escape rooms, golf clubs)
    'bigdons.com',

    # Shopping
    'amazon.com', 'ebay.com', 'etsy.com', 'walmart.com', 'target.com',
    'hobbii.com', 'stamps.com',

    # Real estate browsing (personal unless clearly client work)
    'zillow.com', 'realtor.com',

    # Gossip/Lifestyle
    'buzzfeed.com', 'eonline.com', 'usmagazine.com', 'cosmopolitan.com',
])

# MSN is the big one in the corpus: msn.com itself is a portal, but the
# CONTENT PATHS are clearly personal (news/sports/entertainment/etc.). Match
# msn.com only when the path is one of these personal sections — so a future
# msn.com work tool wouldn't be caught, and the weather homepage stays unknown.
_MSN_PERSONAL_PATHS = (
    '/news/', '/sports/', '/entertainment/', '/foodanddrink/', '/lifestyle/',
    '/money/', '/health/', '/travel/', '/autos/', '/tv/', '/crime/',
    '/topstories/', '/other/', '/opinion/', '/world/', '/us/', '/politics/',
    '/technology/', '/realestate/', '/retirement/', '/personalfinance/',
)


# =============================================================================
# PERSONAL — TITLE MARKERS (expanded)
# =============================================================================

PERSONAL_TITLE_MARKERS = frozenset([
    # News brand markers (original)
    'fox news -', 'cnn -', 'cnn.com', 'msnbc -', 'breaking news',
    'syracuse news', '9wsyr',
    'fox news', 'msn |', 'msnbc', 'newsmax', 'breitbart', 'huffpost',
    'yahoo news', 'usa today', 'maggie haberman', 'barron trump',
    # news brands (corpus additions)
    'drudge report', 'daily caller', 'daily wire', 'the japan times',
    'the guardian', 'the sun', 'the times', 'nbc news', 'the independent',
    'die zeit',

    # Food / restaurants (corpus: very heavy applebee's + menu sites)
    "applebee's", 'applebees', 'menu with prices', 'menuwithprices',
    'singleplatform', 'order online | chinese', 'mealkeyway', 'menusifu',

    # Games / fun (corpus: monkeyhappy, prank apps, escape rooms, mini golf)
    'monkey go happy', 'prankdial', 'prank caller', 'escape rooms',
    'mini golf', 'laser tag', 'topgolf', 'top golf', 'country club',
    'yacht & country', 'big don', 'movie tickets', 'showtimes',
    'now showing', 'fandango', 'marcus theatres', 'regal',

    # Music / streaming
    ' | spotify', 'spotify –', 'spotify -', 'song and lyrics', 'lyrics on spotify',
    ' on anghami', 'iheart',

    # Sports markers (original)
    ' nfl ', ' nba ', ' mlb ', ' nhl ', ' pga ', 'sports highlights',
    'milb.com', 'red sox', 'syracuse mets',

    # Travel (corpus: bing travel flights)
    'bing travel', 'flights from',

    # Social media markers (original)
    ' - twitter', ' / x', '(@', ' - facebook', ' - instagram',
])

# News-style trailing/leading brand suffixes (original, kept).
_PERSONAL_TITLE_ENDINGS = (
    '| fox news', '- fox news', '| cnn', '- cnn.com',
    '- the new york times', '- the washington post', '- the guardian',
    '- bbc news', '- reuters', '- ap news', '- syracuse.com',
    '| the japan times', '| msn', '| the sun', '| wsyr', '| nbc news',
    '| die zeit', '- pranks', '| spotify',
)


# =============================================================================
# CLASSIFIER
# =============================================================================

def classify_event_content(event) -> str:
    """
    Classify a single RawEvent's content type for compaction grouping.

    Returns 'work' | 'personal' | 'unknown'.

    WORK is checked FIRST (allowlist). This guarantees billable work —
    professional software, known work hosts, client documents, and tax
    research — is never misclassified as personal, which is what lets the
    personal set be aggressive without risking billable time.
    """
    title = (getattr(event, 'window_title', '') or '')
    title_l = title.lower()
    url = (getattr(event, 'url', '') or '')
    url_l = url.lower()
    app_l = (getattr(event, 'app_name', '') or '').lower()
    # content_identity may be carried on the event (agent v1.6.8+) or absent.
    ident = (getattr(event, 'content_identity', '') or '')

    host = _extract_host(url_l) if url_l else ''

    # ---- CHECK 0: WORK ALLOWLIST (runs first; nothing below overrides) ----

    # 0a. A confident work content_identity = work.
    if ident and not ident.startswith('personal'):
        return 'work'

    # 0b. Known work host.
    if host:
        for wh in WORK_HOSTS:
            if host == wh or host.endswith('.' + wh) or wh in host:
                return 'work'

    # 0c. Open document (*.pdf) or scanner batch in the title = client work.
    if title and (_PDF_IN_TITLE_RE.search(title) or _SCAN_RE.search(title)):
        return 'work'

    # 0d. Work app marker in title or app_name.
    haystack = f"{title_l} {app_l}"
    for marker in WORK_APP_MARKERS:
        if marker in haystack:
            return 'work'

    # ---- CHECK 1: PERSONAL by URL host ----
    if host:
        for domain in PERSONAL_DOMAINS:
            if host == domain or host.endswith('.' + domain):
                return 'personal'

    # ---- CHECK 2: PERSONAL by MSN content path ----
    if host.endswith('msn.com'):
        path = ''
        try:
            path = urlparse(url_l if '://' in url_l else 'http://' + url_l).path
        except Exception:
            path = ''
        if any(seg in path for seg in _MSN_PERSONAL_PATHS):
            return 'personal'

    # ---- CHECK 3: PERSONAL by title marker ----
    if title_l:
        for marker in PERSONAL_TITLE_MARKERS:
            if marker in title_l:
                return 'personal'
        for ending in _PERSONAL_TITLE_ENDINGS:
            if ending in title_l:
                return 'personal'

    # ---- CHECK 4: PERSONAL by structural headline ----
    # No work signal reached here. A long, prose-like headline that is NOT a
    # document, search, or app screen is almost certainly a news/article read.
    # Conservative: require length + sentence-like shape + no work tokens.
    if _looks_like_headline(title):
        return 'personal'

    # ---- CHECK 5: (residual) work app marker already handled in 0d ----

    # ---- DEFAULT ----
    return 'unknown'


# Tokens that, if present, mean "not a personal headline" (search, app, doc).
_NON_HEADLINE_TOKENS = (
    ' - search', '- search', 'search -', '| search', 'google search',
    'bing maps', 'yahoo search', 'new tab', 'sign in', 'log in', 'login',
    'dashboard', 'untitled', '.pdf', '.xlsx', '.docx', 'home -', 'inbox',
    'calendar', 'onvio', 'quickbooks', 'teams', 'zoom', 'meet -',
    'remote desktop', 'save as', 'print', 'loading',
)


def _looks_like_headline(title: str) -> bool:
    """Heuristic: is this title a news/article HEADLINE (personal) rather than
    a work screen? Conservative — false negatives (miss a headline → 'unknown')
    are safe; false positives (call work a headline) are not, so the gates are
    strict.
    """
    if not title:
        return False
    t = title.replace('\u200b', '')
    # Strip the Edge/Chrome browser suffix and page-counter for analysis.
    t = re.sub(r'\s+and\s+\d+\s+more\s+pages?\s*$', '', t, flags=re.IGNORECASE)
    for suf in (' - Work - Microsoft Edge', ' - Microsoft Edge',
                ' - Google Chrome', ' — Mozilla Firefox'):
        if t.endswith(suf):
            t = t[:-len(suf)].strip()
    tl = t.lower()

    # Must not contain any work/app/search/doc token.
    for tok in _NON_HEADLINE_TOKENS:
        if tok in tl:
            return False

    words = t.split()
    # Headlines are multi-word prose. Require a real sentence length.
    if len(words) < 6:
        return False
    # Headlines rarely contain a file-ish or code-ish token.
    if any(('/' in w or '\\' in w or '_' in w or w.endswith(':')) for w in words):
        return False
    # Require some lowercase prose (work screens are often Title Case / ALLCAPS
    # labels). At least 3 fully-lowercase words signals a sentence.
    lowercase_words = sum(1 for w in words if w.isalpha() and w.islower())
    if lowercase_words < 3:
        return False
    return True


def is_high_confidence_personal(events) -> bool:
    """
    Return True if EVERY event in the list is classified as 'personal'.

    Used by compaction to decide whether to drop the client attribution on a
    personal-content block. We only drop the client when we're certain — a
    single non-personal event in the mix means we keep the client for review.
    """
    events = list(events)
    if not events:
        return False
    return all(classify_event_content(ev) == 'personal' for ev in events)


# =============================================================================
# INTERNALS
# =============================================================================

def _extract_host(url: str) -> str:
    """Pull hostname from a URL, lowercased and 'www.' stripped. '' on failure."""
    try:
        parsed = urlparse(url if '://' in url else f'http://{url}')
        host = (parsed.hostname or '').lower()
        if host.startswith('www.'):
            host = host[4:]
        return host
    except Exception:
        return ''
