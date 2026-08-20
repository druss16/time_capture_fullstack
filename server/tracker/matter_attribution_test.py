"""
Tests for matter attribution — deciding which matter captured work belongs to.

This is billing-critical in a way client attribution is not. Sending an hour to
the wrong matter bills the wrong client, and in a regulated profession that is
worse than an accounting mis-post. Every case below is really asking the same
question: does this abstain when it should?

The specific hazards, all learned the hard way on the client side:
  - a token shared by two matters must identify NEITHER (Sacred Heart)
  - a short or year-like number must never match on its own ("Smith 2024.pdf"
    is a tax year, not matter 2024)
  - text naming two matters is evidence of neither

Needs Django importable; if unavailable, cases are SKIPPED.

    python manage.py shell -c "import tracker.matter_attribution_test"
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_passed = _failed = _skipped = 0


def check(label, cond):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {label}")
    else:
        _failed += 1
        print(f"  FAIL  {label}")


try:
    from tracker.services.matter_attribution import (
        candidate_tokens, build_matter_index, match_matter_in_text, attribute_block,
    )
    _ok = True
except Exception as e:
    _ok = False
    _skipped = 1
    print("Matter attribution:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")


class _M:
    def __init__(self, project_id, display_number, status='open'):
        self.project_id = project_id
        self.display_number = display_number
        self.external_status = status


class _B:
    def __init__(self, file_path='', title='', window_title='', url='',
                 client_id=None, hints=None):
        self.file_path, self.title = file_path, title
        self.window_title, self.url, self.client_id = window_title, url, client_id
        self.hints = hints or {}


if _ok:
    print("Matter attribution — tokens drawn from a Clio matter number:")
    t = candidate_tokens('00123-Smith')
    check("leading number is usable alone", '00123' in t)
    check("full number kept as a phrase", '00123 smith' in t)
    check("bare year rejected — 'Smith 2024.pdf' is a tax year",
          candidate_tokens('2024-Smith') == {'2024 smith'})
    check("short number rejected on its own",
          all(len(x) >= 4 or ' ' in x for x in candidate_tokens('12-Smith')))
    check("empty number yields nothing", candidate_tokens('') == set())

    print("Matter attribution — a token two matters share identifies neither:")
    idx = build_matter_index([_M(1, '00123-Smith'), _M(2, '00123-Jones')])
    check("shared leading number dropped", '00123' not in idx)
    check("but each full number survives", '00123 smith' in idx and '00123 jones' in idx)

    idx2 = build_matter_index([_M(1, '00123-Smith'), _M(2, '00456-Jones')])
    check("distinct numbers both usable", idx2.get('00123') == {1} and idx2.get('00456') == {2})

    print("Matter attribution — matching real filenames:")
    check("matches a matter number in a filename",
          match_matter_in_text(r'S:\Clients\Smith\00123 Estate\motion.docx', idx2) == 1)
    check("matches inside a Word window title",
          match_matter_in_text('00456 Jones - Response.docx - Word', idx2) == 2)
    check("no number, no match",
          match_matter_in_text('random notes.docx', idx2) is None)
    check("ABSTAINS when two matters are named",
          match_matter_in_text('00123 and 00456 comparison.xlsx', idx2) is None)
    check("does not match a number embedded in a longer one",
          match_matter_in_text('invoice 004561234.pdf', idx2) is None)
    check("empty text is safe", match_matter_in_text('', idx2) is None)
    check("empty index is safe", match_matter_in_text('00123 Estate.docx', {}) is None)

    print("Matter attribution — a year in a filename must not win:")
    year_idx = build_matter_index([_M(9, '2024-Smith')])
    check("'Smith 2024 return.pdf' does not match matter 2024-Smith",
          match_matter_in_text('Smith 2024 return.pdf', year_idx) is None)
    check("but the full number still matches",
          match_matter_in_text('2024-Smith engagement.docx', year_idx) == 9)

    print("Matter attribution — tier order and the sole-matter fallback:")
    sole = {77: 5}
    check("explicit number beats the sole-matter inference",
          attribute_block(_B(file_path='00123 Estate.docx', client_id=77), idx2, sole)[:2] == (1, 'number'))
    check("falls back to the client's only matter",
          attribute_block(_B(title='notes.docx', client_id=77), idx2, sole)[:2] == (5, 'sole_matter'))
    check("client with several matters abstains",
          attribute_block(_B(title='notes.docx', client_id=88), idx2, sole)[0] is None)
    check("no client and no number abstains",
          attribute_block(_B(title='notes.docx'), idx2, sole)[0] is None)
    check("url is searched too",
          attribute_block(_B(url='https://portal/00456/doc', client_id=None), idx2, sole)[:2] == (2, 'number'))

    print("Matter attribution — the Clio anchor outranks every heuristic:")
    anchors = {'1925394507': 63, '1925394508': 64}
    check("anchor alone attributes",
          attribute_block(_B(hints={'clio_matter_id': '1925394507'}), idx2, sole, anchors)[:2]
          == (63, 'clio_anchor'))
    check("anchor BEATS a conflicting matter number in the filename",
          attribute_block(_B(file_path='00123 Estate.docx',
                             hints={'clio_matter_id': '1925394508'}), idx2, sole, anchors)[0] == 64)
    check("anchor beats the sole-matter inference",
          attribute_block(_B(title='notes.docx', client_id=77,
                             hints={'clio_matter_id': '1925394507'}), idx2, sole, anchors)[0] == 63)
    check("unknown matter id falls through, never invents a project",
          attribute_block(_B(file_path='00123 Estate.docx',
                             hints={'clio_matter_id': '999999'}), idx2, sole, anchors)[:2]
          == (1, 'number'))
    check("no anchor map (org never synced Clio) is safe",
          attribute_block(_B(hints={'clio_matter_id': '1925394507'}), idx2, sole, None)[0] is None)
    check("blank hints are safe", attribute_block(_B(hints={}), idx2, sole, anchors)[0] is None)
    check("numeric-typed id still matches its string key",
          attribute_block(_B(hints={'clio_matter_id': 1925394507}), idx2, sole, anchors)[0] == 63)

print(f"\n{_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
