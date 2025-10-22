import re, fnmatch

def apply_rules(block, rules):
    """Return list of (field, value_text, confidence)."""
    hay = " ".join([block.title or "", block.url or "", block.file_path or ""]).lower()
    out = []
    for r in rules:
        pat = r.pattern.lower()
        hit = (
            (r.kind=="contains" and pat in hay) or
            (r.kind=="regex" and re.search(r.pattern, hay, re.I)) or
            (r.kind=="glob" and (fnmatch.fnmatch(block.url or "", r.pattern) or fnmatch.fnmatch(block.file_path or "", r.pattern)))
        )
        if hit and r.active:
            out.append((r.field, r.value_text, 0.85))  # base confidence for rules
    return out
