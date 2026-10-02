"""Tests for agent_presence.py's counting — platform-free, no OS hooks.

    python -m unittest test_agent_presence
"""
import os
import tempfile
import time
import unittest

import agent_presence as ap

HOUR = 1_800_000_000 // 3600 * 3600   # an exact hour boundary


class CollectorTest(unittest.TestCase):
    def setUp(self):
        self.c = ap.Collector()

    def test_clicks_split_real_and_synthetic_with_source(self):
        self.c.note_click(False, now=HOUR + 1)
        self.c.note_click(True, "pad.robot", now=HOUR + 2)
        self.c.note_click(True, "pad.robot", now=HOUR + 3)
        [b] = self.c.take_closed(now=HOUR + 3600)
        self.assertEqual((b["clicks_real"], b["clicks_synthetic"]), (1, 2))
        self.assertEqual(b["synthetic_by"], {"pad.robot": 2})

    def test_foreground_change_counts_only_while_idle(self):
        self.c.note_foreground("chrome.exe", "a", idle_s=0, interval_s=5, now=HOUR + 1)
        self.c.note_foreground("chrome.exe", "b", idle_s=0, interval_s=5, now=HOUR + 6)    # person
        self.c.note_foreground("chrome.exe", "c", idle_s=120, interval_s=5, now=HOUR + 11)  # idle entry
        self.c.note_foreground("chrome.exe", "c", idle_s=125, interval_s=5, now=HOUR + 16)  # no change
        self.c.note_foreground("chrome.exe", "d", idle_s=130, interval_s=5, now=HOUR + 21)  # nobody
        [b] = self.c.take_closed(now=HOUR + 3600)
        self.assertEqual(b["idle_changes"], 1)
        self.assertEqual(b["idle_changes_by_app"], {"chrome": 1})
        self.assertEqual((b["seconds_observed"], b["idle_seconds"]), (25, 15))

    def test_change_at_idle_entry_is_not_counted(self):
        # Active samples carry no title (macOS skips the AX read while working);
        # crossing into idle must not count that as a window change.
        self.c.note_foreground("Safari", "", idle_s=5, interval_s=10, now=HOUR + 10)
        self.c.note_foreground("Safari", "Inbox", idle_s=70, interval_s=10, now=HOUR + 20)
        self.c.note_foreground("Safari", "Inbox", idle_s=80, interval_s=10, now=HOUR + 30)
        self.c.note_foreground("Safari", "Order #4", idle_s=90, interval_s=10, now=HOUR + 40)
        [b] = self.c.take_closed(now=HOUR + 3600)
        self.assertEqual(b["idle_changes"], 1)

    def test_unattended_active_needs_tracker_active_and_hardware_idle(self):
        n = lambda idle, hid, t: self.c.note_foreground("Safari", "x", idle_s=idle, interval_s=10,
                                                         now=HOUR + t, hid_idle_s=hid)
        n(1, 2, 10)       # person working: both clocks fresh
        n(3, 300, 20)     # tracker sees input, hardware untouched 5 min: software
        n(5, 310, 30)
        n(400, 400, 40)   # genuinely idle: tracker would not book it
        n(2, None, 50)    # no HID clock (Windows): never counted
        [b] = self.c.take_closed(now=HOUR + 3600)
        self.assertEqual(b["unattended_active_seconds"], 20)
        self.assertEqual(b["unattended_active_by_app"], {"safari": 20})

    def test_unattended_time_is_given_a_cause_and_people_win_over_agents(self):
        def tick(t, procs):
            self.c.note_processes(procs, 60, now=HOUR + t)
            self.c.note_foreground("Excel", "", idle_s=2, interval_s=10, now=HOUR + t + 1, hid_idle_s=300)

        tick(0, [(1, "universal_control", 10.0), (2, "claude_code", 10.0)])     # baseline sample
        tick(60, [(1, "universal_control", 10.0), (2, "claude_code", 10.0)])    # nothing busy
        tick(120, [(1, "universal_control", 10.0), (2, "claude_code", 15.0)])   # agent busy
        tick(180, [(1, "universal_control", 11.0), (2, "claude_code", 20.0)])   # UC busy too: person
        tick(240, [(1, "universal_control", 11.0), (2, "claude_code", 20.0),
                   (3, "tablet_driver", 0.0)])                                  # tablet: always explains
        [b] = self.c.take_closed(now=HOUR + 3600)
        self.assertEqual(b["unattended_by_cause"], {
            "unexplained": 20, "agent_busy": 10, "universal_control": 10, "tablet_driver": 10})

    def test_always_running_explainer_does_not_explain_while_quiet(self):
        self.c.note_processes([(1, "universal_control", 5.0)], 60, now=HOUR)
        self.c.note_processes([(1, "universal_control", 5.13),      # measured idle noise
                               (2, "claude_desktop", 5.0)], 60, now=HOUR + 60)
        self.c.note_processes([(1, "universal_control", 5.26),
                               (2, "claude_desktop", 10.2)], 60, now=HOUR + 120)  # open app != agent
        self.c.note_foreground("Excel", "", idle_s=2, interval_s=10, now=HOUR + 121, hid_idle_s=300)
        [b] = self.c.take_closed(now=HOUR + 3600)
        self.assertEqual(b["unattended_by_cause"], {"unexplained": 10})

    def test_process_busy_minutes_from_cpu_delta(self):
        self.c.note_processes([(10, "claude_code", 5.0)], 60, now=HOUR + 60)
        self.c.note_processes([(10, "claude_code", 9.0)], 60, now=HOUR + 120)   # +4s: busy
        self.c.note_processes([(10, "claude_code", 9.2)], 60, now=HOUR + 180)   # +0.2s: idle
        [b] = self.c.take_closed(now=HOUR + 3600)
        self.assertEqual(b["processes"]["claude_code"],
                         {"seen_min": 3, "busy_min": 1, "cpu_s": 4.2})

    def test_session_logs_counted_distinct_in_current_hour(self):
        self.c.note_session_files("claude_code", [("/a/s1.jsonl", HOUR - 30)], now=HOUR + 10)
        self.c.note_session_files("claude_code", [("/a/s1.jsonl", HOUR + 200),
                                                  ("/a/s2.jsonl", HOUR + 250)], now=HOUR + 300)
        closed = self.c.take_closed(now=HOUR + 3600)
        self.assertEqual(len(closed), 1)   # never re-creates the previous hour
        self.assertEqual(closed[0]["local_sessions"], {"claude_code": 2})

    def test_open_hour_is_not_sent_and_sent_hours_are_dropped(self):
        self.c.note_click(False, now=HOUR + 1)
        self.assertEqual(self.c.take_closed(now=HOUR + 100), [])
        closed = self.c.take_closed(now=HOUR + 3600)
        self.c.mark_sent(closed)
        self.assertEqual(self.c.take_closed(now=HOUR + 7200), [])

    def test_name_maps_are_capped(self):
        for i in range(ap.MAX_NAMES + 5):
            self.c.note_click(True, f"app{i}", now=HOUR + 1)
        [b] = self.c.take_closed(now=HOUR + 3600)
        self.assertEqual(len(b["synthetic_by"]), ap.MAX_NAMES + 1)
        self.assertEqual(b["synthetic_by"]["_other"], 5)


class ClassifyTest(unittest.TestCase):
    def test_known_agents(self):
        self.assertEqual(ap.classify_process("PAD.Robot.exe"), "power_automate")
        self.assertEqual(ap.classify_process("AutoHotkey64.exe"), "autohotkey")
        self.assertEqual(ap.classify_process("claude", "/Applications/Claude.app/Contents/MacOS/Claude"),
                         "claude_desktop")
        self.assertEqual(ap.classify_process("Claude.exe", r"C:\Users\x\AppData\Local\AnthropicClaude\claude.exe"),
                         "claude_desktop")
        self.assertEqual(ap.classify_process("claude", "/Users/x/.local/bin/claude"), "claude_code")
        self.assertEqual(ap.classify_process(
            "claude", "/Users/x/Library/Application Support/Claude/claude-code/2.1.281/claude.app/Contents/MacOS/claude"),
            "claude_code")
        self.assertEqual(ap.classify_process(
            "chrome-native-host", "/Applications/Claude.app/Contents/Helpers/chrome-native-host"), "claude_in_chrome")
        self.assertIsNone(ap.classify_process("chrome-native-host", "/opt/other/chrome-native-host"))
        self.assertEqual(ap.classify_process("node", "", ["node", "/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js"]),
                         "claude_code")
        self.assertIsNone(ap.classify_process("node", "", ["node", "server.js"]))
        self.assertIsNone(ap.classify_process("EXCEL.EXE"))
        self.assertEqual(ap.classify_process("screensharingd"), "remote_control")
        self.assertEqual(ap.classify_process("TeamViewer.exe"), "remote_control")
        self.assertEqual(ap.classify_process("UniversalControl"), "universal_control")
        self.assertEqual(ap.classify_process("WacomTabletDriver"), "tablet_driver")
        self.assertIsNone(ap.classify_process("parsecd"))  # Apple's Siri daemon, not Parsec


class SessionLogScanTest(unittest.TestCase):
    def test_reads_mtimes_only_and_filters_by_since(self):
        with tempfile.TemporaryDirectory() as home:
            proj = os.path.join(home, ".claude", "projects", "p")
            os.makedirs(proj)
            old, new = os.path.join(proj, "old.jsonl"), os.path.join(proj, "new.jsonl")
            for p in (old, new):
                open(p, "w").close()
            os.utime(old, (time.time() - 7200, time.time() - 7200))
            found = ap.recent_session_logs(home, since=time.time() - 600)
            self.assertEqual([os.path.basename(p) for p, _ in found["claude_code"]], ["new.jsonl"])


class CopiesInSyncTest(unittest.TestCase):
    def test_mac_copy_is_identical(self):
        here = os.path.dirname(os.path.abspath(__file__))
        mac = os.path.join(here, "..", "mac_agent", "agent_presence.py")
        if not os.path.exists(mac):
            self.skipTest("mac_agent not alongside")
        with open(os.path.join(here, "agent_presence.py"), "rb") as a, open(mac, "rb") as b:
            self.assertEqual(a.read(), b.read(), "windows_agent/ and mac_agent/ agent_presence.py differ")


if __name__ == "__main__":
    unittest.main()
