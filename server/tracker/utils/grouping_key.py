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


# Folder names that hold one sub-folder per client. The segment immediately
# BELOW one of these is the client-level folder — a stable, per-client boundary
# that (unlike a filename keyword) is identical for every one of that client's
# documents and differs between clients. Lowercased exact-segment match.
# Extend per-org if a firm uses a different clients-root name.
_CLIENT_ROOT_FOLDERS = (
    "client file notes",
    "clients",
    "client files",
    "client docs",
)


# A Dropbox ROOT, where a firm keeps one top-level folder per client
# (a marketing agency: Dropbox/<Client>/<Project>/file.psd). Recognised only in
# the shapes Dropbox actually installs as — never any segment that merely
# contains "dropbox":
#
#   macOS File Provider  ~/Library/CloudStorage/Dropbox/<Client>
#                        ~/Library/CloudStorage/Dropbox-<Team Name>/<Client>
#   legacy macOS/Linux   ~/Dropbox/<Client>,  ~/Dropbox (<Team Name>)/<Client>
#   Windows              C:\Users\<x>\Dropbox\<Client>  (and "Dropbox (<Team>)")
#
# i.e. the segment sits directly in CloudStorage, or directly in a home folder.
_DROPBOX_NAME_RE = re.compile(r"^dropbox(?:\s*\([^)]*\))?$")
_DROPBOX_CLOUDSTORAGE_RE = re.compile(r"^dropbox(?:-.+|\s*\([^)]*\))?$")
_HOME_PARENTS = ("users", "home")


def _dropbox_root_index(low):
    """Index of the Dropbox root segment in a lowercased path, or None."""
    for i, s in enumerate(low):
        if i >= 1 and low[i - 1] == "cloudstorage" and _DROPBOX_CLOUDSTORAGE_RE.match(s):
            return i
        if i >= 2 and low[i - 2] in _HOME_PARENTS and _DROPBOX_NAME_RE.match(s):
            return i
    return None


# The user's own Desktop / Documents, the last-resort anchor. A small agency or
# a solo bookkeeper keeps ~/Desktop/<Client>/<Project>/file.psd with no
# "Clients" folder and no Dropbox, and without an anchor every one of those
# files fell into the single coarse "docs" bucket — so ten seconds on
# Desktop/Dauphin & Fantacone/D&F_trois.psd and the next three minutes on
# Desktop/Nike/Spring Launch/Nike_test.psd became ONE Photoshop block, booked
# to Dauphin & Fantacone.
#
# Recognised only where the OS puts these folders: directly in a home folder
# (/Users/<x>/Desktop, C:\Users\<x>\Documents, /home/<x>/Desktop), or directly
# in a OneDrive root that backs them up (C:\Users\<x>\OneDrive - Firm\Desktop,
# ~/Library/CloudStorage/OneDrive-Firm/Documents). Downloads is left out: what
# lands there is whatever a browser named it, not a folder the user filed.
_HOME_WORK_FOLDERS = ("desktop", "documents")
_ONEDRIVE_HOME_RE = re.compile(r"^onedrive(?:\s*-\s*.+)?$")
_ONEDRIVE_CLOUDSTORAGE_RE = re.compile(r"^onedrive(?:-.+)?$")


def _home_work_folder_index(low):
    """Index of a home-level Desktop/Documents segment in a lowercased path, or None."""
    for i, s in enumerate(low):
        if s not in _HOME_WORK_FOLDERS or i < 2:
            continue
        if low[i - 2] in _HOME_PARENTS:
            return i
        parent = low[i - 1]
        if i >= 3 and low[i - 3] in _HOME_PARENTS and _ONEDRIVE_HOME_RE.match(parent):
            return i
        if low[i - 2] == "cloudstorage" and _ONEDRIVE_CLOUDSTORAGE_RE.match(parent):
            return i
    return None


def client_folder_bucket(file_path: str, roots=_CLIENT_ROOT_FOLDERS) -> str:
    """Return the client-level folder segment from a path, or '' if none.

    The path structure that matters here is ``...\\<clients-root>\\<Client>\\...``
    (org 21: ``...\\Company Data\\Client File Notes\\Divine Mercy\\...``). The
    ``<Client>`` folder is the client boundary: every one of that client's docs
    shares it, and two different clients never do. Keying a doc block on this
    folder is what stops one Excel session that touched two clients' files from
    collapsing into a single mixed block (block 54393: Divine Mercy + Our Lady
    of Hope files merged under one ``docs`` bucket).

    A named clients-root anywhere in the path wins. Only when there is none is
    a Dropbox ROOT used as the anchor, so ``Dropbox/Firm/Clients/Acme/...`` is
    still ``acme``, and org 21's paths are unchanged. Only when there is no
    Dropbox root either is the user's home-level Desktop / Documents used
    (``~/Desktop/Nike/Spring Launch/x.psd`` -> ``nike``). Under a Dropbox or
    home-folder anchor the segment below must be a FOLDER — a file saved
    straight onto the Desktop names no client.

    GROUPING ONLY. The one caller is compaction._grouping_content_id, which
    uses this to split "docs" blocks at a folder boundary. It never picks a
    client. A top-level non-client Dropbox folder (Apps, Templates, Internal)
    just gets its own block.

    Returns '' when the path has no recognized root (e.g. a file saved straight
    into ``C:\\Users\\<name>\\OneDrive - Firm\\Documents``) — the caller then
    keeps the existing coarse ``docs`` bucket, so those paths are unaffected.
    """
    if not file_path:
        return ""
    segs = [s for s in re.split(r"[\\/]+", file_path) if s]
    low = [s.strip().lower() for s in segs]
    anchor_idx = None
    for i, s in enumerate(low):
        if s in roots:
            anchor_idx = i
            break
    if anchor_idx is None:
        anchor_idx = _dropbox_root_index(low)
        if anchor_idx is None:
            anchor_idx = _home_work_folder_index(low)
        # Dropbox/<file>, Desktop/<file> — the next segment must be a folder,
        # not the file.
        if anchor_idx is not None and anchor_idx + 2 >= len(low):
            return ""
    if anchor_idx is None or anchor_idx + 1 >= len(low):
        return ""
    folder = re.sub(r"\s+", " ", low[anchor_idx + 1]).strip()
    # A one/two-char segment is not a real client folder — keep coarse.
    if len(folder) < 3:
        return ""
    return folder


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