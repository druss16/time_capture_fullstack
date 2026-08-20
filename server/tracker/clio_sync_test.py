"""
Tests for Clio sync's pure record-shaping helpers.

These three functions decide what actually lands in the database, and each
has a failure mode that is silent or destructive:

1. `_pick` — Clio field names are verified against docs but not yet against a
   live account. `_pick` degrades an unexpected key to a blank value instead
   of raising, so a rename costs a field, not the whole sync.

2. `_contact_display_name` — Clio companies carry `name`; people may carry
   only `first_name`/`last_name`. Falling back wrongly produces Clients named
   "None None".

3. `_matter_project_name` — THE important one. Project is unique on
   (org, client, name), and two matters for one client routinely share a
   description ("Estate Planning"). Leading with Clio's firm-unique display
   number is what stops the second matter raising IntegrityError mid-sync.

Needs Django importable; if unavailable (bare python), cases are SKIPPED.

    python manage.py shell -c "import tracker.clio_sync_test"
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
    from tracker.integrations.clio.sync import (
        _pick,
        _contact_display_name,
        _matter_project_name,
    )
    _ok = True
except Exception as e:
    _ok = False
    _skipped = 1
    print("Clio sync helpers:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")

if _ok:
    print("Clio sync — _pick tolerates field drift:")
    check("returns first present key", _pick({'a': 'x', 'b': 'y'}, 'a', 'b') == 'x')
    check("falls through to the second key", _pick({'b': 'y'}, 'a', 'b') == 'y')
    check("skips empty string", _pick({'a': '', 'b': 'y'}, 'a', 'b') == 'y')
    check("skips None", _pick({'a': None, 'b': 'y'}, 'a', 'b') == 'y')
    check("skips empty list", _pick({'a': [], 'b': 'y'}, 'a', 'b') == 'y')
    check("all missing -> default", _pick({}, 'a', 'b') == '')
    check("custom default honoured", _pick({}, 'a', default='fallback') == 'fallback')
    check("zero is NOT treated as missing", _pick({'a': 0}, 'a', default='x') == 0)
    check("False is NOT treated as missing", _pick({'a': False}, 'a', default='x') is False)

    print("Clio sync — contact naming:")
    check("company uses name",
          _contact_display_name({'name': 'Acme Holdings LLC'}) == 'Acme Holdings LLC')
    check("person falls back to first+last",
          _contact_display_name({'first_name': 'Ada', 'last_name': 'Byron'}) == 'Ada Byron')
    check("name wins over first/last",
          _contact_display_name(
              {'name': 'Acme', 'first_name': 'Ada', 'last_name': 'Byron'}) == 'Acme')
    check("first name only",
          _contact_display_name({'first_name': 'Ada'}) == 'Ada')
    check("last name only",
          _contact_display_name({'last_name': 'Byron'}) == 'Byron')
    check("no name parts -> empty, never 'None None'",
          _contact_display_name({'id': 7}) == '')
    check("truncates to Client.name max_length",
          len(_contact_display_name({'name': 'z' * 400})) == 255)

    print("Clio sync — matter names avoid the (org, client, name) collision:")
    a = _matter_project_name(
        {'id': 1, 'display_number': '00123-Smith', 'description': 'Estate Planning'})
    b = _matter_project_name(
        {'id': 2, 'display_number': '00124-Smith', 'description': 'Estate Planning'})
    check("same description, different matter -> different names", a != b)
    check("readable: number then description", a == '00123-Smith — Estate Planning')
    check("description only still works",
          _matter_project_name({'id': 3, 'description': 'Estate Planning'}) == 'Estate Planning')
    check("number only still works",
          _matter_project_name({'id': 4, 'display_number': '00125'}) == '00125')
    check("neither -> falls back to the matter id, never blank",
          _matter_project_name({'id': 9}) == 'Matter 9')
    check("truncates to Project.name max_length",
          len(_matter_project_name(
              {'id': 5, 'display_number': '1', 'description': 'q' * 400})) == 200)
    check("whitespace-only description ignored",
          _matter_project_name({'id': 6, 'display_number': '00126', 'description': '   '})
          == '00126')

print(f"\n{_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
