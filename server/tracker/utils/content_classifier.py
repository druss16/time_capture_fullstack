"""
tracker/utils/content_classifier.py

Lightweight, deterministic content classifier for RawEvents.

Used by compaction.py to split blocks by content type, so that personal
browsing (news, social media, streaming) doesn't get merged with legitimate
client work that happens to share the same app/client/session.

DESIGN PRINCIPLES
=================
- Cheap: no AI, no DB, no I/O. Pure string matching.
- Conservative: when in doubt, return 'unknown'. Don't mislabel work as personal
  (that would silently drop billable time) and don't mislabel personal as work
  (that would silently bill the client for news reading).
- Deterministic: same input always produces same output. Important for
  reproducible compaction.

USAGE
=====
    from tracker.utils.content_classifier import classify_event_content

    bucket = classify_event_content(raw_event)
    # bucket is one of: 'work', 'personal', 'unknown'

EXTENSION
=========
The PERSONAL_* and WORK_* lists are designed to be extended over time.
When making changes:
  - Add to PERSONAL_DOMAINS only when the domain has no reasonable work use
    (so "youtube.com" stays out — it might be a CPE video)
  - Add to WORK_TITLE_MARKERS only when the marker is unique to work software
    (so "Excel" is fine, but "tax" is too generic)
"""

from urllib.parse import urlparse


# =============================================================================
# DOMAINS — personal/non-work sites
# =============================================================================
# Match against the URL field of RawEvent. Substring match on the hostname,
# case-insensitive. Include news, social, streaming, sports, entertainment.
# Avoid generic platforms (youtube, github, reddit) that could be work-related.

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

    # Local news (Syracuse area — extend per market)
    'syracuse.com', '9wsyr.com', 'cnycentral.com', 'localsyr.com',
    'wstm.com', 'wsyr.com',

    # Sports
    'espn.com', 'sports.yahoo.com', 'bleacherreport.com', 'cbssports.com',
    'foxsports.com', 'nfl.com', 'nba.com', 'mlb.com', 'nhl.com',
    'pgatour.com', 'athletic.com', 'theathletic.com',

    # Social media
    'twitter.com', 'x.com', 'facebook.com', 'instagram.com', 'tiktok.com',
    'snapchat.com', 'pinterest.com', 'tumblr.com', 'mastodon.social',
    'threads.net', 'bsky.app',

    # Entertainment / streaming
    'netflix.com', 'hulu.com', 'disneyplus.com', 'hbomax.com', 'max.com',
    'primevideo.com', 'spotify.com', 'pandora.com', 'soundcloud.com',
    'twitch.tv',

    # Shopping (not always personal but very rarely client work)
    'amazon.com', 'ebay.com', 'etsy.com', 'walmart.com', 'target.com',

    # Gossip/Lifestyle
    'buzzfeed.com', 'eonline.com', 'usmagazine.com', 'cosmopolitan.com',
])


# =============================================================================
# TITLE MARKERS — phrases that strongly suggest personal browsing
# =============================================================================
# Match against window_title, case-insensitive substring. Used when the URL
# field is empty (most desktop apps don't expose URL) but the title contains
# unambiguous personal-content markers.

PERSONAL_TITLE_MARKERS = frozenset([
    # News brand markers
    'fox news -', 'cnn -', 'cnn.com', 'msnbc -', 'breaking news',
    'syracuse news', '9wsyr',
    # News brand markers WITHOUT a trailing dash — real window titles read
    # "Fox News apologizes..." or "MSN | Personalized News..." with the brand
    # at the START, which the dash-suffixed markers above missed. High-confidence
    # personal. Verified vs block 46880 (Eileen): catches the MSN/Fox news,
    # ZERO false positives on the 10 parish-work events in the same block.
    'fox news', 'msn |', 'msnbc', 'newsmax', 'breitbart', 'huffpost',
    'yahoo news', 'usa today', 'maggie haberman', 'barron trump',

    # Sports markers
    ' nfl ', ' nba ', ' mlb ', ' nhl ', ' pga ', 'sports highlights',

    # Social media markers
    ' - twitter', ' / x', '(@', ' - facebook', ' - instagram',
])


# =============================================================================
# WORK APP MARKERS — phrases that strongly suggest legitimate client work
# =============================================================================
# Match against window_title OR app_name, case-insensitive substring.
# Used to prevent false-positive personal classification when title is
# ambiguous but app context is clearly professional software.

WORK_APP_MARKERS = frozenset([
    # CPA tax software
    'ultratax', 'lacerte', 'taxwise', 'drake tax', 'drake software',
    'proseries', 'atx ',

    # CPA / accounting platforms
    'cs professional', 'cs connect', 'onvio', 'workpapers cs',
    'fixed assets cs', 'accounting cs', 'practice cs',

    # Bookkeeping
    'quickbooks', 'qbo', 'xero', 'sage ', 'freshbooks', 'wave accounting',

    # Payroll
    'paychex', 'adp ', 'gusto', 'rippling',

    # Document workflow
    ' - excel', ' - word', ' - powerpoint', ' - outlook',
    'adobe acrobat', 'adobe reader',

    # Generic professional indicators
    'cch axcess', 'thomson reuters', 'wolters kluwer',
])


# =============================================================================
# CLASSIFIER
# =============================================================================

def classify_event_content(event) -> str:
    """
    Classify a single RawEvent's content type for compaction grouping.

    Returns:
        'personal' — strong signal this is news/social/streaming/etc.
        'work'     — strong signal this is professional software / client work
        'unknown'  — couldn't determine; let existing logic handle it

    Order of checks (most specific first):
      1. URL hostname matches PERSONAL_DOMAINS → 'personal'
      2. Title matches PERSONAL_TITLE_MARKERS → 'personal'
      3. Title or app matches WORK_APP_MARKERS → 'work'
      4. Otherwise → 'unknown'

    The 'personal' checks run first because work apps (like Edge browser)
    can host personal content, and we want the content to override the app.
    For example, "Microsoft Edge" alone is unknown, but "Microsoft Edge"
    showing foxnews.com is clearly personal.
    """
    title = (getattr(event, 'window_title', '') or '').lower()
    url = (getattr(event, 'url', '') or '').lower()
    app = (getattr(event, 'app_name', '') or '').lower()

    # --- Check 1: URL hostname against personal domains ---
    if url:
        host = _extract_host(url)
        if host:
            # Match either exact host or any subdomain (e.g. m.foxnews.com)
            for domain in PERSONAL_DOMAINS:
                if host == domain or host.endswith('.' + domain):
                    return 'personal'

    # --- Check 2: Title markers for personal content ---
    if title:
        for marker in PERSONAL_TITLE_MARKERS:
            if marker in title:
                return 'personal'

        # Additional check: news-style trailing brand suffixes that don't
        # appear in PERSONAL_TITLE_MARKERS but are common in window titles
        # like "Some Headline | Fox News" or "Article — The New York Times"
        if any(ending in title for ending in (
            '| fox news',
            '- fox news',
            '| cnn',
            '- cnn.com',
            '- the new york times',
            '- the washington post',
            '- the guardian',
            '- bbc news',
            '- reuters',
            '- ap news',
            '- syracuse.com',
        )):
            return 'personal'

    # --- Check 3: Work app markers ---
    haystack = f"{title} {app}"
    for marker in WORK_APP_MARKERS:
        if marker in haystack:
            return 'work'

    # --- Default ---
    return 'unknown'


def is_high_confidence_personal(events) -> bool:
    """
    Return True if EVERY event in the list is classified as 'personal'.

    Used by compaction to decide whether to drop the client attribution on
    a personal-content block. We only drop the client when we're certain —
    a single 'unknown' event in the mix means we keep the agent's client
    pick for review.

    Args:
        events: iterable of RawEvent objects

    Returns:
        bool
    """
    events = list(events)
    if not events:
        return False
    return all(classify_event_content(ev) == 'personal' for ev in events)


# =============================================================================
# INTERNALS
# =============================================================================

def _extract_host(url: str) -> str:
    """
    Pull the hostname out of a URL, lowercased and 'www.' stripped.
    Returns '' on parse failure.
    """
    try:
        parsed = urlparse(url if '://' in url else f'http://{url}')
        host = (parsed.hostname or '').lower()
        if host.startswith('www.'):
            host = host[4:]
        return host
    except Exception:
        return ''