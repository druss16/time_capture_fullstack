"""
Tests for the Clio push decision — the arithmetic that prevents double-billing.

This is the highest-consequence logic in the integration. Getting it wrong does
not throw; it bills a law firm's client twice, or silently drops hours the firm
earned. Neither shows up as an error anywhere.

Clio time entries carry a date and a duration but NO start time, so overlap can
never be determined precisely. The only honest comparison is a per-(user,
matter, day) total, and push is therefore a delta rather than an append:

    delta = everything we captured  -  everything already in Clio

The property that makes this safe is CONVERGENCE: running push repeatedly must
drive Clio's total to our captured total and then stop, whatever order work and
manual entries arrive in. The scenarios below run push several times against a
simulated Clio to assert exactly that.

Needs Django importable; if unavailable (bare python), cases are SKIPPED.

    python manage.py shell -c "import tracker.clio_push_test"
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
    from tracker.integrations.clio.push import decide_entry, _note_for, MIN_PUSH_MINUTES
    _ok = True
except Exception as e:
    _ok = False
    _skipped = 1
    print("Clio push:")
    print(f"  SKIP  app deps unavailable ({type(e).__name__}) — run in the app container")


class _FakeBlock:
    def __init__(self, notes='', title='', minutes=0):
        self.notes, self.title, self.minutes = notes, title, minutes


if _ok:
    # ── The headline case ────────────────────────────────────────────────
    print("Clio push — nets against what Clio already holds:")
    check("captured 210m, Clio has 120m -> push 90m",
          decide_entry(210, 120) == ('push', 90, ''))
    check("captured 210m, Clio empty -> push all 210m",
          decide_entry(210, 0) == ('push', 210, ''))
    check("captured 120m, Clio already has 120m -> push nothing",
          decide_entry(120, 120)[0] == 'skip')
    check("Clio holds MORE than we captured -> push nothing, never negative",
          decide_entry(60, 200)[0] == 'skip')
    check("skip reason names the cause", decide_entry(120, 120)[2] == 'already_in_clio')

    print("Clio push — sub-minute deltas are rounding noise, not billable work:")
    check("delta below the floor is skipped",
          decide_entry(120 + MIN_PUSH_MINUTES - 1, 120)[0] == 'skip')
    check("delta at the floor is pushed",
          decide_entry(120 + MIN_PUSH_MINUTES, 120)[0] == 'push')

    # ── Convergence: the property that actually protects the client ──────
    print("Clio push — repeated runs converge and never double-bill:")

    def run_push(captured, clio_total):
        """One push cycle against a simulated Clio; returns its new total."""
        action, minutes, _ = decide_entry(captured, clio_total)
        return clio_total + minutes if action == 'push' else clio_total

    # Attorney logged 2h by hand; we captured 3.5h of the same day.
    clio = 120
    clio = run_push(210, clio)
    check("run 1: Clio reaches our captured total", clio == 210)
    clio = run_push(210, clio)
    check("run 2 with no new work: unchanged (idempotent)", clio == 210)
    clio = run_push(210, clio)
    check("run 3: still unchanged", clio == 210)

    # A further hour gets captured that day.
    clio = run_push(270, clio)
    check("new work later the same day tops up to 270m", clio == 270)

    # The attorney then logs 30m manually on top.
    clio += 30
    clio = run_push(270, clio)
    check("their manual entry is absorbed, not duplicated", clio == 300)
    check("and a further run adds nothing", run_push(270, clio) == 300)

    # Ten runs in a row must not drift.
    clio = 0
    for _ in range(10):
        clio = run_push(480, clio)
    check("ten consecutive runs total exactly what we captured", clio == 480)

    # ── Matter guards run BEFORE the arithmetic ──────────────────────────
    print("Clio push — matters that cannot take our time are refused first:")
    check("UTBMS matter skipped even with time to push",
          decide_entry(210, 0, requires_utbms=True) == ('skip', 210, 'requires_utbms'))
    check("flat-fee matter skipped",
          decide_entry(210, 0, billing_method='flat')[2] == 'not_hourly')
    check("contingency matter skipped",
          decide_entry(210, 0, billing_method='contingency')[2] == 'not_hourly')
    check("billing method is case-insensitive",
          decide_entry(210, 0, billing_method='Flat')[2] == 'not_hourly')
    check("hourly matter is pushed",
          decide_entry(210, 0, billing_method='hourly')[0] == 'push')
    check("closed matter skipped",
          decide_entry(210, 0, matter_status='Closed')[2] == 'matter_closed')
    check("open matter pushed", decide_entry(210, 0, matter_status='Open')[0] == 'push')
    check("pending matter pushed", decide_entry(210, 0, matter_status='Pending')[0] == 'push')
    check("unknown status is blank-tolerant (unsynced field)",
          decide_entry(210, 0, matter_status='')[0] == 'push')
    check("UTBMS outranks the already-in-Clio check",
          decide_entry(120, 120, requires_utbms=True)[2] == 'requires_utbms')

    # ── Notes ────────────────────────────────────────────────────────────
    print("Clio push — the note a client will read on their bill:")
    check("prefers notes over title",
          _note_for([_FakeBlock(notes='Drafted MSJ', title='Word')]) == 'Drafted MSJ')
    check("falls back to title",
          _note_for([_FakeBlock(title='Smith depo prep')]) == 'Smith depo prep')
    check("joins distinct entries",
          _note_for([_FakeBlock(notes='A'), _FakeBlock(notes='B')]) == 'A; B')
    check("de-duplicates case-insensitively",
          _note_for([_FakeBlock(notes='Research'), _FakeBlock(notes='research')]) == 'Research')
    check("never empty — a blank note on a bill is worse than a generic one",
          _note_for([_FakeBlock()]) == 'Captured by TimeTracker')
    check("truncated to a sane length",
          len(_note_for([_FakeBlock(notes='x' * 900)])) == 500)

print(f"\n{_passed} passed, {_failed} failed, {_skipped} skipped")
sys.exit(1 if _failed else 0)
