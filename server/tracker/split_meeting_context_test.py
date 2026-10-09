"""
Regression tests for "Mixes N clients" on a meeting, and for the per-slice
`source` that lets the Daily Review row say WHY each chip is there.

The bug it guards: a 21-minute Google Meet ("Meet - Weekly SE | MTC - Alannah
(morethancars.com)") showed in Needs You as "Mixes 3 clients: More Than Cars
Creative, Direct Exteriors, 5E Pump & Well". The row only shows the block's
main title, so nothing on it said where the other two came from: other
clients' Google Sheets that were in front for a minute or two during the call.
A meeting is one conversation; what was glanced at during it is not separate
work.

  - _is_meeting_block knows Chrome's "Meet - <event>" tab title, which the
    shared platform list (google meet / meet.google.com) does not.
  - _slice_suggestions tags each slice "named" (its own title names the
    client) or "booked" (nothing named anyone; it stays with the block).

Pure functions, no database:
    docker exec time_api python manage.py shell -c "import tracker.split_meeting_context_test"
"""
import sys
from types import SimpleNamespace

from tracker.utils.client_name_match import build_token_index
from tracker.views_block_evidence import _is_meeting_block, _slice_suggestions

FAILURES = []


def check(label, cond):
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}")
        FAILURES.append(label)


def block(title, app="Google Chrome", url="", is_meeting=False, client_id=None, client_name=None):
    return SimpleNamespace(
        window_title=title, app_name=app, url=url, is_meeting=is_meeting,
        client_id=client_id,
        client=SimpleNamespace(name=client_name) if client_name else None,
    )


print("\n1. Meeting detection")
check("Chrome 'Meet - Weekly SE | MTC ...' tab is a meeting",
      _is_meeting_block(block("Meet - Weekly SE | MTC - Alannah (morethancars.com)")))
check("'Meet – abc-defg-hij' (en dash) is a meeting",
      _is_meeting_block(block("Meet – abc-defg-hij")))
check("is_meeting flag set by the agent counts",
      _is_meeting_block(block("Loading Microsoft Teams", app="Teams", is_meeting=True)))
check("meet.google.com URL counts",
      _is_meeting_block(block("Weekly sync", url="https://meet.google.com/abc-defg-hij")))
check("'Meeting notes - Google Docs' is NOT a meeting",
      not _is_meeting_block(block("Meeting notes - Google Docs")))
check("'Meetup venue list - Google Sheets' is NOT a meeting",
      not _is_meeting_block(block("Meetup venue list - Google Sheets")))
check("a client's Google Sheet is NOT a meeting",
      not _is_meeting_block(block("Direct Exteriors - Creative Specs - Google Sheets")))


print("\n2. Slice sources")
NAMES = {
    10: "More Than Cars Creative",
    11: "Direct Exteriors",
    12: "5E Pump & Well",
}
INDEX = build_token_index(NAMES)
ORG = SimpleNamespace(name="Agency Co")
bd = [
    {"label": "Meet - Weekly SE", "minutes": 15},
    {"label": "Direct Exteriors - Creative Specs - Google Sheets", "minutes": 4},
    {"label": "My timesheet", "minutes": 1},
]
sug = _slice_suggestions(block("Meet - Weekly SE", client_id=10, client_name=NAMES[10]),
                         ORG, breakdown=bd, names=NAMES, index=INDEX)
check("slice naming nobody stays with the booked client, source=booked",
      sug["Meet - Weekly SE"]["client_id"] == 10 and sug["Meet - Weekly SE"]["source"] == "booked")
check("slice whose title names a client, source=named",
      sug[bd[1]["label"]]["client_id"] == 11 and sug[bd[1]["label"]]["source"] == "named")
check("own-admin slice, source=timesheet",
      sug["My timesheet"]["client_id"] is None and sug["My timesheet"]["source"] == "timesheet")


if FAILURES:
    print(f"\n{len(FAILURES)} FAILED")
    sys.exit(1)
print("\nall passed")
