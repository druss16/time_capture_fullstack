"""pdf_identity.py — recover a client name from a PDF's document-properties
metadata (Title / Subject / Author) ONLY. Never reads page text.

Why: report PDFs (QuickBooks reconciliations, payroll registers) are saved with
system-export filenames that name no client — but their /Info metadata often
carries the company, e.g. /Title "St Mary's - Reconciliation". Reading just those
few metadata fields is low-sensitivity (document properties, not the financial
body) and frequently enough to attribute the client.

Dependency-free on purpose — adds nothing to the PyInstaller bundle. It parses
the /Info dictionary out of the raw bytes; for encrypted or object-stream-
compressed metadata it simply returns {} (graceful, never raises).
"""
import re

# Cap the read — metadata lives near the file head/tail; never slurp a huge PDF.
_MAX_BYTES = 3_000_000
_MAX_FIELD_LEN = 200  # a Title is a label, not a document

_FIELD_MARKERS = {'title': b'/Title', 'subject': b'/Subject', 'author': b'/Author'}


def _extract_string_after(data: bytes, marker: bytes):
    """Find `marker` then parse the PDF string that follows it — a balanced
    literal `(...)` (honoring \\( \\) \\\\ escapes and nested parens) or a hex
    `<...>` string. Returns the raw string token (with delimiters) or None."""
    idx = data.find(marker)
    if idx < 0:
        return None
    i = idx + len(marker)
    while i < len(data) and data[i:i + 1].isspace():
        i += 1
    if i >= len(data):
        return None
    ch = data[i]
    if ch == 0x28:  # (  — balanced literal
        depth = 0
        j = i
        buf = bytearray()
        while j < len(data):
            c = data[j]
            if c == 0x5c:  # backslash: keep both chars, decode later
                buf.append(c)
                if j + 1 < len(data):
                    buf.append(data[j + 1])
                j += 2
                continue
            if c == 0x28:
                depth += 1
                if depth > 1:
                    buf.append(c)
                j += 1
                continue
            if c == 0x29:
                depth -= 1
                if depth == 0:
                    return b'(' + bytes(buf) + b')'
                buf.append(c)
                j += 1
                continue
            buf.append(c)
            j += 1
        return None
    if ch == 0x3c:  # <  — hex string
        end = data.find(b'>', i)
        return data[i:end + 1] if end > i else None
    return None

_OCTAL = re.compile(rb'[0-7]{1,3}')
_ESCAPES = {0x6e: 0x0a, 0x72: 0x0d, 0x74: 0x09, 0x62: 0x08,
            0x66: 0x0c, 0x28: 0x28, 0x29: 0x29, 0x5c: 0x5c}


def _unescape_literal(s: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(s):
        c = s[i]
        if c == 0x5c and i + 1 < len(s):  # backslash escape
            n = s[i + 1]
            if n in _ESCAPES:
                out.append(_ESCAPES[n]); i += 2; continue
            if 0x30 <= n <= 0x37:  # \ddd octal
                mo = _OCTAL.match(s, i + 1)
                out.append(int(mo.group(0), 8) & 0xFF)
                i += 1 + len(mo.group(0)); continue
            i += 1; continue  # drop the backslash, keep next char next loop
        out.append(c); i += 1
    return bytes(out)


def _decode_pdf_string(raw: bytes) -> str:
    raw = raw.strip()
    if raw.startswith(b'<') and raw.endswith(b'>'):
        try:
            data = bytes.fromhex(re.sub(rb'\s+', b'', raw[1:-1]).decode('ascii'))
        except Exception:
            return ''
    elif raw.startswith(b'(') and raw.endswith(b')'):
        data = _unescape_literal(raw[1:-1])
    else:
        return ''
    if data[:2] in (b'\xfe\xff', b'\xff\xfe'):          # UTF-16 with BOM
        try: return data.decode('utf-16').strip()
        except Exception: return ''
    for enc in ('utf-8', 'latin-1'):
        try: return data.decode(enc).strip()
        except Exception: continue
    return ''


def read_pdf_metadata(path: str) -> dict:
    """Return {'title','subject','author'} (only the present, sane ones), or {}.
    Never raises."""
    try:
        with open(path, 'rb') as f:
            data = f.read(_MAX_BYTES)
    except Exception:
        return {}
    if not data.startswith(b'%PDF'):
        return {}
    out = {}
    for key, marker in _FIELD_MARKERS.items():
        raw = _extract_string_after(data, marker)
        if not raw:
            continue
        val = _decode_pdf_string(raw)
        # Drop empties and anything too long to be a metadata label (defends
        # against a mis-parse swallowing body text).
        if val and 0 < len(val) <= _MAX_FIELD_LEN and val.isprintable():
            out[key] = val
    return out


def pdf_identity_hint(path: str) -> str:
    """One short string for the classifier haystack: the Title, plus Subject when
    it adds something. Empty when nothing usable was found."""
    meta = read_pdf_metadata(path)
    parts = []
    for k in ('title', 'subject'):
        v = meta.get(k)
        if v and v.lower() not in (p.lower() for p in parts):
            parts.append(v)
    return ' — '.join(parts).strip()
