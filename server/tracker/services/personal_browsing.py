"""
Personal-browsing detection — flag unambiguously non-work web browsing so it
drops out of the *billable* review pile instead of demanding a decision.

The browser review pile is MOSTLY work (reimbursement PDFs, payroll registers,
bank portals) whose title carries a file code rather than a client name — so a
blanket "browser = non-billable" would massively under-bill. This detector is
deliberately surgical: it fires ONLY on slam-dunk personal categories (weather,
real-estate/apartments, restaurants, sports, music/streaming, job search, prank
sites, travel, lottery) AND only when no work term is present.

Non-billable is the safe direction: a wrongly-non-billable block is visible and
re-billable in Daily Review; it can never mis-charge a client. Even so, the
work-veto keeps professional content (a "Trump Accounts" tax CPE webinar, an
IRS payment page, a client-named search) out of scope.

Pure function of (title, app) — no dependency on neighboring blocks — so it is
safe to run INLINE in the classifier as well as in a backfill command.
"""
from __future__ import annotations

import re

_BROWSER_RE = re.compile(r'edge|chrome|firefox|msedge|brave|opera|safari', re.I)

# Slam-dunk personal categories. Kept intentionally narrow: political/news,
# generic shopping, and social media are OMITTED because a firm may read them
# for work (tax-news, office supplies, a client's Facebook page).
_PERSONAL_RE = re.compile(
    r'weather|forecast|air quality|precipitation|interactive radar'
    r'|\bnfl\b|\bnba\b|\bmlb\b|\bnhl\b|golf|espn|\bsports\b|world series'
    r'|restaurant|yelp|tripadvisor'
    r'|apartment|zillow|realtor|rentcafe|for rent|floor plan|home rentals'
    r'|hotel|airbnb|expedia|\bflight\b|vacation|flight comparison'
    r'|spotify|netflix|hulu|pandora|soundcloud|youtube music'
    r'|podcast|listen to your favorite|lyrics'
    r'|\bjobs?\b|indeed|glassdoor|usajobs|careers'
    r'|typing (?:test|free|speed)|typing\.com|\bprank\b|prankdial|prankgpt'
    r'|comedycalls|\bimdb\b|horoscope|lottery',
    re.I,
)

# Work-term veto: if the title contains any of these, DO NOT flag — leave it in
# review. Guards against professional content that happens to trip a keyword
# (e.g. a "Trump Accounts" tax webinar, "RSM Careers" while researching a firm).
_WORK_RE = re.compile(
    r'\btax\b|\bcpa\b|accounting|webinar|\bcpe\b|\birs\b|payroll|invoice'
    r'|\bclient\b|quickbooks|ledger|audit|1040|1099|\bw-?2\b|reconcil'
    r'|deduction|church|dioces|parish|cemetery|foundation|onvio|paychex'
    r'|statement|reimburs|register|deposit|\bbank\b|ledger|financ',
    re.I,
)


def is_personal_browsing(title: str, app_name: str = "") -> bool:
    """True only for unambiguously personal web browsing.

    Requires a browser app, a slam-dunk personal signal, and NO work term.
    """
    t = title or ""
    if not t:
        return False
    if app_name and not _BROWSER_RE.search(app_name):
        return False
    if not _PERSONAL_RE.search(t):
        return False
    if _WORK_RE.search(t):
        return False
    return True
