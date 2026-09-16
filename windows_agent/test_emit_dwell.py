"""
_emit_current_dwell — unobserved-gap guard test
================================================
Runs the REAL function body out of main.py rather than a re-implementation:
the source text between `def _emit_current_dwell` and `def _start_new_dwell` is
extracted, wrapped in a harness that supplies the closure variables, and
executed with stubs for write_event / log / report_error_to_backend. If someone
edits the function, this tests the edit.

main.py cannot be imported on a non-Windows host (win32 imports at module
scope), and the function is a closure inside run_agent(), so extraction is the
only way to reach it. That is the point: no simulation, no second copy of the
logic to drift.

    python windows_agent/test_emit_dwell.py

Covers: the real 2026-09-16 overnight stall, no re-emission on the following
heartbeat, hostile mouse_idle_pause_seconds values (that field has no
server-side validators and a 0 would otherwise write zero events), normal work
losing nothing, IDLE dwells keeping their full span, and the guard clauses.
"""
import io, os, textwrap, sys

_MAIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")

src = io.open(_MAIN, encoding='utf-8').read()
start = src.index('            def _emit_current_dwell(end_ts: float):')
end = src.index('            def _start_new_dwell(sig, start_ts: float):')
body = textwrap.dedent(src[start:end]).rstrip()
print("extracted %d lines of REAL source" % len(body.splitlines()))
assert 'grace_s = max(' in body, "floor missing from extracted source!"
assert 'last_emit_ts = real_end' in body

MAX_EVENT_DURATION_S = 300
HEARTBEAT_INTERVAL_S = 60
IDLE_SIG = ("Idle", "__idle__", "Idle/Uncategorized", None, None)
WRITES = []
def write_event(conn, cur, os_user, hostname, sig, start_ts=None, end_ts=None, **kw):
    WRITES.append((start_ts, end_ts))
def log(msg, level=None): pass
REPORTS = []
def report_error_to_backend(t, m, tb=None, context=None): REPORTS.append((t, context))
conn = cur = os_user = None
hostname = "TESTHOST"

harness = "def _make(current_sig, last_emit_ts, MOUSE_IDLE_PAUSE_S):\n"
harness += textwrap.indent(body, "    ") + "\n"
harness += "    def _get(): return last_emit_ts\n"
harness += "    return _emit_current_dwell, _get\n"
ns = dict(globals())
exec(compile(harness, "<real _emit_current_dwell>", "exec"), ns)
_make = ns["_make"]

def run(sig, last_emit, end, pause):
    WRITES.clear(); REPORTS.clear()
    fn, get = _make(sig, last_emit, pause)
    fn(end)
    return list(WRITES), get(), list(REPORTS)

QB = ("Qbw.Exe", "qbw.exe", "Syracuse Firefighters Association Local 280", None, None)
fails = []

print("\n--- the real overnight stall (00:01:14 -> 12:51:35, pause=600) ---")
w, nl, r = run(QB, 0.0, 46221.1, 600)
print(f"   events={len(w)} credited={sum(b-a for a,b in w)/60:.1f} min  last_emit_ts={nl}  reports={[t for t,_ in r]}")
if not (len(w) == 2 and abs(nl - 46221.1) < 1e-6 and r): fails.append("overnight")

print("\n--- next heartbeat must not re-emit the dropped span ---")
w2, nl2, _ = run(QB, nl, nl + 62.0, 600)
print(f"   events={len(w2)} seconds={sum(b-a for a,b in w2):.0f}")
if not (len(w2) == 1 and abs(sum(b-a for a,b in w2) - 62.0) < 1e-6): fails.append("heartbeat")

print("\n--- hostile idle_pause values must never write zero events ---")
for p in [None, 0, -5, 1, 60, 600, 3600]:
    w, nl, _ = run(QB, 0.0, 46221.1, p)
    ok = len(w) > 0 and abs(nl - 46221.1) < 1e-6
    print(f"   pause={str(p):6s} events={len(w):3d} credited={sum(b-a for a,b in w)/60:6.1f} min  {'OK' if ok else 'ZERO-WRITE'}")
    if not ok: fails.append(f"pause={p}")

print("\n--- normal work at the real setting must lose nothing ---")
for gap, label in [(5.4,'short dwell'), (62.0,'heartbeat'), (300.0,'5-min freeze'), (540.0,'9-min freeze'), (600.0,'exactly 10 min')]:
    w, _, r = run(QB, 0.0, gap, 600)
    cred = sum(b-a for a,b in w)
    print(f"   {label:15s} gap={gap:6.1f}s credited={cred:6.1f}s lost={gap-cred:5.1f}s reports={len(r)}")
    if abs(cred - gap) > 1e-6 or r: fails.append(label)

print("\n--- IDLE dwells keep their full span ---")
w, _, r = run(IDLE_SIG, 0.0, 2400.0, 600)
print(f"   40-min idle: recorded={sum(b-a for a,b in w)/60:.1f} min reports={len(r)}")
if abs(sum(b-a for a,b in w) - 2400.0) > 1e-6 or r: fails.append("idle")

print("\n--- guard clauses still short-circuit ---")
for sig, le, e, label in [(None, 0.0, 100.0, 'current_sig None'), (QB, None, 100.0, 'last_emit None'),
                          (QB, 100.0, 50.0, 'end before start'), (QB, 0.0, 0.5, 'sub-second')]:
    w, _, _ = run(sig, le, e, 600)
    print(f"   {label:18s} -> {len(w)} events {'OK' if len(w)==0 else 'WROTE!'}")
    if len(w): fails.append(label)

print("\nFAILURES:", fails or "none")
sys.exit(1 if fails else 0)
