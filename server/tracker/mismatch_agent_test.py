"""
Regression tests for the mismatch agent's DECISION, not its evidence-gathering.

Gathering is queries; deciding is the part that can quietly do damage. These
lock down the three rules the agent exists to never break:

  1. A window title on its own never moves a block. The title is what raised
     the flag — scoring it again is one opinion counted twice, not a second
     opinion. Every auto-apply needs a witness that does not read the title.

  2. Same-family pairs are never machine-resolved. 27% of org 21's booked time
     carries no distinguishing word at all; an agent that "resolves" St. Mary's
     Church vs St. Mary's Cemetery is picking, and a confident pick is worse
     than an honest queue.

  3. Evidence pointing back at the booked client stops the machine. It does not
     merely lower the score — it hands the row to a person. This is the browser
     chrome lesson in reverse: noise only had to LOOK like a second opinion to
     veto a right answer, and a genuine contradiction deserves at least that
     much weight.

Plus the shape that makes vetoes different from caveats: a person clicking
Approve is allowed to overrule thin evidence, and is not allowed to overrule
"this was already invoiced".

Pure module — no database, no Django settings. Run inside the app container or
bare:
    python tracker/mismatch_agent_test.py
Exits non-zero if any assertion fails.
"""
import importlib.util
import os
import sys
import types

# The module imports django.db / django.utils at import time for the APPLY
# path, which none of these tests touch. Stub just enough for the import to
# succeed so the decision logic can be exercised without a configured Django.
if 'django' not in sys.modules:
    for name, attrs in (
        ('django', {}),
        ('django.db', {'transaction': types.SimpleNamespace(atomic=None)}),
        ('django.utils', {}),
        ('django.utils.timezone', {'now': lambda: None}),
    ):
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
    sys.modules['django'].db = sys.modules['django.db']
    sys.modules['django'].utils = sys.modules['django.utils']
    sys.modules['django.utils'].timezone = sys.modules['django.utils.timezone']

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     'services', 'mismatch_agent.py')
_spec = importlib.util.spec_from_file_location('_mismatch_agent', _PATH)
ma = importlib.util.module_from_spec(_spec)
# Register before exec: @dataclass resolves annotations through
# sys.modules[cls.__module__], and a module that isn't there yet reads as None.
sys.modules['_mismatch_agent'] = ma
_spec.loader.exec_module(ma)

Signal = ma.Signal

NAMES = {
    1: "St. Mary's Church",
    2: "St. Mary's Cemetery",
    3: "Hamilton Brothers Excavating",
    4: "Cutting Edge Decks, Inc",
}


def name_of(cid):
    return NAMES.get(cid, '')


def no_vetoes(_target):
    return []


def decide(booked, signals, veto_fn=no_vetoes):
    return ma.draft_from_signals(block_id=1, org_id=21, booked_id=booked,
                                 signals=signals, name_of=name_of,
                                 veto_fn=veto_fn)


def title(cid, w=0.85):
    return Signal('title', cid, w, f'Title names {name_of(cid)}.', independent=False)


def file_path(cid, w=0.85):
    return Signal('file_path', cid, w, f"File sits in {name_of(cid)}'s path.",
                  independent=True)


def qb_file(cid):
    return Signal('qb_company_file', cid, 0.95,
                  f"Company file is {name_of(cid)}'s.", independent=True)


def neighbours(cid, w=0.70):
    return Signal('neighbours', cid, w, f'Booked either side to {name_of(cid)}.',
                  independent=True)


def precedent(cid, w=0.90):
    return Signal('human_precedent', cid, w,
                  f'A person filed this title to {name_of(cid)} before.',
                  independent=True)


def dismissal(cid, w=0.85):
    return Signal('prior_dismissal', cid, w,
                  f'Reviewed and called correct on {name_of(cid)}.',
                  independent=True)


FAILURES = []


def check(label, cond):
    if cond:
        print(f'  ok   {label}')
    else:
        print(f'  FAIL {label}')
        FAILURES.append(label)


print('\n1. A title on its own never moves a block')
d = decide(3, [title(1)])
check('verdict is reassign (the agent still says who it looks like)',
      d.verdict == ma.VERDICT_REASSIGN and d.target_client_id == 1)
check('but it does NOT auto-apply', d.auto is False)
check('and it says why in plain words',
      any('nothing independent' in c.lower() for c in d.caveats))
check('confidence stays under the bar', d.confidence < ma.AUTO_BAR)

print('\n2. Title + one independent witness clears the bar')
d = decide(3, [title(1), file_path(1)])
check('auto-applies', d.auto is True)
check('target is the corroborated client', d.target_client_id == 1)
check('no caveats left', not d.caveats)

d = decide(3, [title(1), qb_file(1)])
check('a QuickBooks company file is enough on its own', d.auto is True)

print('\n3. Same-family pairs are never machine-resolved')


def family_veto(target):
    if {1, 2} == {1, target} or {1, 2} == {2, target}:
        return ['Same-family names — nothing in the text separates them.']
    return []


d = decide(2, [title(1), file_path(1)], veto_fn=family_veto)
check('a hard veto stops the auto-apply however strong the evidence',
      d.auto is False)
check('the veto is recorded, not silently swallowed', len(d.vetoes) == 1)
check('confidence is still reported honestly (the evidence WAS strong)',
      d.confidence >= ma.AUTO_BAR)

print('\n4. Evidence pointing back at the booked client stops the machine')
d = decide(3, [title(1), file_path(1), neighbours(3)])
check('does not auto-apply even though the title side out-weighs it',
      d.auto is False)
check('the contradiction is spelled out',
      any('points back at' in c for c in d.caveats))

print('   …and when the booked side actually wins, the flag is the thing wrong')
d = decide(3, [title(1, w=0.55), qb_file(3), precedent(3)])
check('verdict flips to leave-it-alone', d.verdict == ma.VERDICT_CONFIRM)
check('no target client is proposed', d.target_client_id is None)
check('but it still will not close the flag by itself', d.auto is False)

print('\n5. Two rivals with independent backing = a person decides')
d = decide(3, [title(1), file_path(1), neighbours(4)])
check('contested evidence never auto-applies', d.auto is False)
check('and says so', any('more than one other client' in c.lower()
                         for c in d.caveats))

print('\n6. Vetoes and caveats are different kinds of stop')
d = decide(3, [title(1)])
check('thin evidence is a caveat, not a veto — a person may overrule it',
      not d.vetoes and bool(d.caveats))
d = decide(3, [title(1), file_path(1)],
           veto_fn=lambda t: ['Already invoiced.'])
check('already-invoiced is a veto — nobody overrules it through this path',
      bool(d.vetoes))

print('\n7. No evidence at all is an honest shrug, not a guess')
d = decide(3, [])
check('verdict is needs_human', d.verdict == ma.VERDICT_HUMAN)
check('nothing is proposed', d.target_client_id is None)
check('confidence is zero, not a hedged number', d.confidence == 0.0)

print('\n8. A single witness can never read as certainty')
check('one perfect independent signal still lands under 1.0',
      ma._score([qb_file(1)], []) < 0.75)
check('two agreeing witnesses clear the bar',
      ma._score([title(1), file_path(1)], []) >= ma.AUTO_BAR)
check('an equally weighted opponent drags it back under',
      ma._score([title(1), file_path(1)], [file_path(3)]) < ma.AUTO_BAR)

print('\n9. Closing a flag is ALWAYS a person\'s call')
# The asymmetry that matters: a wrong move is visible (an audit row, an hours
# change someone notices, a place in the random accuracy sample). A wrong
# close is invisible — the row just stops appearing, and the tab starts
# reporting a clean book it has not earned.
d = decide(3, [dismissal(3), file_path(3), precedent(3)])
check('verdict is leave-it-alone', d.verdict == ma.VERDICT_CONFIRM)
check('evidence is overwhelming', d.confidence > 0.85)
check('and it STILL does not close the flag unattended', d.auto is False)
check('it says whose call it is',
      any('person' in c.lower() for c in d.caveats))

print()
if FAILURES:
    print(f'{len(FAILURES)} FAILED:')
    for f in FAILURES:
        print(f'  - {f}')
    sys.exit(1)
print('all mismatch-agent decision tests passed')
