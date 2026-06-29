"""
tracker/utils/grouping_key.py

Maps a fine-grained content_identity (one-per-document) to a COARSE grouping
key (one-per-activity-kind) for compaction. This is what prevents the
90-blocks-from-90-scans fragmentation while still splitting:
  - personal browsing away from work,
  - one client's QBO customer page from another's,
  - one parish's documents from another's (when the filename names the parish).

THE RULE
========
Group on activity KIND, split on CLIENT BOUNDARY only where the client is
actually visible. Fine identity (the exact filename) is kept as metadata on the
event, never as the grouping key.

Mapping:
  qbo:customer=<name>      -> KEEP FINE  ("qbo:customer=<name>")   client boundary
  paychex:company=<id>     -> KEEP FINE  ("paychex:company=<id>")  client boundary
  file=<parish-named>.pdf  -> "docs:<parish>"   group a parish's docs together
  file=skmbt_/ccf_/doc_    -> "scan-batch"      anonymous scans = one session block
  file=<other>.pdf/doc     -> "docs:<client?>"  by detected client else "docs"
  qbo:section=...          -> "qbo-work"         coarse QBO session
  pinnacle:...             -> "pinnacle-work"
  paychex:section=...      -> "paychex-work"
  web:<host>/...           -> "web:<host>"       host-level (not per-path)
  ''  (no identity)        -> fall back to content bucket (personal/work/unknown)

The caller combines this with the content bucket so personal still separates:
  group = grouping_key(identity) if identity else bucket
"""

from __future__ import annotations
import re

# Known parish / church / client name fragments that appear in PDF filenames.
# When a scanned/opened doc filename contains one of these, the doc groups
# under that client so multiple clients' docs in one session stay separate.
# Extend as new clients appear. Lowercased substring match on the filename.
_CLIENT_NAME_HINTS = (
    "st francis xavier", "st francis", "st mark", "st matthew", "st mary",
    "st marys", "st mary's", "st joseph", "st patrick", "st patrick taberg",
    "st pat", "st malachy", "st charles", "st ann", "st peter", "st paul",
    "st john", "john episcopal", "grace episcopal", "transfiguration",
    "sacred heart", "sh parish", "assumption", "all saints", "basilica",
    "st james", "all around auto", "upstate cerebral palsy", "empire winds",
    "central ny coin", "tung d nguyen", "vgg", "col ",
    "francis assisi", "st francis assisi",
)

# Scanner / generic numeric document prefixes — anonymous, no client in name.
_ANON_DOC_RE = re.compile(
    r"^(skmbt_|ccf\d|doc\d|\d{6,}|0056_|000000|20\d{6}|c:20\d|payrolldetail|"
    r"payrollliability|reconciliationreport)",
    re.IGNORECASE,
)


def _client_from_filename(fname: str) -> str:
    """Return a client bucket suffix if the filename names a known client."""
    fl = fname.lower()
    for hint in _CLIENT_NAME_HINTS:
        if hint in fl:
            # normalize the hint to a stable bucket token
            return hint.replace("'", "").replace(".", "").strip()
    return ""


def grouping_key(identity: str) -> str:
    """Map a fine content_identity to a coarse grouping key.

    Returns '' if identity is empty (caller falls back to the content bucket).
    """
    if not identity:
        return ""

    # Client-boundary identities: keep fine so different clients split.
    if identity.startswith("qbo:customer=") or identity.startswith("paychex:company="):
        return identity

    # File/document identities -> coarse.
    if identity.startswith("file="):
        fname = identity[len("file="):]
        client = _client_from_filename(fname)
        if client:
            return f"docs:{client}"
        if _ANON_DOC_RE.match(fname):
            return "scan-batch"
        # A named, non-client doc (e.g. "account spreadsheet.xlsx") — group all
        # such misc docs together rather than per-file.
        return "docs"

    # QBO section work (no customer) -> one coarse QBO block.
    if identity.startswith("qbo:"):
        return "qbo-work"

    if identity.startswith("pinnacle:"):
        return "pinnacle-work"

    if identity.startswith("paychex:"):
        return "paychex-work"

    # Known work host -> host-level (drop the path segment so a portal's many
    # pages group together instead of splitting per page).
    if identity.startswith("web:"):
        host = identity[len("web:"):].split("/")[0]
        return f"web:{host}"

    # Anything else -> use as-is (rare).
    return identity