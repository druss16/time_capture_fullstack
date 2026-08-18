"""
qb_company_file.py — resolve a QuickBooks Desktop company FILE to a client.

THE PROBLEM
-----------
QuickBooks Desktop puts its Company Name field in the window title, never the
filename or path:

    "St. Mary's Church - QuickBooks Accountant Desktop Plus 2024 - [Home]"

Firms do not keep that name unique. One production directory holds 135 .qbw
company files, of which fourteen are some variant of "St. Mary's ...":

    St. Mary's Church_Clinton_QB2024.QBW
    St. Mary's Cemetery Clinton_QB2024.QBW
    St. Mary's Cemetery Rome_QB2024.qbw
    St. Mary's Assumption Minoa_QB2024.QBW
    St. Mary's Assumption Cemetery Minoa_QB2024.QBW
    st mary's church_Baldwinsville.qbw
    …

Every disambiguator — Clinton, Rome, Minoa, Baldwinsville, Oswego, NY Mills —
lives in the FILENAME and nowhere else. A title-only classifier is choosing
between fourteen parishes with no information, so Stage 3 rightly abstains and
the block used to fall through to Stage 10, where an LLM guessed a town that
appeared nowhere in its input.

The agent reads the open .qbw path off qbw.exe's handle table and reports it as
ctx.qb_company_path. This module turns that path into a client.

Kept free of Django imports so it is unit-testable standalone:
    python server/tracker/qb_company_file_test.py

Mirrors windows_agent/qb_company_tracker.clean_company_file_stem — the agent
applies the same cleaning for its local (tray/widget) inference. Keep in step.
"""
import re

# Bookkeeping noise firms bolt onto company filenames, taken from a real
# 135-file production directory. Stripped before matching so a working copy and
# a version rename still resolve to the same client.
_PREFIX_RE = re.compile(r'^(restored|fixed|copy of|copy)[_\-\s]+', re.IGNORECASE)
_YEAR_RE = re.compile(r'[_\-.\s]*qb?w?\s*20\d\d$', re.IGNORECASE)
_DATE_RE = re.compile(r'[_\-.\s]*\d{6,8}[a-z]?$', re.IGNORECASE)

# Below this, a name matches far too much of a 135-file directory to be trusted.
MIN_MATCHABLE_LEN = 5

# A match must also account for a real share of the filename's identity. A firm
# list carrying both a generic "Sacred Heart" record and specific parish records
# would otherwise let the generic one claim
# "Church of Sacred Heart & St. Mary NY Mills" — 11 matched characters out of
# 32 — and most-specific-wins cannot catch it, because the specific client
# ("Sacred Heart Church") is not contained in that filename at all. Word order
# differs, so containment alone is not evidence of identity.
MIN_COVERAGE = 0.5


def norm(text: str) -> str:
    """Lowercase alphanumerics only: "St. Mary's Church– Clinton" → 'stmaryschurchclinton'."""
    return re.sub(r'[^a-z0-9]+', '', (text or '').lower())


def clean_stem(path: str) -> str:
    """
    Company file path → client identity, with version/date bookkeeping removed.

      "Q:\\QB\\QB2024 Files\\St. Mary's Church_Clinton_QB2024.QBW"
          → "St. Mary's Church_Clinton"
      'fixed_harrington homes of jamesville01142026b.qbw'
          → 'harrington homes of jamesville'

    'Cadd Systems_03042025' and 'Cadd Systems_022626' are the same client, so
    trailing dates and QB version years are stripped: they are metadata about
    the file, not about who the work is for.

    Separator-agnostic — these are Windows paths arriving at a Linux server, so
    os.path would not split them.
    """
    stem = (path or '').replace('/', '\\').rsplit('\\', 1)[-1]
    if '.' in stem:
        stem = stem.rsplit('.', 1)[0]
    stem = _PREFIX_RE.sub('', stem).strip()

    # Suffixes stack in either order ('_01222025_QB2024', 'X_QB2024' after a
    # date), so peel until stable rather than assuming a layout.
    for _ in range(4):
        before = stem
        stem = _YEAR_RE.sub('', stem).strip()
        stem = _DATE_RE.sub('', stem).strip()
        if stem == before:
            break
    return stem.strip(' _-.')


def match_stem(path: str, candidates):
    """
    Resolve a .qbw path against client names/aliases.

    `candidates` is an iterable of (client_id, client_name, matchable_string).
    Returns (client_id, client_name, matched_string), or None to abstain.

    MOST-SPECIFIC WINS: when both "St. Mary's Church" and "St. Mary's Church
    Clinton" are clients and both appear inside the filename, the longer is the
    real subject — the same principle as the Stage-3 substring-domination rule.

    ABSTAINS on a true tie between two different clients, and on any filename
    that matches nothing. Filing a parish's books to its cemetery is precisely
    the failure this module exists to remove, so no-answer beats a coin flip;
    the caller then falls back to the pre-existing title path.
    """
    file_norm = norm(clean_stem(path))
    if len(file_norm) < MIN_MATCHABLE_LEN:
        return None

    best, best_len = [], 0
    for client_id, client_name, matchable in candidates:
        cand_norm = norm(matchable)
        if len(cand_norm) < MIN_MATCHABLE_LEN or cand_norm not in file_norm:
            continue
        # Guard against a generic short record claiming a specific file.
        if len(cand_norm) / len(file_norm) < MIN_COVERAGE:
            continue
        if len(cand_norm) > best_len:
            best_len, best = len(cand_norm), [(client_id, client_name, matchable)]
        elif len(cand_norm) == best_len:
            best.append((client_id, client_name, matchable))

    if not best or len({b[0] for b in best}) > 1:
        return None
    return best[0]


# ─────────────────────────────────────────────────────────────────────────────
# Directory-listing parsing, for the map_qb_company_files command.
#
# Kept here (not in the command) because it is pure and because getting it
# wrong is SILENT: an early version of this parse left the byte-size column
# glued to the front of every filename, which made each company file look
# unique and produced a flattering, meaningless 100% match rate.
# ─────────────────────────────────────────────────────────────────────────────

# `dir` / Get-ChildItem columns that precede the filename: mode, date, time and
# size. Peeled repeatedly so any subset, in any order, is handled.
#
# The SIZE pattern requires 5+ digits on purpose. Client names begin with a
# number more often than you would guess — "100 Maconi Ave., LLC_QB2024.QBW",
# "1819 Lemoyne Avenue LLC_QB2024.qbw" are both real — and a naive ^\d+ ate the
# address, quietly renaming the client. A .qbw company file is megabytes, so a
# real size column is never under five digits and a street number never over
# four.
_DIR_COLUMNS = [
    re.compile(r'^[-dahsrl]{4,7}\s+'),
    re.compile(r'^\d{1,2}/\d{1,2}/\d{2,4}\s+'),
    re.compile(r'^\d{1,2}:\d{2}(:\d{2})?\s*(AM|PM)?\s+', re.IGNORECASE),
    re.compile(r'^\d[\d,]{4,}\s+'),
]

# Everything QuickBooks parks beside a company file. None of these is a company
# file, and each would otherwise truncate at '.qbw' into a phantom duplicate of
# the real one.
_SIDECAR_RE = re.compile(r'\.qbw[.\s]', re.IGNORECASE)


def parse_listing(text):
    """Company filenames out of a directory listing, or a plain list of names.

    Sidecars are dropped: .qbw.ND, .QBW.TLG, .SDS, *.qbw.SearchIndex and the
    "* Tax Forms" entries that sit beside every real file in a QB directory.
    """
    names = []
    for raw in (text or '').splitlines():
        line = raw.strip().strip('"')
        if not line or '.qbw' not in line.lower():
            continue
        if _SIDECAR_RE.search(line):
            continue                    # .qbw.ND / .qbw.TLG / .qbw.SearchIndex
        if not line.lower().endswith('.qbw'):
            continue                    # some other trailing junk — not a name
        changed = True
        while changed:
            changed = False
            for rx in _DIR_COLUMNS:
                new = rx.sub('', line)
                if new != line:
                    line, changed = new, True
        line = line.strip().strip('"')
        if line.lower().endswith('.qbw') and len(clean_stem(line)) >= MIN_MATCHABLE_LEN:
            names.append(line)
    return names


def listing_tokens(text):
    """Distinctive (>=4 char) lowercase tokens, for candidate ranking."""
    return {t for t in re.split(r'[^a-z0-9]+', (text or '').lower()) if len(t) >= 4}


# ─────────────────────────────────────────────────────────────────────────────
# Compaction merge key. Lives here (not in compaction.py) so it is testable
# without Django, and so the ONE definition is shared by all three places
# compaction computes a content_id — they must never drift apart.
# ─────────────────────────────────────────────────────────────────────────────

QB_COMPACT_APPS = {'qbw', 'qbw.exe', 'qbw32', 'qbw32.exe'}


def company_file_key(app_name: str, file_path: str):
    """'qbfile=<path>' when a QB block knows its own .qbw file, else None.

    The company FILE is a stronger identity than the company NAME: a firm's
    QB company names are not unique (fourteen "St. Mary's ..." files in one
    directory), so keying a merge on the name glues two parishes into one
    block. Used by BOTH the grouping key and the block-extension key — they
    must agree, or grouping separates two companies and extension re-merges
    them.
    """
    if (app_name or "").strip().lower() not in QB_COMPACT_APPS:
        return None
    fp = (file_path or "").strip()
    if not fp.lower().endswith(".qbw"):
        return None
    return "qbfile=" + fp.lower()
