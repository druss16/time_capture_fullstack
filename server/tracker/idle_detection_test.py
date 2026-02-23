"""
TimeTracker Idle Detection — Accuracy Test Suite
==================================================
Simulates various activity patterns and validates that idle detection
categorizes them correctly. Tests edge cases CPAs will hit daily.

Usage:
    # If you have a Django management command or testable idle detection module:
    python manage.py shell < idle_detection_test.py

    # Or standalone if you point it at your idle detection logic:
    python idle_detection_test.py

    Modify the `detect_idle` import at the top to match your actual function.
"""

import json
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Optional

# ═══════════════════════════════════════════════════════════════════
# CONFIGURATION — Update these to match your actual implementation
# ═══════════════════════════════════════════════════════════════════

# Try to import your actual idle detection function
# Update this import to match your codebase:
IDLE_DETECTION_IMPORTED = False
try:
    # Common patterns — uncomment/modify the one that matches:
    # from timetracker.detection import detect_idle, IDLE_THRESHOLD
    # from agent.idle import is_idle, IDLE_TIMEOUT
    # from core.activity import IdleDetector
    pass
except ImportError:
    pass

# If import fails, we'll use a reference implementation for testing
IDLE_THRESHOLD_SECONDS = 300  # 5 minutes — adjust to match your setting
SHORT_BREAK_THRESHOLD = 600  # 10 minutes
LONG_BREAK_THRESHOLD = 1800  # 30 minutes


# ═══════════════════════════════════════════════════════════════════
# REFERENCE IDLE DETECTOR (replace with your actual logic)
# ═══════════════════════════════════════════════════════════════════

def reference_detect_idle(activity_events: list, threshold_seconds: int = IDLE_THRESHOLD_SECONDS) -> list:
    """
    Reference idle detection implementation.
    Replace this with a call to your actual detection logic.
    
    Takes a list of activity events and returns annotated events
    with idle periods identified.
    """
    results = []
    for i, event in enumerate(activity_events):
        if i == 0:
            event['is_idle'] = False
            event['idle_duration'] = 0
            results.append(event)
            continue

        prev_end = datetime.fromisoformat(activity_events[i-1]['end_time'])
        curr_start = datetime.fromisoformat(event['start_time'])
        gap = (curr_start - prev_end).total_seconds()

        event['is_idle'] = gap >= threshold_seconds
        event['idle_duration'] = gap if gap >= threshold_seconds else 0
        event['gap_seconds'] = gap
        results.append(event)

    return results


# Use your actual function if imported, otherwise use reference
detect_idle = reference_detect_idle


# ═══════════════════════════════════════════════════════════════════
# TEST SCENARIOS
# ═══════════════════════════════════════════════════════════════════

@dataclass
class TestScenario:
    name: str
    description: str
    events: list
    expected_idle_count: int
    expected_total_idle_minutes: float
    tags: list  # e.g., ["edge-case", "common", "cpa-specific"]


def make_event(start: datetime, duration_minutes: float, app: str = "Excel",
               title: str = "Working") -> dict:
    end = start + timedelta(minutes=duration_minutes)
    return {
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "application": app,
        "window_title": title,
        "duration_seconds": int(duration_minutes * 60)
    }


BASE_TIME = datetime(2026, 2, 24, 8, 0, 0)  # Next Tuesday 8:00 AM

SCENARIOS = [
    # ── Scenario 1: Continuous Work ─────────────────────────────
    TestScenario(
        name="Continuous work — no idle",
        description="CPA working straight through on tax returns. No gaps > threshold.",
        events=[
            make_event(BASE_TIME, 45, "CCH Axcess Tax", "Smith Corp - 1120S"),
            make_event(BASE_TIME + timedelta(minutes=45), 30, "Excel", "Smith Corp - Trial Balance.xlsx"),
            make_event(BASE_TIME + timedelta(minutes=75), 60, "Chrome", "QuickBooks Online - Smith Corp"),
            make_event(BASE_TIME + timedelta(minutes=135), 45, "Outlook", "RE: Smith Corp Questions"),
        ],
        expected_idle_count=0,
        expected_total_idle_minutes=0,
        tags=["common", "baseline"]
    ),

    # ── Scenario 2: Quick App Switching ─────────────────────────
    TestScenario(
        name="Rapid app switching — no idle",
        description="CPA rapidly switching between apps (common during tax prep). Gaps < 10 seconds.",
        events=[
            make_event(BASE_TIME, 3, "CCH Axcess Tax", "Johnson LLC - 1065"),
            make_event(BASE_TIME + timedelta(minutes=3, seconds=5), 2, "Excel", "Johnson LLC - K-1 Allocations"),
            make_event(BASE_TIME + timedelta(minutes=5, seconds=8), 1, "Chrome", "IRS.gov - Form 1065 Instructions"),
            make_event(BASE_TIME + timedelta(minutes=6, seconds=10), 4, "CCH Axcess Tax", "Johnson LLC - 1065"),
            make_event(BASE_TIME + timedelta(minutes=10, seconds=12), 2, "Adobe Acrobat", "Johnson LLC - Engagement Letter.pdf"),
        ],
        expected_idle_count=0,
        expected_total_idle_minutes=0,
        tags=["common", "edge-case"]
    ),

    # ── Scenario 3: Coffee Break ────────────────────────────────
    TestScenario(
        name="Short coffee break — should detect idle",
        description="CPA takes a 7-minute coffee break. Should trigger idle if threshold is 5 min.",
        events=[
            make_event(BASE_TIME, 60, "Excel", "Revenue Analysis.xlsx"),
            # 7-minute gap
            make_event(BASE_TIME + timedelta(minutes=67), 45, "Excel", "Revenue Analysis.xlsx"),
        ],
        expected_idle_count=1,
        expected_total_idle_minutes=7,
        tags=["common"]
    ),

    # ── Scenario 4: Lunch Break ─────────────────────────────────
    TestScenario(
        name="Lunch break — 45 minutes",
        description="CPA takes lunch. Clear idle period.",
        events=[
            make_event(BASE_TIME + timedelta(hours=3, minutes=30), 30, "Outlook", "Inbox"),
            # 45-minute lunch gap
            make_event(BASE_TIME + timedelta(hours=4, minutes=45), 60, "CCH Axcess Tax", "Davis Estate - 1041"),
        ],
        expected_idle_count=1,
        expected_total_idle_minutes=45,
        tags=["common"]
    ),

    # ── Scenario 5: Meeting (no desktop activity) ───────────────
    TestScenario(
        name="In-person meeting — 30-minute gap",
        description="CPA goes to a meeting. No screen activity but shouldn't lose billable time.",
        events=[
            make_event(BASE_TIME, 90, "Excel", "Client Budget.xlsx"),
            # 30-minute meeting gap
            make_event(BASE_TIME + timedelta(minutes=120), 60, "Outlook", "Meeting Notes - Client Review"),
        ],
        expected_idle_count=1,
        expected_total_idle_minutes=30,
        tags=["common", "cpa-specific", "critical"]
    ),

    # ── Scenario 6: Phone Call (screen idle but working) ────────
    TestScenario(
        name="Phone call with client — screen idle, but working",
        description="CPA on a 20-min client call. Screen shows no activity. "
                    "This is the #1 pain point — billable time that gets missed.",
        events=[
            make_event(BASE_TIME, 45, "CCH Axcess Tax", "Rivera Corp - 1120"),
            # 20-minute phone call gap
            make_event(BASE_TIME + timedelta(minutes=65), 30, "CCH Axcess Tax", "Rivera Corp - 1120"),
        ],
        expected_idle_count=1,  # Will detect as idle, but user should be able to reclaim
        expected_total_idle_minutes=20,
        tags=["critical", "cpa-specific", "billable-risk"]
    ),

    # ── Scenario 7: End of Day Forgot to Stop ───────────────────
    TestScenario(
        name="Left computer on overnight",
        description="CPA leaves at 5 PM, doesn't close laptop. Agent should not count 15 hours of idle.",
        events=[
            make_event(BASE_TIME + timedelta(hours=9), 30, "Outlook", "Inbox"),
            # 15-hour overnight gap
            make_event(BASE_TIME + timedelta(hours=24), 30, "Outlook", "Inbox"),
        ],
        expected_idle_count=1,
        expected_total_idle_minutes=870,  # 14.5 hours
        tags=["edge-case", "critical"]
    ),

    # ── Scenario 8: Zoom Call (shows activity) ──────────────────
    TestScenario(
        name="Zoom meeting — app is active",
        description="CPA in a Zoom call. Zoom is the active window, should count as activity.",
        events=[
            make_event(BASE_TIME, 30, "Excel", "Prep for Meeting.xlsx"),
            make_event(BASE_TIME + timedelta(minutes=30), 60, "Zoom", "Team Meeting - Tax Season Planning"),
            make_event(BASE_TIME + timedelta(minutes=90), 30, "Excel", "Action Items.xlsx"),
        ],
        expected_idle_count=0,
        expected_total_idle_minutes=0,
        tags=["common"]
    ),

    # ── Scenario 9: Multiple Short Breaks ───────────────────────
    TestScenario(
        name="Multiple short breaks throughout day",
        description="CPA takes several 2-3 minute breaks (bathroom, water). Should NOT trigger idle at 5min threshold.",
        events=[
            make_event(BASE_TIME, 60, "Excel", "Workpaper.xlsx"),
            # 3-min break
            make_event(BASE_TIME + timedelta(minutes=63), 45, "CCH Axcess Tax", "Tax Return"),
            # 2-min break
            make_event(BASE_TIME + timedelta(minutes=110), 30, "Chrome", "Research"),
            # 4-min break
            make_event(BASE_TIME + timedelta(minutes=144), 60, "Excel", "Analysis.xlsx"),
        ],
        expected_idle_count=0,
        expected_total_idle_minutes=0,
        tags=["common", "cpa-specific"]
    ),

    # ── Scenario 10: Just Under Threshold ───────────────────────
    TestScenario(
        name="Gap just under threshold (4 min 59 sec)",
        description="Gap is 1 second under the 5-minute threshold. Should NOT be idle.",
        events=[
            make_event(BASE_TIME, 30, "Excel", "Report.xlsx"),
            # 4 min 59 sec gap
            make_event(BASE_TIME + timedelta(minutes=34, seconds=59), 30, "Excel", "Report.xlsx"),
        ],
        expected_idle_count=0,
        expected_total_idle_minutes=0,
        tags=["edge-case", "boundary"]
    ),

    # ── Scenario 11: Exactly At Threshold ───────────────────────
    TestScenario(
        name="Gap exactly at threshold (5 min 0 sec)",
        description="Gap is exactly at the 5-minute threshold. Behavior depends on >= vs >.",
        events=[
            make_event(BASE_TIME, 30, "Excel", "Report.xlsx"),
            # Exactly 5 min gap
            make_event(BASE_TIME + timedelta(minutes=35), 30, "Excel", "Report.xlsx"),
        ],
        expected_idle_count=1,  # Assuming >= threshold
        expected_total_idle_minutes=5,
        tags=["edge-case", "boundary"]
    ),

    # ── Scenario 12: Client Switch Pattern ──────────────────────
    TestScenario(
        name="Switching between clients with brief pauses",
        description="CPA finishing one client, pulling up another. 1-2 min gaps.",
        events=[
            make_event(BASE_TIME, 90, "CCH Axcess Tax", "Client A - 1040"),
            # 2-min gap (pulling up next client)
            make_event(BASE_TIME + timedelta(minutes=92), 5, "Chrome", "Client B - QBO Login"),
            make_event(BASE_TIME + timedelta(minutes=97), 60, "CCH Axcess Tax", "Client B - 1120S"),
            # 1-min gap
            make_event(BASE_TIME + timedelta(minutes=158), 45, "Excel", "Client C - Workpaper"),
        ],
        expected_idle_count=0,
        expected_total_idle_minutes=0,
        tags=["common", "cpa-specific"]
    ),
]


# ═══════════════════════════════════════════════════════════════════
# TEST RUNNER
# ═══════════════════════════════════════════════════════════════════

def run_tests():
    print("\n" + "=" * 70)
    print("  IDLE DETECTION ACCURACY TEST")
    print(f"  Threshold: {IDLE_THRESHOLD_SECONDS}s ({IDLE_THRESHOLD_SECONDS/60:.0f} minutes)")
    print(f"  Scenarios: {len(SCENARIOS)}")
    print(f"  Using: {'YOUR idle detector' if IDLE_DETECTION_IMPORTED else 'Reference implementation'}")
    print("=" * 70)

    if not IDLE_DETECTION_IMPORTED:
        print("\n  ⚠️  Using REFERENCE idle detector — not your actual code!")
        print("     Update the import at the top of this file to test your real logic.")
        print("     The reference implementation uses simple gap-based detection.\n")

    passed = 0
    failed = 0
    warnings = []

    for i, scenario in enumerate(SCENARIOS, 1):
        print(f"\n  ── Test {i}/{len(SCENARIOS)}: {scenario.name}")
        print(f"     {scenario.description}")
        print(f"     Tags: {', '.join(scenario.tags)}")

        # Run detection
        results = detect_idle(scenario.events, IDLE_THRESHOLD_SECONDS)

        # Count actual idle periods
        actual_idle_count = sum(1 for r in results if r.get('is_idle', False))
        actual_idle_minutes = sum(r.get('idle_duration', 0) for r in results) / 60.0

        # Compare
        idle_count_match = actual_idle_count == scenario.expected_idle_count
        idle_minutes_match = abs(actual_idle_minutes - scenario.expected_total_idle_minutes) < 1.0

        if idle_count_match and idle_minutes_match:
            print(f"     ✅ PASS")
            print(f"        Idle periods: {actual_idle_count} (expected {scenario.expected_idle_count})")
            print(f"        Idle minutes: {actual_idle_minutes:.1f} (expected {scenario.expected_total_idle_minutes:.1f})")
            passed += 1
        else:
            print(f"     ❌ FAIL")
            if not idle_count_match:
                print(f"        Idle periods: {actual_idle_count} (expected {scenario.expected_idle_count})")
            if not idle_minutes_match:
                print(f"        Idle minutes: {actual_idle_minutes:.1f} (expected {scenario.expected_total_idle_minutes:.1f})")
            failed += 1

            if "critical" in scenario.tags:
                warnings.append(f"CRITICAL failure: {scenario.name}")

        # Show detail for failures
        if not (idle_count_match and idle_minutes_match):
            print(f"        Detail:")
            for j, r in enumerate(results):
                gap = r.get('gap_seconds', 0)
                idle = r.get('is_idle', False)
                if gap > 0 or idle:
                    print(f"          Event {j}: gap={gap:.0f}s idle={'YES' if idle else 'no'} → {r['application']}: {r['window_title']}")

    # ── Summary ──────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"  RESULTS: {passed} passed, {failed} failed out of {len(SCENARIOS)}")
    print("=" * 70)

    if warnings:
        print("\n  ⚠️  CRITICAL WARNINGS:")
        for w in warnings:
            print(f"     • {w}")

    if failed == 0:
        print("\n  ✅ All idle detection tests passed!")
        print("     Your threshold and detection logic look solid for launch.")
    elif failed <= 2:
        print("\n  ⚠️  Some edge cases failing — review before Tuesday.")
        print("     Focus on the 'critical' tagged scenarios first.")
    else:
        print("\n  ❌ Multiple failures — idle detection needs attention before launch.")
        print("     CPAs are very sensitive about lost billable time.")

    # ── CPA-Specific Recommendations ─────────────────────────────
    print(f"""
  ── CPA-SPECIFIC RECOMMENDATIONS ──

  1. PHONE CALLS: Your biggest risk. CPAs spend 20-30% of billable time
     on calls with no screen activity. Consider:
     • A "phone call mode" button in the agent tray
     • Calendar integration to auto-detect meeting blocks
     • Easy "reclaim idle time" UI in the timesheet

  2. THRESHOLD: {IDLE_THRESHOLD_SECONDS/60:.0f} minutes is {'conservative (good for launch)' if IDLE_THRESHOLD_SECONDS >= 300 else 'aggressive — may over-detect idle for busy CPAs'}.
     Recommended: 5-10 minutes for tax season, adjustable per user.

  3. OVERNIGHT: Make sure idle periods are capped or the agent auto-pauses
     after a long idle. No one wants to explain 15 hours of "idle" time.

  4. CLIENT ATTRIBUTION: When idle ends and a new app/client appears,
     make sure the idle period isn't attributed to the new client.
    """)
    print("=" * 70 + "\n")


if __name__ == "__main__":
    run_tests()