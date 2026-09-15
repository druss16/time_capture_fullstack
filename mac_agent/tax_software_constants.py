# windows_agent/tax_software_constants.py
"""
Shared suppress lists and tax software constants for the TimeTracker Windows agent.

This file is the AGENT-SIDE copy of the constants defined in:
  tracker/utils/tax_software.py  (Django backend)

Both files must be kept in sync. When you add a new generic dialog title
or tax software exe to suppress, update BOTH files.

SYNC CHECKLIST (update both when changing either):
  - GENERIC_TAX_DIALOGS  →  ai_client_switcher.py _should_skip()
                          →  block_classifier.py  Stage 0a
  - GENERIC_TAX_EXES     →  ai_client_switcher.py __init__ (merged into _skip_exes)
"""

# ---------------------------------------------------------------------------
# Generic tax software dialog titles — no client signal, suppress entirely.
# Titles are lowercased for case-insensitive comparison.
# ---------------------------------------------------------------------------

import re


GENERIC_TAX_DIALOGS: set = {
    # UltraTax CS generic dialogs (no return open)
    "cflvoutframe",
    "cflyoutframe",
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
    "client properties",
    "open client",
    "return list",
    "print returns",
    "printing status",
    "data sharing",
    "cflyoutframe",


    # Bare UltraTax app titles (app open, no return loaded)
    "2025 ultratax cs",
    "2024 ultratax cs",
    "2023 ultratax cs",
    "ultratax cs",

    # TaxWise bare app titles
    "taxwise 2024 on z drive",
    "taxwise 2023 on z drive",
    "taxwise 2024",
    "taxwise 2023",

    # Generic Office / Windows chrome — no meaningful signal
    "book1 - excel",
    "book1",
    "document1 - word",
    "save as",
    "new tab",
    "program manager",
    "about:blank",
}

# ---------------------------------------------------------------------------
# Tax software exe names — when these are the active process with no
# meaningful window title, skip entirely (don't attempt client switch).
# ---------------------------------------------------------------------------

GENERIC_TAX_EXES: set = {
    "utw25.exe",   # UltraTax 2025
    "utw24.exe",   # UltraTax 2024
    "utw23.exe",   # UltraTax 2023
    "tww24.exe",   # TaxWise 2024
    "tww23.exe",   # TaxWise 2023
}

# Matches any open tax software return title
# Covers UltraTax and TaxWise open-return patterns
TAX_SOFTWARE_RETURN_PATTERN = re.compile(
    r'(?:1040|1120-?S?|1065|990(?:EZ|PF)?|1041|706|709)'
    r'\s*\[[\w]+\s+[A-Z]',  # \w handles both SSNs and alphanumeric codes
    re.IGNORECASE,
)

TAX_SOFTWARE_TAXWISE_PATTERN = re.compile(
    r'TaxWise.*?:\s*(?:1040|1120-?S?|1065|990)\s+(?:In\s+|Individual\s*:?\s*)[A-Z\d]',
    re.IGNORECASE,
)

# The client name in your system that individual returns should map to.
# Create a client record with this exact name in TimeTracker.
INTERNAL_TAX_CLIENT_NAME = "Internal - Tax"

