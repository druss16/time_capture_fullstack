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


_QB_TITLE_RE = re.compile(r'^(?P<c>.+?)\s+[-\u2013]\s+quickbooks\b', re.IGNORECASE)


def extract_qb_company(title: str):
    """'{Company} - QuickBooks ... - [Screen]' -> 'Company', else None.

    The '(Primary)' / '(Secondary)' markers QuickBooks appends when two company
    files are open are stripped: they identify the WINDOW, not the client.
    """
    t = (title or '').rsplit(' - [', 1)[0].strip()
    m = _QB_TITLE_RE.match(t)
    if not m:
        return None
    c = re.sub(r'\s*\([^)]*\)\s*$', '', m.group('c').strip()).strip()
    if len(c) < 4 or c.lower().startswith(('quickbooks', 'intuit')):
        return None
    return c


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

    # The FILE must not out-specify the client. "St. Mary's Cemetery Rome" and
    # "St. Mary's Cemetery Central SQ" are real files on this share with no
    # client of their own; client 125's generic alias "St. Mary's Cemetery"
    # covers most of each name and MIN_COVERAGE happily lets it claim both, so
    # a Rome cemetery's books land on a Baldwinsville one. A place or name word
    # in the FILE that appears in none of the client's names means the file is
    # naming a different entity, and no-answer beats a coin flip.
    #
    # Every word is weighed against ALL of that client's matchables, not just
    # the one that matched: client 105 is named "Sacred Heart & St. Mary's
    # Church" but carries "Sacred Heart NY Mills", and its file needs both
    # halves to be accounted for.
    winner_id = best[0][0]
    client_words = set()
    for cid, _cname, matchable in candidates:
        if cid == winner_id:
            client_words |= _identifying_words(matchable)
    file_words = _identifying_words(clean_stem(path))
    if (file_words - client_words) and (client_words - file_words):
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


# ─────────────────────────────────────────────────────────────────────────────
# Interpreting the agent's raw report (ctx.qb_report).
#
# The agent reports observations and does not decide. It cannot decide well:
# most QuickBooks samples are modals with no company name in the title, so an
# agent-side rule that needs one discards everything. The server has what the
# agent lacks — every event in the block, so a company name from ANY sample
# covers the modals, plus the client list.
# ─────────────────────────────────────────────────────────────────────────────

# The winner must be this much fresher than the next candidate. Seven people
# share the drive, so several files are always warm; only a decisive lead means
# "this block's work", and anything closer is a coin flip between colleagues.
RECENT_LEAD_SECONDS = 120

# Beyond this the file was not being worked in during the block, whatever else
# was going on.
RECENT_MAX_AGE_SECONDS = 60 * 60

# Observed in the field: an agent picked a company file because it was 15 days
# less stale than the next candidate — both over FIVE YEARS old, both in a
# folder named "MaryLou's Old QB files". It landed on the right client only
# because the name filter had already narrowed the field; with an ambiguous
# name like "St. Mary's Church" the same coin flip chooses between two
# parishes. So when every candidate is ancient, the timestamps are not tracking
# anything and ranking by them is ranking noise.
SIGNAL_MAX_AGE_SECONDS = 24 * 60 * 60


# Vocabulary an entire book of parishes shares, so it can never say WHICH one.
# Deliberately local rather than imported from classification_service: that
# module imports this one, and a module-level import back would be a cycle.
_COMPANY_STOPWORDS = frozenset({
    'saint', 'saints', 'st', 'church', 'churches', 'catholic', 'parish',
    'cemetery', 'school', 'academy', 'chapel', 'fund', 'foundation',
    'diocese', 'ministry', 'mission', 'community', 'company', 'incorporated',
    'inc', 'llc', 'ltd', 'corp', 'the', 'and', 'of', 'our', 'lady',
    'qbw', 'qb', 'file', 'files', 'data', 'backup', 'copy', 'restored',
    'primary', 'secondary', 'current', 'new', 'old',
})


# Mutually exclusive kinds of entity. A parish keeps its church, its cemetery
# and its school as SEPARATE clients with separate books, so a title naming one
# can never be satisfied by a file naming another — however many words they
# share. Local to this module for the same reason _COMPANY_STOPWORDS is.
_ENTITY_CLASSES = frozenset({'church', 'cemetery', 'school', 'academy',
                             'fund', 'foundation'})


def _entity_class(text):
    """Which kind of entity this name claims, if any."""
    import re as _re
    words = {w for w in _re.split(r"[^a-z0-9]+", (text or '').lower())}
    return {w[:-1] if w.endswith('s') and w[:-1] in _ENTITY_CLASSES else w
            for w in words} & _ENTITY_CLASSES


def _identifying_words(text):
    """Words from a company name or file stem that actually name somebody.

    Drops separators and the vocabulary every parish shares, so "St. Mary's
    Church" and "st._marys_minoa.qbw" meet on {mary} while "St. Patrick's
    Taberg" shares nothing with either.
    """
    import re as _re
    out = set()
    for w in _re.split(r"[^a-z0-9]+", (text or '').lower()):
        # Stem the possessive: a company name says "St. Mary's Church" and the
        # file says "st._marys_minoa.qbw". Without this they share nothing and
        # the corroboration silently never fires.
        if len(w) >= 5 and w.endswith('s'):
            w = w[:-1]
        if len(w) >= 4 and w not in _COMPANY_STOPWORDS:
            out.add(w)
    return out


def pick_recent_company_file(reports, companies, primary_company=None):
    """Choose the company file this block was working in, or None.

    `reports`  — ctx.qb_report dicts from the block's events.
    `companies`— company names seen in ANY of the block's titles.

    Two routes, strongest first:
      1. A mechanism read the path outright ('exact') — believe it.
      2. Otherwise the freshest company file whose name matches a company seen
         in the block. Matching first, freshness second: a colleague's file may
         well be fresher, but it will not carry this block's company name.

    With no company name anywhere in the block, the freshest file is accepted
    only if it leads every other candidate decisively — otherwise abstain,
    because on a shared drive "most recent" alone is somebody's work, not
    necessarily this person's.
    """
    for r in reports:
        if isinstance(r, dict) and r.get('exact'):
            for path in r['exact']:
                if path:
                    return path, 'exact'

    # 1b. The user PICKED this file in a shell Open dialog (agent: 'picked',
    # read from the current user's ComDlg32 MRU — the one mechanism elevation
    # cannot block). Not believed outright the way 'exact' is: the MRU records
    # the last file CHOSEN, which goes stale when someone switches company
    # through the Open Previous Company menu instead of a dialog.
    #
    # So it must agree with the block about WHO this is. The title carries the
    # generic company name ("St. Mary's Church"); the filename carries the
    # specific one ("st._marys_minoa.qbw"). Requiring them to share an
    # identifying word means the MRU only ever decides WHICH St. Mary's — never
    # that a St. Patrick's file belongs to a St. Mary's block. With no company
    # name anywhere in the block there is nothing to agree with, so abstain.
    picked = [p for r in reports if isinstance(r, dict) for p in (r.get('picked') or []) if p]
    if picked:
        # Corroborate against the ACTIVE title's company, not every company the
        # block ever saw. A block whose window title read "Sacred Heart" was
        # given Divine Mercy Parish because a Divine Mercy window existed
        # somewhere in the same block: the user had picked that file earlier,
        # then switched company through the Open Previous menu, which leaves
        # the MRU pointing at the old one. Checking the whole set made the
        # staleness invisible — the picked file agreed with SOMETHING, just not
        # with what was on screen.
        #
        # With no company on the active title (a modal like "Print Checks"),
        # fall back to the block's wider set, but only when it names exactly
        # ONE company: two different companies in a block means we cannot tell
        # which the MRU is supposed to agree with.
        if primary_company:
            target = {primary_company}
        elif len(companies or ()) == 1:
            target = set(companies)
        else:
            target = set()
        company_words = set()
        for name in target:
            company_words |= _identifying_words(name)
        target_class = set()
        for name in target:
            target_class |= _entity_class(name)
        if company_words:
            for path in picked:
                stem = clean_stem(path)
                if not (_identifying_words(stem) & company_words):
                    continue
                # Sharing a saint's name is not agreement. "St. Mary - St.
                # Peter's Church" and "St. Mary's Cemetery Bville" overlap on
                # "mary" and nothing else, and they are two different clients
                # with two different sets of books.
                file_class = _entity_class(stem)
                if target_class and file_class and not (target_class & file_class):
                    continue
                return path, 'picked'

    # Freshest observation wins per file: the same file appears in every event's
    # report, ageing as the block runs.
    best_age = {}
    for r in reports:
        if not isinstance(r, dict):
            continue
        for item in (r.get('recent') or []):
            try:
                name, age = item.get('f'), int(item.get('age'))
            except Exception:
                continue
            if not name or age < 0:
                continue
            if name not in best_age or age < best_age[name]:
                best_age[name] = age

    fresh = sorted(((a, n) for n, a in best_age.items() if a <= RECENT_MAX_AGE_SECONDS))
    if not fresh:
        # Nothing recent. If the freshest thing on the whole share is ancient,
        # say so distinctly — that is "this share has no timing signal", not
        # "this block had no activity", and the two want different responses.
        if best_age and min(best_age.values()) > SIGNAL_MAX_AGE_SECONDS:
            return None, 'stale_share'
        return None, 'none'

    cnorms = [norm(c) for c in (companies or []) if len(norm(c)) >= 4]
    if cnorms:
        for age, name in fresh:
            fnorm = norm(clean_stem(name))
            if any(cn in fnorm for cn in cnorms):
                return name, 'named'
        return None, 'no_name_match'

    # No company name anywhere in the block — accept only a decisive lead.
    if len(fresh) == 1 or (fresh[1][0] - fresh[0][0]) >= RECENT_LEAD_SECONDS:
        return fresh[0][1], 'lead'
    return None, 'ambiguous'
