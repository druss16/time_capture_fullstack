"""
Tests for how tool/personal detection tokens are matched against a block.

WHY THESE EXIST
---------------
Stage 9.6 matched a detection domain with `d in domain` and a keyword with
`kw in haystack`. The social-media bucket lists 'x.com', which is a substring of
'dropbox.com' — so every Dropbox web block was categorised Personal/Non-Billable
at 0.92. The same substring test sat in views_block_evidence._looks_personal.

Domains now match only as the host or a subdomain of it; a dotted keyword must
not be glued to a letter/digit/hyphen. Plain-word keywords are unchanged.

    python manage.py shell -c "import tracker.detection_token_boundary_test"
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_passed = _failed = 0


def check(label, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}")


from tracker.industry_categories import (  # noqa: E402  (pure module, no Django)
    INDUSTRY_TYPES, PERSONAL_SITE_DETECTION, detection_token_in,
    get_combined_tool_detection, host_matches,
)

print("Detection token boundaries:")

# ── The bug ───────────────────────────────────────────────────────────────
check("x.com is not a domain match for dropbox.com",
      not host_matches('www.dropbox.com', 'x.com'))
check("x.com is not a keyword match inside a Dropbox URL",
      not detection_token_in('x.com', 'https://www.dropbox.com/home/clients/acme'))

dropbox = 'acme brand assets - dropbox https://www.dropbox.com/home/clients/acme'
hits = [
    tok for grp in PERSONAL_SITE_DETECTION.values()
    for tok in list(grp.get('keywords', [])) + list(grp.get('domains', []))
    if detection_token_in(tok, dropbox)
]
check(f"no personal-site token fires on a Dropbox block (hit: {hits})", not hits)

check("x.com does not fire inside x.company.com",
      not detection_token_in('x.com', 'https://x.company.com/'))

# ── What must still match ─────────────────────────────────────────────────
check("x.com itself", host_matches('x.com', 'x.com'))
check("a subdomain of x.com", host_matches('mobile.x.com', 'x.com'))
check("x.com keyword in its own URL", detection_token_in('x.com', 'https://x.com/home'))
check("dotted keyword after a subdomain dot",
      detection_token_in('twitter.com', 'https://mobile.twitter.com/a'))
check("dotted keyword with a path", detection_token_in('linkedin.com/feed', 'https://www.linkedin.com/feed/'))
check("plain word keeps substring behaviour", detection_token_in('facebook', 'facebookads'))
check("empty inputs never match",
      not detection_token_in('', 'x') and not detection_token_in('x.com', '')
      and not host_matches('', 'x.com'))

# Every configured entry must still recognise itself, in every vertical.
misses = []
for key, _label in INDUSTRY_TYPES:
    for tool, spec in get_combined_tool_detection(key).items():
        for d in spec.get('domains', []):
            if d and '/' not in d and not host_matches(d, d):
                misses.append((key, tool, d))
        for kw in spec.get('keywords', []):
            if kw and not detection_token_in(kw, f"foo {kw.lower()} bar"):
                misses.append((key, tool, kw))
check(f"every configured domain/keyword still matches itself (misses: {misses[:5]})", not misses)

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
