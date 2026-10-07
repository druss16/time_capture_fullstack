"""The permission state machine behind the setup checklist.

    python3 mac_agent/test_permissions.py

No macOS calls: PermissionMonitor is driven by a fake probe object and a fake
clock. Covers: Accessibility prompt-once and live flip, the post-upgrade
stale-entry reset, Automation denied (-1743) detection, required vs optional,
"Remind me later" re-showing, and the update swap helper's restart.
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import permissions as P  # noqa: E402


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class FakeProbes:
    def __init__(self, ax=False, installed=(), running=(), ae=None):
        self.ax = ax
        self.inst = set(installed)
        self.running = set(running)
        self.ae = dict(ae or {})
        self.ax_prompts = 0
        self.opened = []
        self.resets = 0
        self.asked = []
        self.answer = P.GRANTED
        self.front = None

    def ax_trusted(self):
        return self.ax

    def ax_prompt(self):
        self.ax_prompts += 1
        return self.ax

    def installed(self, b):
        return b in self.inst

    def running_path(self, b):
        return f"/Applications/{b}.app" if b in self.running else None

    def frontmost_bundle(self):
        return self.front

    def ae_status(self, b):
        if b not in self.running:
            return P.NOT_RUNNING
        return self.ae.get(b, P.NOT_ASKED)

    def ae_prompt(self, b, path):
        self.asked.append(b)
        self.ae[b] = self.answer
        return self.answer

    def open_url(self, url, bundle_id=None):
        self.opened.append(bundle_id or url)

    def tcc_reset_accessibility(self):
        self.resets += 1
        return True


def monitor(probes, clock=None, ext=None, version="1.9.18", state=None):
    return P.PermissionMonitor(
        probes, state or tempfile.mktemp(suffix=".json"), clock=clock or Clock(),
        log=lambda m: None, extension_last_seen=(lambda: ext), version=version)


CHROME, PS, EXCEL, SAFARI = ("com.google.Chrome", "com.adobe.Photoshop",
                             "com.microsoft.Excel", "com.apple.Safari")


# ---------------------------------------------------------------- Accessibility

def test_ax_prompts_once_per_launch_then_only_on_click():
    p = FakeProbes(ax=False)
    c = Clock()
    m = monitor(p, c)
    m.startup(version_changed=False)
    assert p.ax_prompts == 1
    for _ in range(5):
        c.advance(P.RECHECK_MISSING_S)
        m.tick()
    assert p.ax_prompts == 1, "must not re-prompt on every re-check"
    m.fix("accessibility")
    assert p.ax_prompts == 2, "a click on Fix always prompts"
    assert P.AX_PANE_URL in p.opened, "Fix opens the exact Accessibility pane"


def test_ax_grant_flips_live_without_restart():
    p = FakeProbes(ax=False)
    c = Clock()
    m = monitor(p, c)
    m.startup(False)
    assert m.capture_mode() == "no_accessibility"
    p.ax = True                       # the person flips the switch
    c.advance(P.RECHECK_MISSING_S - 1)
    assert m.tick() is False, "not due yet"
    c.advance(1)
    assert m.tick() is True, "re-checked within 12s and reported the change"
    assert m.ax_granted is True and m.capture_mode() == "full"
    assert m.report()["accessibility"] == "granted"
    # Once granted, only a slow re-check (to notice a revocation).
    c.advance(P.RECHECK_MISSING_S)
    assert not m.due()


def test_revoked_mid_run_is_noticed_and_prompts_at_most_once():
    p = FakeProbes(ax=True)
    c = Clock()
    m = monitor(p, c)
    m.startup(False)
    assert p.ax_prompts == 0
    p.ax = False
    c.advance(P.RECHECK_OK_S)
    assert m.tick() is True
    assert m.capture_mode() == "no_accessibility"
    assert p.ax_prompts == 1


def test_stale_entry_reset_only_after_an_upgrade_and_once_per_version():
    state = tempfile.mktemp(suffix=".json")
    p = FakeProbes(ax=False)
    monitor(p, state=state).startup(version_changed=False)
    assert p.resets == 0, "a plain launch with AX missing must not reset anything"

    m = monitor(p, state=state)
    m.startup(version_changed=True)
    assert p.resets == 1
    assert m.stale_entry_reset and m.report()["stale_entry_reset"] is True
    ax_row = m.rows()[[r["key"] for r in m.rows()].index("accessibility")]
    assert "“−”" in ax_row["detail"] and "“+”" in ax_row["detail"]

    monitor(p, state=state).startup(version_changed=True)
    assert p.resets == 1, "never twice for the same version"
    monitor(p, state=state, version="1.9.19").startup(version_changed=True)
    assert p.resets == 2


def test_no_reset_when_ax_is_fine_after_upgrade():
    p = FakeProbes(ax=True)
    monitor(p).startup(version_changed=True)
    assert p.resets == 0 and p.ax_prompts == 0


# ---------------------------------------------------------------- Automation

def test_osascript_denied_detection():
    assert P.osascript_denied(1, "execution error: Not authorized to send Apple events "
                                 "to Google Chrome. (-1743)")
    assert P.osascript_denied(1, "... (-1743)")
    assert not P.osascript_denied(0, "(-1743)")
    assert not P.osascript_denied(1, "execution error: Can't get window 1. (-1728)")
    assert P.ae_code_to_status(0) == P.GRANTED
    assert P.ae_code_to_status(-1743) == P.DENIED
    assert P.ae_code_to_status(-1744) == P.NOT_ASKED
    assert P.ae_code_to_status(-600) == P.NOT_RUNNING


def test_denied_seen_in_capture_puts_row_back_and_survives_app_quitting():
    p = FakeProbes(ax=True, installed={CHROME}, running={CHROME}, ae={CHROME: P.GRANTED})
    c = Clock()
    m = monitor(p, c, ext=c())
    m.startup(False)
    assert m.missing_required() == []
    m.remind_later()
    assert m.record_observed(CHROME, P.DENIED) is True
    assert m.missing_required() == ["Google Chrome"]
    assert m.should_show_checklist(), "a fresh denial clears the snooze"
    assert m.report()["automation"][CHROME] == "denied"
    # Chrome quits: macOS can't answer any more, but we remember the denial.
    p.running.clear()
    p.ae.pop(CHROME)
    m.refresh()
    assert m.automation[CHROME] == P.DENIED
    assert m.missing_required() == ["Google Chrome"]
    # The person turns it back on and Chrome is open again.
    p.running.add(CHROME)
    p.ae[CHROME] = P.GRANTED
    m.refresh()
    assert m.missing_required() == []


def test_record_observed_ignores_unknown_bundles_and_noise():
    m = monitor(FakeProbes())
    assert m.record_observed("com.example.unknown", P.DENIED) is False
    assert m.record_observed(CHROME, P.UNKNOWN) is False


def test_required_vs_optional():
    p = FakeProbes(ax=False, installed={CHROME, PS, EXCEL}, running={CHROME, PS, EXCEL})
    c = Clock()
    m = monitor(p, c, ext=c())                 # extension fresh
    m.startup(False)
    # Chrome + Photoshop never asked: required. Excel never asked: optional.
    # Accessibility missing: recommended, never counted.
    assert m.missing_required() == ["Google Chrome", "Adobe Photoshop"]
    assert m.recommended_missing() == ["Accessibility"]
    assert m.menu_label() == "⚠️ Finish setup (2 permissions missing)"
    rows = {r["key"]: r for r in m.rows()}
    assert rows["accessibility"]["required"] is False
    assert "Slack desktop, Figma and Canva" in rows["accessibility"]["detail"]
    assert rows[EXCEL]["required"] is False and rows[EXCEL]["fix"] == "Ask"
    assert rows[CHROME]["required"] is True
    order = [r["required"] for r in m.rows()]
    assert order == sorted(order, reverse=True), "required rows first"


def test_app_not_running_is_will_ask_not_missing():
    p = FakeProbes(ax=True, installed={PS}, running=set())
    m = monitor(p)
    m.startup(False)
    row = {r["key"]: r for r in m.rows()}[PS]
    assert row["ok"] is None and row["fix"] is None
    assert "first time you open Adobe Photoshop" in row["detail"]
    assert m.missing_required() == []
    assert m.report()["automation"][PS] == "unknown"


def test_ask_all_pending_asks_running_unasked_apps_only():
    p = FakeProbes(ax=True, installed={CHROME, PS, SAFARI},
                   running={CHROME, SAFARI}, ae={SAFARI: P.GRANTED})
    c = Clock()
    m = monitor(p, c, ext=c())
    m.startup(False)
    assert m.ask_all_pending() == ["Google Chrome"]
    assert p.asked == [CHROME]
    assert m.missing_required() == []
    assert m.asking is None


def test_fix_denied_opens_automation_pane_not_ask():
    p = FakeProbes(ax=True, installed={CHROME}, running={CHROME}, ae={CHROME: P.DENIED})
    m = monitor(p)
    m.startup(False)
    m.fix(CHROME)
    assert p.asked == [] and p.opened == [P.AUTOMATION_PANE_URL]


def test_extension_required_only_after_the_browser_sat_in_front_silently():
    p = FakeProbes(ax=True, installed={CHROME}, running={CHROME}, ae={CHROME: P.GRANTED})
    c = Clock()
    m = monitor(p, c, ext=None)
    p.front = CHROME
    m.startup(False)
    assert m.extension == P.NOT_RUNNING, "just came to front: too soon to judge"
    c.advance(P.EXTENSION_FRONT_GRACE_S)
    m.refresh()
    assert m.missing_required() == ["Browser extension"]
    p.running.clear()
    p.front = None
    m.refresh()
    assert m.extension == P.NOT_RUNNING and m.missing_required() == []

    m2 = monitor(p, c, ext=c() - P.EXTENSION_FRESH_S + 5)
    p.running.add(CHROME)
    m2.startup(False)
    assert m2.extension == "seen" and m2.missing_required() == []
    # No supported browser installed at all: no extension row.
    m3 = monitor(FakeProbes(ax=True, installed={SAFARI}), c)
    m3.startup(False)
    assert m3.extension is None
    assert "extension" not in {r["key"] for r in m3.rows()}


def test_extension_quiet_while_browser_in_background_is_not_missing():
    """The bug: Chrome open behind Photoshop for 5+ minutes flagged the
    extension as off. It only posts while its browser is in front."""
    p = FakeProbes(ax=True, installed={CHROME, PS}, running={CHROME, PS},
                   ae={CHROME: P.GRANTED, PS: P.GRANTED})
    c = Clock()
    last = [c()]
    m = P.PermissionMonitor(p, tempfile.mktemp(suffix=".json"), clock=c,
                            log=lambda m: None, extension_last_seen=lambda: last[0])
    p.front = CHROME
    m.startup(False)
    assert m.extension == "seen"
    p.front = PS                                  # off to Photoshop for an hour
    for _ in range(30):
        c.advance(P.RECHECK_OK_S)
        m.refresh()
        assert m.extension == "seen" and m.missing_required() == []
    # Back in Chrome; the extension posts on focus.
    p.front = CHROME
    m.refresh()
    last[0] = c()
    c.advance(P.EXTENSION_FRONT_GRACE_S)
    m.refresh()
    assert m.extension == "seen"
    # Turned off: Chrome stays in front and nothing arrives.
    c.advance(P.EXTENSION_FRESH_S)
    m.refresh()
    assert m.extension == "not_seen"


# ---------------------------------------------------------------- nagging

def test_remind_me_later_reshows_after_the_snooze():
    p = FakeProbes(ax=True, installed={CHROME}, running={CHROME})
    c = Clock()
    state = tempfile.mktemp(suffix=".json")
    m = monitor(p, c, ext=c(), state=state)
    m.startup(False)
    assert m.should_show_checklist()
    m.remind_later()
    assert not m.should_show_checklist()
    # Survives a restart.
    m2 = monitor(p, c, ext=c(), state=state)
    m2.startup(False)
    assert not m2.should_show_checklist()
    c.advance(P.REMIND_LATER_S)
    assert m2.should_show_checklist()


def test_nothing_missing_never_shows():
    p = FakeProbes(ax=False, installed={CHROME}, running={CHROME}, ae={CHROME: P.GRANTED})
    c = Clock()
    m = monitor(p, c, ext=c())
    m.startup(False)
    assert not m.should_show_checklist()
    assert m.menu_label() is None
    assert m.capture_mode() == "no_accessibility"


def test_report_shape():
    p = FakeProbes(ax=False, installed={CHROME, EXCEL}, running={CHROME},
                   ae={CHROME: P.DENIED})
    c = Clock()
    m = monitor(p, c, ext=c())
    m.startup(False)
    r = m.report()
    assert r["accessibility"] == "missing"
    assert r["automation"] == {CHROME: "denied", EXCEL: "unknown"}
    assert r["capture_mode"] == "no_accessibility"
    assert r["required_missing"] == ["Google Chrome"]
    assert r["extension"] == "seen"
    assert r["checked_at"].endswith("+00:00")


# ---------------------------------------------------------------- the root cause

def test_orphan_restart_loop_guard():
    path = tempfile.mktemp(suffix=".json")
    assert [P.orphan_restart_allowed(path, now=100.0 + i) for i in range(4)] == \
        [True, True, True, False]
    assert P.orphan_restart_allowed(path, now=100.0 + 700), "window expires"


def test_this_process_is_not_orphaned():
    assert P.executable_orphaned() is False


def test_swap_helper_restarts_whatever_launchd_respawned():
    """The helper must `kickstart -k` (kill + start) after the swap. A plain
    kickstart left v1.9.17 running from its deleted pre-swap binary."""
    import update_checker as uc
    assert "kickstart -k" in uc._MAC_SWAP_HELPER
    root = tempfile.mkdtemp()
    bundle = os.path.join(root, "TimeTracker.app")
    stage = os.path.join(root, "stage")
    os.makedirs(os.path.join(bundle, "Contents"))
    os.makedirs(os.path.join(stage, "Contents"))
    open(os.path.join(bundle, "Contents", "v"), "w").write("old")
    open(os.path.join(stage, "Contents", "v"), "w").write("new")
    shim = os.path.join(root, "bin")
    os.makedirs(shim)
    calls = os.path.join(root, "calls")
    with open(os.path.join(shim, "launchctl"), "w") as f:
        f.write(f'#!/bin/bash\necho "$@" >> "{calls}"\n')
    os.chmod(os.path.join(shim, "launchctl"), 0o755)
    helper = os.path.join(root, "swap.sh")
    open(helper, "w").write(uc._MAC_SWAP_HELPER)
    env = dict(os.environ, PATH=shim + ":" + os.environ["PATH"], HOME=root)
    dead_pid = "999999"
    subprocess.run(["/bin/bash", helper, bundle, stage, dead_pid, "9.9.9",
                    "com.example.nolabel", os.path.join(root, "log")],
                   env=env, check=True, timeout=30)
    assert open(os.path.join(bundle, "Contents", "v")).read() == "new"
    assert "kickstart -k gui/" in open(calls).read()


# --- AEDeterminePermissionToAutomateTarget can hang forever (macOS 26) -------

def test_ae_status_returns_when_macos_never_answers():
    import threading
    import time
    release = threading.Event()

    def hangs(bundle_id, ask):
        release.wait(30)
        return P._AE_NOERR

    t0 = time.monotonic()
    st = P._ae_status_bounded("com.test.hang", determine=hangs, timeout=0.2)
    assert st == P.UNKNOWN, st
    assert time.monotonic() - t0 < 2, "the caller waited on the hung check"
    # While that call is still stuck, the same app is not asked again (no
    # pile-up of hung threads) ...
    calls = []
    st = P._ae_status_bounded("com.test.hang",
                              determine=lambda b, a: calls.append(b) or P._AE_NOERR,
                              timeout=0.2)
    assert st == P.UNKNOWN and calls == [], (st, calls)
    # ... and once macOS does answer, it is asked normally again.
    release.set()
    time.sleep(0.2)
    st = P._ae_status_bounded("com.test.hang", determine=lambda b, a: P._AE_NOERR,
                              timeout=1)
    assert st == P.GRANTED, st


def test_ae_status_passes_answers_through():
    assert P._ae_status_bounded("com.test.a", lambda b, a: P._AE_DENIED) == P.DENIED
    assert P._ae_status_bounded("com.test.b", lambda b, a: P._AE_WOULD_ASK) == P.NOT_ASKED

    def boom(b, a):
        raise OSError("no CoreServices")
    assert P._ae_status_bounded("com.test.c", boom) == P.UNKNOWN


def test_ae_status_never_asks_macos_about_an_app_that_is_not_running():
    probes = P.MacProbes()
    probes.running_path = lambda b: None
    real, P._ae_determine = P._ae_determine, None  # any call would raise
    try:
        assert probes.ae_status("com.adobe.Photoshop") == P.NOT_RUNNING
    finally:
        P._ae_determine = real


if __name__ == "__main__":
    failures = 0
    names = [n for n in sorted(globals()) if n.startswith("test_") and callable(globals()[n])]
    for name in names:
        try:
            globals()[name]()
            print(f"PASS  {name}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {name}: {e}")
        except Exception as e:
            failures += 1
            print(f"ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{len(names) - failures}/{len(names)} passed")
    sys.exit(1 if failures else 0)
