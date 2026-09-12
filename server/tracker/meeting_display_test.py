"""
Tests for how a bracketed meeting is named and explained.

A meeting block is the one kind whose window title is reliably worthless: the
agent's detector fires the instant the conferencing app appears, which is while
it is still painting its splash, so the title it keeps says "Loading Microsoft
Teams". Seven of org 21's thirteen meeting blocks in a month said exactly that,
and the Daily Review row announced it as though it were the work.

The negative cases carry the weight. A Teams CHAT window is ordinary work and
must keep its own title, and a meeting title that DID survive the splash is
better than any label we could invent.

    python manage.py shell -c "import tracker.meeting_display_test"

Exits non-zero if any assertion fails.
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
    from tracker.utils.display_formatter import (
        _meeting_display_title, format_block_for_display)
    _ok = True
except Exception as e:
    _ok = False
    _skipped = 1
    print(f"  SKIP  app deps unavailable ({type(e).__name__})")

if _ok:
    T = _meeting_display_title

    print("Naming a meeting — the splash screen is not the work:")
    check("the real block: 'Loading Microsoft Teams' -> 'Teams meeting'",
          T('Teams Meeting', 'Loading Microsoft Teams') == 'Teams meeting')
    check("a bare app name is no better",
          T('Teams Meeting', 'Microsoft Teams') == 'Teams meeting')
    check("an empty title still names the platform",
          T('Teams Meeting', '') == 'Teams meeting')
    check("'Connecting…' is a splash too",
          T('Zoom Meeting', 'Connecting to Zoom') == 'Zoom meeting')
    check("an unknown platform still says it was a meeting",
          T('Meeting', 'Loading') == 'Meeting')

    print("\nNaming a meeting — a real title beats any label we invent:")
    check("a surviving subject is kept",
          T('Teams Meeting', 'Q3 review | Microsoft Teams')
          == 'Teams meeting: Q3 review')
    check("the platform chrome is trimmed off it",
          'Microsoft Teams' not in T('Teams Meeting', 'Q3 review | Microsoft Teams'))
    check("a participant name survives",
          T('Teams Meeting', 'Meeting with Kim Barnes | Microsoft Teams')
          == 'Teams meeting: Meeting with Kim Barnes')

    print("\nNaming a meeting — a title that only describes the window:")
    check("browser chrome is stripped, then the room code is rejected",
          T('Meeting', 'Meet - oak-tjkn-ryx and 1 more page - Work - Microsoft Edge')
          == 'Meeting')
    check("'In lobby · Meeting · Webex' says nothing about the meeting",
          T('Meeting', 'In lobby \u00b7 Meeting \u00b7 Webex and 3 more pages - Work - Microsoft Edge')
          == 'Webex meeting')
    check("'Chat' and the platform stamp drop; the person survives",
          T('Teams Meeting', 'Chat | Stephen Dubois (You) | Microsoft Teams')
          == 'Teams meeting: Stephen Dubois (You)')
    check("a real subject inside browser chrome still survives",
          T('Meeting', 'Parish budget review and 1 more page - Work - Microsoft Edge')
          == 'Meeting: Parish budget review')

    print("\nNaming a meeting — what must NOT be renamed:")
    check("a Teams CHAT window is ordinary work, not a meeting",
          T('Teams', 'Chat | Stephen Dubois (You) | Microsoft Teams') == '')
    check("QuickBooks is untouched",
          T('qbw.exe', "St. Mary's Church - QuickBooks") == '')
    check("a browser tab that merely says 'meeting' is untouched",
          T('msedge', 'How to run a better meeting - Edge') == '')

    print("\nThe formatter returns the meeting name as both title and app:")
    out = format_block_for_display({
        'app_name': 'Teams Meeting',
        'window_title': 'Loading Microsoft Teams',
        'minutes': 71,
    })
    check("title is the meeting, not the splash", out['title'] == 'Teams meeting')
    check("app agrees with it", out['app'] == 'Teams meeting')
    check("duration still formats", bool(out['duration']))

print(f"\n{_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
