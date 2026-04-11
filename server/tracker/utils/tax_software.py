# tracker/utils/tax_software.py
"""
Tax software window title parser for TimeTracker.

PURPOSE:
  Extracts taxpayer name + return type from tax software window titles
  (UltraTax CS, TaxWise, Lacerte, ProSeries) so blocks can be bucketed
  by individual taxpayer without storing any PII.

SSN / EIN HANDLING:
  SSNs and EINs appear in UltraTax window titles. We parse them purely
  for deduplication (to distinguish "Wood, Michael Sr." from "Wood, Michael Jr.")
  then immediately discard the raw value. Only a truncated SHA-256 hash is
  retained — computationally irreversible, SOC 2 safe, never stored in plain text.

SUPPORTED SOFTWARE:
  - UltraTax CS  (Utw25.exe / Utw24.exe)
  - TaxWise      (Tww24.exe / Tww23.exe)
  - Lacerte      (future-proofed)
  - ProSeries    (future-proofed)

USAGE:
  from tracker.utils.tax_software import extract_tax_context, is_generic_tax_dialog

  ctx = extract_tax_context(block.window_title)
  if ctx:
      # ctx.taxpayer_name     → "Wood, Michael"
      # ctx.taxpayer_id_hash  → "a3f9c2b18e44"  (hash only, SSN gone)
      # ctx.return_type       → "1040"
      # ctx.software          → "ultratax"
      # ctx.category          → "Tax Preparation"
      # ctx.is_business_return → False (1040 = individual)

  if is_generic_tax_dialog(block.window_title):
      # Suppress this block — no client signal
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Data structure
# ---------------------------------------------------------------------------

@dataclass
class TaxSoftwareContext:
    taxpayer_name: str          # "Wood, Michael" — display name only
    taxpayer_id_hash: str       # sha256(ssn_or_ein)[:12] — dedup key, NOT the SSN
    return_type: str            # "1040", "1120S", "1065", "990", etc.
    software: str               # "ultratax" | "taxwise" | "lacerte" | "proseries"
    category: str               # always "Tax Preparation" for open returns

    @property
    def is_business_return(self) -> bool:
        """True for entity returns that may match a client record."""
        return self.return_type in ('1065', '1120', '1120S', '1120-S', '990', '990EZ')

    @property
    def is_individual_return(self) -> bool:
        return not self.is_business_return


# ---------------------------------------------------------------------------
# Regex patterns per software
# ---------------------------------------------------------------------------

# UltraTax CS: "2025 UltraTax CS / 1040 [103545863 WOOD, MICHAEL"
#              "Utw25 - 2025 UltraTax CS / 1065 [123456789 EVERSON CORP, LLC"
_UT_PATTERN = re.compile(
    r'(?:1040|1120-?S?|1065|990(?:EZ|PF)?|1041|706|709)'
    r'\s*\[(\w{5,12})\s+([A-Z][A-Z0-9\s,\.&\-]+?)(?:\]|(?=\s*-\s*\[)|\Z)',
    re.IGNORECASE,
)

# TaxWise: "TaxWise 2024 on Z drive : Version 39.03 : 1040 Individual : Terri : 133-32-2621"
# TaxWise: "TaxWise 2024 on Z drive : Version 39.03 : 1040 In SMITH JOHN"
_TW_PATTERN = re.compile(
    r'TaxWise.*?:\s*(1040|1120-?S?|1065|990(?:EZ)?)\s+(?:Individual|In)\s.*?:\s*(\d{3}-\d{2}-\d{4})\s*$',
    re.IGNORECASE,
)
_TW_PATTERN_NAME = re.compile(
    r'TaxWise.*?:\s*(1040|1120-?S?|1065|990(?:EZ)?)\s+In\s+([A-Z][A-Za-z\s,\.]+)',
    re.IGNORECASE,
)

# Lacerte: "Lacerte Tax 2024 - SMITH, JOHN - 1040"
_LA_PATTERN = re.compile(
    r'Lacerte.*?-\s*([A-Z][A-Za-z\s,\.]+?)\s*-\s*(1040|1120-?S?|1065|990)',
    re.IGNORECASE,
)

# ProSeries: "ProSeries 2024 - Smith John - Form 1040"
_PS_PATTERN = re.compile(
    r'ProSeries.*?-\s*([A-Z][A-Za-z\s,\.]+?)\s*-\s*Form\s*(1040|1120-?S?|1065|990)',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Generic dialog titles to suppress (no client signal — block classifier
# and ai_client_switcher both import this set)
# ---------------------------------------------------------------------------

GENERIC_TAX_DIALOGS: set[str] = {
    # UltraTax generic windows
    "cflvoutframe",
    "cflyoutframe",
    "client properties",
    "input screen ctrl+i",
    "statements from a",
    "statements from b&d",
    "statements from w2",
    "statements from broker",
    "statements from 1099",
    "dividend income",
    "electronic filing status",
    "data sharing - pending updates",
    "return list",
    "open client",
    "print returns",
    "printing status",
    "print status",
    "online status",
    "call summary",
    "confirm",
    "edit note",
    "field note/tick",
    "dependents",
    "select package",
    # Bare UltraTax app titles (no return open)
    "2025 ultratax cs",
    "2024 ultratax cs",
    "2023 ultratax cs",
    "ultratax cs",
    # TaxWise bare app titles
    "taxwise 2024 on z drive",
    "taxwise 2023 on z drive",
    "taxwise 2024",
    "taxwise 2023",
    "taxwise 2024 on z drive : version  39.03",
    "taxwise 2023 on z drive : version  38.04",
    # Generic Office / Windows
    "book1 - excel",
    "book1",
    "document1 - word",
    "save as",
    "new tab",
    "program manager",
    "about:blank",
}

# Apps whose bare title (no return open) should be suppressed
GENERIC_TAX_EXES = {"utw25.exe", "utw24.exe", "tww24.exe", "tww23.exe"}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hash_id(raw_id: str) -> str:
    """
    One-way SHA-256 hash of an SSN or EIN.
    Input is immediately discarded after this call — never stored.
    Returns first 12 hex chars (48-bit space — sufficient for dedup within a firm).
    """
    return hashlib.sha256(raw_id.strip().encode()).hexdigest()[:12]


def _normalize_name(raw: str) -> str:
    """
    Normalize a taxpayer name from tax software title casing.
    "WOOD, MICHAEL"        → "Wood, Michael"
    "EVERSON CORP LLC"     → "Everson Corp Llc"   (entity — acceptable)
    "SMITH JOHN"           → "Smith John"          (TaxWise no-comma format)
    """
    raw = raw.strip().rstrip('.,')
    if ',' in raw:
        parts = [p.strip().title() for p in raw.split(',', 1)]
        return ', '.join(parts)
    return raw.title()


def _clean_suffix(name: str) -> str:
    """
    Preserve name suffixes so they display correctly.
    "Wood, Michael Jr"  → "Wood, Michael Jr."
    "Wood, Michael SR"  → "Wood, Michael Sr."
    """
    suffix_pattern = re.compile(
        r'\b(Jr\.?|Sr\.?|II|III|IV|V|Esq\.?)\s*$', re.IGNORECASE
    )
    m = suffix_pattern.search(name)
    if m:
        suffix_map = {
            'jr': 'Jr.', 'jr.': 'Jr.',
            'sr': 'Sr.', 'sr.': 'Sr.',
            'ii': 'II', 'iii': 'III', 'iv': 'IV', 'v': 'V',
            'esq': 'Esq.', 'esq.': 'Esq.',
        }
        raw_suffix = m.group(0).strip().rstrip('.')
        canonical = suffix_map.get(raw_suffix.lower(), raw_suffix)
        base = name[:m.start()].strip().rstrip(',')
        return f"{base} {canonical}"
    return name

def _lookup_name_by_hash(ssn_hash: str) -> Optional[str]:
    """
    Cross-reference a TaxpayerBucket by hash to get the real display name.
    Used by TaxWise (SSN-only titles) to resolve names from UltraTax records.
    Returns None if no match found — caller falls back to SSN-XXXX.
    """
    try:
        from tracker.models import TaxpayerBucket
        bucket = TaxpayerBucket.objects.filter(
            taxpayer_id_hash=ssn_hash
        ).first()
        return bucket.display_name if bucket else None
    except Exception:
        return None

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_tax_context(title: str) -> Optional[TaxSoftwareContext]:
    """
    Parse a window title from tax software and return a TaxSoftwareContext.
    Returns None if the title has no actionable open-return signal.

    SSN/EIN is extracted purely to generate taxpayer_id_hash, then discarded.
    The raw SSN/EIN never leaves this function.
    """
    if not title:
        return None

    # --- UltraTax CS ---
    m = _UT_PATTERN.search(title)
    if m:
        raw_id   = m.group(1).strip()          # SSN or EIN — hashed immediately
        raw_name = m.group(2).strip()
        name = _clean_suffix(_normalize_name(raw_name))
        # Detect return type from the part before the bracket
        rt_match = re.search(
            r'(1040|1120-?S?|1065|990(?:EZ|PF)?|1041|706|709)',
            title[:m.start()], re.IGNORECASE
        )
        return_type = rt_match.group(1).upper().replace('-', '') if rt_match else "1040"

        return TaxSoftwareContext(
            taxpayer_name=name,
            taxpayer_id_hash=_hash_id(raw_id),   # raw_id not stored beyond here
            return_type=return_type,
            software="ultratax",
            category="Tax Preparation",
        )

    # --- TaxWise ---
    # --- TaxWise (SSN format) ---
    # "TaxWise 2024 on Z drive : Version 39.03 : 1040 Individual : Terri : 133-32-2621"
    m = _TW_PATTERN.search(title)
    if m:
        return_type = m.group(1).upper().replace('-', '')
        raw_ssn = m.group(2).replace('-', '')   # strip dashes → "133322621"
        ssn_hash = _hash_id(raw_ssn)            # raw SSN discarded after this line

        # Cross-reference against TaxpayerBucket to get real name if already known
        name = _lookup_name_by_hash(ssn_hash) or f"SSN-{m.group(2)[-4:]}"

        return TaxSoftwareContext(
            taxpayer_name=name,
            taxpayer_id_hash=ssn_hash,
            return_type=return_type,
            software="taxwise",
            category="Tax Preparation",
        )

    # --- TaxWise (name format, older) ---
    m = _TW_PATTERN_NAME.search(title)
    if m:
        return_type = m.group(1).upper().replace('-', '')
        raw_name    = m.group(2).strip()
        name = _clean_suffix(_normalize_name(raw_name))
        return TaxSoftwareContext(
            taxpayer_name=name,
            taxpayer_id_hash=_hash_id(name.lower()),
            return_type=return_type,
            software="taxwise",
            category="Tax Preparation",
        )

    # --- Lacerte ---
    m = _LA_PATTERN.search(title)
    if m:
        raw_name    = m.group(1).strip()
        return_type = m.group(2).upper().replace('-', '')
        name = _clean_suffix(_normalize_name(raw_name))
        return TaxSoftwareContext(
            taxpayer_name=name,
            taxpayer_id_hash=_hash_id(name.lower()),
            return_type=return_type,
            software="lacerte",
            category="Tax Preparation",
        )

    # --- ProSeries ---
    m = _PS_PATTERN.search(title)
    if m:
        raw_name    = m.group(1).strip()
        return_type = m.group(2).upper().replace('-', '')
        name = _clean_suffix(_normalize_name(raw_name))
        return TaxSoftwareContext(
            taxpayer_name=name,
            taxpayer_id_hash=_hash_id(name.lower()),
            return_type=return_type,
            software="proseries",
            category="Tax Preparation",
        )

    return None


def is_generic_tax_dialog(title: str) -> bool:
    """
    Returns True if the title is a generic tax software dialog with no
    client signal — these blocks should be suppressed (no classification attempt).
    """
    if not title:
        return True
    return title.lower().strip() in GENERIC_TAX_DIALOGS


def is_internal_firm_work(title: str) -> Optional[str]:
    """
    Returns a category string if this title is clearly internal firm overhead,
    NOT billable client work. Returns None if it could be client work.

    Used by block_classifier.py to short-circuit before any client matching.
    """
    if not title:
        return None
    t = title.lower()

    # Internal timesheets / payroll — staff admin, not client work
    if re.search(r'\b(timesheet|time\s*sheet|staff\s*hours|payroll)\b', t):
        return "Billing / Admin"

    # Generic meaningless Excel/Word sessions
    if re.search(r'\b(book\s*1|document\s*1|untitled)\b', t):
        return "Billing / Admin"

    return None
