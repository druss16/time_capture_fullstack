"""
reconcile_qbw_aliases.py — QuickBooks company-name → client-alias reconciliation.

THE PROBLEM
-----------
QuickBooks Desktop window titles carry the open company file as the first
segment, e.g.:

    "Pinnacle Sealing & Plowing Inc.  - QuickBooks Accountant Desktop Plus 2024"
    "St.Anthony & St. Agnes Church  - QuickBooks Accountant Desktop ..."

The classifier attributes a QB block by matching that company segment against
a Client's name or aliases. But firms enter client names in their practice-
management system differently from how QuickBooks names the company file:

    QB title:       "St.Anthony & St. Agnes Church"
    Client record:  "The Church of St. Anthony &St. Agnes"   ← never matches

Every such mismatch = a client whose QB work silently fails to attribute and
lands in the non-billable bucket. This script finds those mismatches in bulk
and proposes the QB spelling as a new alias on the right client.

WHAT IT DOES
------------
1. Pulls every distinct QB company segment seen in this org's blocks/events.
2. For each, checks whether it ALREADY matches a client (name or alias) via
   the same substring logic the classifier uses. If it matches → skip.
3. For unmatched company strings, fuzzy-matches against client names to find
   the most likely owner.
4. Prints a proposal table. In --apply mode, adds the QB spelling as an alias
   on the matched client (deduped). In dry-run (default), changes nothing.

USAGE (Django shell or manage.py)
---------------------------------
    # Dry run — propose only, change nothing:
    from reconcile_qbw_aliases import run
    run(org_id=21)

    # Apply, but only proposals at/above a confidence floor:
    run(org_id=21, apply=True, min_confidence=0.72)

    # Apply a SINGLE proposal by company string (after reviewing dry run):
    run(org_id=21, apply=True, only="St.Anthony & St. Agnes Church")

SAFETY
------
  - Dry-run is the default. Nothing is written unless apply=True.
  - Never touches a client's `name`, only appends to `aliases` (deduped).
  - Skips meta/internal clients.
  - Skips proposals below min_confidence even in apply mode.
  - Idempotent: re-running after apply is a no-op (the alias now matches).
"""

from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

from tracker.models import Block, RawEvent, Client


# ── QB title parsing ─────────────────────────────────────────────────────────

# The QB product-chrome suffix that follows the company segment.
_QB_SUFFIX_RE = re.compile(
    r'\s*[-–]\s*quickbooks\b.*$', re.IGNORECASE
)
# Bare product titles that carry NO company (skip these entirely).
_QB_BARE_TITLES = {
    'quickbooks accountant desktop plus 2024',
    'quickbooks accountant desktop plus 2025',
    'quickbooks accountant desktop',
    'quickbooks desktop',
    'quickbooks',
}
# Screen/modal titles that aren't company names (no " - QuickBooks" suffix and
# not a company file). These show up as their own blocks; we can't recover a
# company from them here, so they're skipped.
_QB_MODAL_TITLES = {
    'preview paycheck', 'positive deduction?', 'select date range for liabilities',
    'write checks', 'reconcile', 'pay liabilities', 'home',
    'enter payroll information', 'review and create paychec',
    'review and create paychecks', 'employee center: payroll',
}

_META_CLIENT_NAMES = {
    'internal', 'internal - tax', 'internal tax', 'internal-tax',
    'admin', 'administration', 'office', 'firm', 'firm work',
    'overhead', 'general', 'misc', 'miscellaneous',
}


def _extract_company(title: str) -> str | None:
    """Pull the company-file segment from a QB window title, or None."""
    if not title:
        return None
    t = title.strip()
    low = t.lower()

    # Must look like a QB window with the product suffix.
    if 'quickbooks' not in low and 'qbw' not in low:
        return None

    # Strip a trailing screen bracket: "... - [Vendor Center: X]"
    bracket = t.rfind(' - [')
    if bracket > 0:
        t = t[:bracket]
        low = t.lower()

    # Remove the " - QuickBooks ..." product suffix to leave the company.
    company = _QB_SUFFIX_RE.sub('', t).strip()
    company_low = company.lower().strip()

    if not company_low:
        return None
    if company_low in _QB_BARE_TITLES:
        return None
    if company_low in _QB_MODAL_TITLES:
        return None
    # If after stripping we still have the word "quickbooks", it was a bare
    # title we failed to fully strip — skip.
    if 'quickbooks' in company_low:
        return None
    # Too short to be a real company name.
    if len(company_low) < 4:
        return None

    return company


# ── Matching (mirrors the classifier's substring intent, simplified) ─────────

def _normalize(s: str) -> str:
    s = (s or '').lower()
    s = s.replace("'", "").replace("\u2019", "")
    s = re.sub(r'[.,()&/\\|:;!?"*\u2013\u2014\-\[\]{}]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _already_matches(company: str, client) -> bool:
    """True if `company` already resolves to this client via name/alias substring."""
    hay = _normalize(company)
    names = [client.name] + list(getattr(client, 'aliases', None) or [])
    for n in names:
        nn = _normalize(n)
        if nn and len(nn) >= 4 and (nn in hay or hay in nn):
            return True
    return False


def _any_client_matches(company: str, clients) -> bool:
    return any(_already_matches(company, c) for c in clients)


def _similarity(a: str, b: str) -> float:
    """Token-aware similarity for ranking the best client for an unmatched company."""
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return 0.0
    # Base: sequence ratio on normalized strings.
    base = SequenceMatcher(None, na, nb).ratio()
    # Boost: shared distinctive tokens (>=4 chars), to reward real word overlap
    # over coincidental character runs.
    ta = {t for t in na.split() if len(t) >= 4}
    tb = {t for t in nb.split() if len(t) >= 4}
    if ta and tb:
        shared = len(ta & tb) / max(1, min(len(ta), len(tb)))
        return round(0.5 * base + 0.5 * shared, 3)
    return round(base, 3)


def _best_client_for(company: str, clients):
    """Return (client, score) of the most similar non-meta client, or (None, 0)."""
    best, best_score = None, 0.0
    for c in clients:
        if c.name.strip().lower() in _META_CLIENT_NAMES:
            continue
        s = _similarity(company, c.name)
        # Also try the client's aliases — sometimes the QB name is closer to an
        # existing alias than to the canonical name.
        for a in (getattr(c, 'aliases', None) or []):
            s = max(s, _similarity(company, a))
        if s > best_score:
            best, best_score = c, s
    return best, best_score


# ── Main entry ───────────────────────────────────────────────────────────────

def run(org_id: int, apply: bool = False, min_confidence: float = 0.62,
        only: str | None = None, scan_events: bool = True, verbose: bool = True):
    """
    Reconcile QB company names to client aliases for one org.

    Args:
        org_id:         Organization to process.
        apply:          When True, write aliases. Default False (dry run).
        min_confidence: Only propose/apply matches at/above this similarity.
        only:           If set, restrict to this exact company string.
        scan_events:    Also scan RawEvent titles (not just Block titles) for
                        company strings. More coverage, slightly slower.
        verbose:        Print the proposal table.
    """
    clients = list(Client.objects.filter(org_id=org_id))
    if not clients:
        print(f"[reconcile] org {org_id}: no clients found.")
        return

    # ── Gather distinct company strings ──
    company_counts: dict[str, int] = defaultdict(int)

    block_titles = (
        Block.objects.filter(org_id=org_id)
        .exclude(window_title__isnull=True).exclude(window_title__exact='')
        .values_list('window_title', flat=True)
    )
    for t in block_titles.iterator():
        comp = _extract_company(t)
        if comp:
            company_counts[comp] += 1

    if scan_events:
        ev_titles = (
            RawEvent.objects.filter(block__org_id=org_id)
            .exclude(window_title__isnull=True).exclude(window_title__exact='')
            .values_list('window_title', flat=True)
        )
        for t in ev_titles.iterator():
            comp = _extract_company(t)
            if comp:
                company_counts[comp] += 1

    if not company_counts:
        print(f"[reconcile] org {org_id}: no QB company strings found.")
        return

    # ── Build proposals for companies that DON'T already match a client ──
    proposals = []   # (company, count, client, score)
    skipped_matched = 0

    for company, count in sorted(company_counts.items(), key=lambda kv: -kv[1]):
        if only and company != only:
            continue
        if _any_client_matches(company, clients):
            skipped_matched += 1
            continue
        client, score = _best_client_for(company, clients)
        if client:
            proposals.append((company, count, client, score))

    # ── Report ──
    if verbose:
        print(f"\n[reconcile] org {org_id}: {len(company_counts)} distinct QB "
              f"company strings; {skipped_matched} already match a client.\n")
        if not proposals:
            print("  Nothing to propose — every QB company already resolves. ✅")
        else:
            print(f"  {len(proposals)} unmatched compan{'y' if len(proposals)==1 else 'ies'} "
                  f"(min_confidence={min_confidence}):\n")
            print(f"    {'CONF':<6} {'SEEN':<5} {'QB COMPANY':<42} → CLIENT")
            print(f"    {'-'*6} {'-'*5} {'-'*42}   {'-'*30}")
            for company, count, client, score in proposals:
                flag = ' ' if score >= min_confidence else '·'  # · = below floor
                print(f"  {flag} {score:<6.2f} {count:<5} {company[:42]:<42} → "
                      f"{client.name}  (#{client.id})")
            below = sum(1 for *_, s in proposals if s < min_confidence)
            if below:
                print(f"\n    ({below} marked '·' are below min_confidence — "
                      f"not applied even with apply=True; review manually.)")

    # ── Apply ──
    if not apply:
        print(f"\n[reconcile] DRY RUN — nothing written. "
              f"Re-run with apply=True to add aliases.\n")
        return

    applied = 0
    for company, count, client, score in proposals:
        if score < min_confidence:
            continue
        existing = list(client.aliases or [])
        # Dedupe case-insensitively.
        if any(_normalize(a) == _normalize(company) for a in existing):
            continue
        client.aliases = list(dict.fromkeys(existing + [company]))
        client.save(update_fields=['aliases'])
        applied += 1
        print(f"  ✓ added alias '{company}' → {client.name} (#{client.id}) "
              f"[conf {score:.2f}]")

    print(f"\n[reconcile] APPLIED {applied} alias(es). "
          f"Reset affected blocks to 'captured' and re-run classification "
          f"to attribute them.\n")