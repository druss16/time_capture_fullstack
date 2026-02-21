"""
TimeTracker Load Test — Simulates 12 Concurrent Desktop Agents
================================================================
Simulates realistic agent behavior: activity captures, heartbeats,
timesheet submissions, and API queries happening concurrently.

Usage:
    pip install aiohttp rich
    python load_test.py

    # With auth token:
    TIMETRACKER_TOKEN=your_token python load_test.py

    # Custom base URL:
    TIMETRACKER_URL=https://timetracker.mavops.ai python load_test.py
"""

import asyncio
import aiohttp
import time
import json
import random
import os
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional

# ── Config ──────────────────────────────────────────────────────

BASE_URL = os.getenv("TIMETRACKER_URL", "https://timetracker-api-k375.onrender.com")
AUTH_TOKEN = os.getenv("TIMETRACKER_TOKEN", "")
NUM_AGENTS = 12
TEST_DURATION_SECONDS = 120  # 2-minute test
AGENT_HEARTBEAT_INTERVAL = 10  # seconds between heartbeats
ACTIVITY_CAPTURE_INTERVAL = 5  # seconds between activity captures
TIMESHEET_SUBMIT_INTERVAL = 60  # seconds between timesheet submissions

# ── Simulated Users ────────────────────────────────────────────

SIMULATED_USERS = [
    {"name": f"Test User {i+1}", "email": f"testuser{i+1}@testfirm.com", "role": role}
    for i, role in enumerate([
        "partner", "partner",
        "manager", "manager", "manager",
        "senior", "senior", "senior",
        "staff", "staff", "staff", "staff"
    ])
]

SAMPLE_APPS = [
    "Microsoft Excel", "Google Chrome", "QuickBooks Online",
    "Adobe Acrobat", "Microsoft Outlook", "Slack",
    "Microsoft Word", "Zoom", "CCH Axcess Tax",
    "Drake Tax", "Thomson Reuters UltraTax"
]

SAMPLE_CLIENTS = [
    "Smith Manufacturing LLC", "Johnson Medical Group",
    "Riverside Properties Inc", "Tech Innovations Corp",
    "Green Valley Foods", "Metro Construction Co",
    "Lakeside Dental PLLC", "Blue Ridge Consulting",
    "Admin/Internal", "Professional Development"
]


# ── Metrics ─────────────────────────────────────────────────────

@dataclass
class Metrics:
    requests_sent: int = 0
    requests_succeeded: int = 0
    requests_failed: int = 0
    total_response_time: float = 0.0
    max_response_time: float = 0.0
    min_response_time: float = float("inf")
    errors: list = field(default_factory=list)
    status_codes: dict = field(default_factory=dict)
    endpoint_times: dict = field(default_factory=dict)

    def record(self, endpoint: str, status: int, response_time: float, error: Optional[str] = None):
        self.requests_sent += 1
        self.total_response_time += response_time
        self.max_response_time = max(self.max_response_time, response_time)
        self.min_response_time = min(self.min_response_time, response_time)
        self.status_codes[status] = self.status_codes.get(status, 0) + 1

        if endpoint not in self.endpoint_times:
            self.endpoint_times[endpoint] = []
        self.endpoint_times[endpoint].append(response_time)

        if 200 <= status < 300:
            self.requests_succeeded += 1
        else:
            self.requests_failed += 1
            if error:
                self.errors.append({"endpoint": endpoint, "status": status, "error": error[:200]})

    @property
    def avg_response_time(self):
        return self.total_response_time / max(self.requests_sent, 1)

    def report(self):
        print("\n" + "=" * 70)
        print("  TIMETRACKER LOAD TEST RESULTS")
        print("=" * 70)
        print(f"\n  Duration:          {TEST_DURATION_SECONDS}s")
        print(f"  Simulated Agents:  {NUM_AGENTS}")
        print(f"  Total Requests:    {self.requests_sent}")
        print(f"  Succeeded:         {self.requests_succeeded} ({self.requests_succeeded/max(self.requests_sent,1)*100:.1f}%)")
        print(f"  Failed:            {self.requests_failed} ({self.requests_failed/max(self.requests_sent,1)*100:.1f}%)")
        print(f"\n  Response Times:")
        print(f"    Average:         {self.avg_response_time*1000:.0f}ms")
        print(f"    Min:             {self.min_response_time*1000:.0f}ms")
        print(f"    Max:             {self.max_response_time*1000:.0f}ms")
        print(f"    Requests/sec:    {self.requests_sent/TEST_DURATION_SECONDS:.1f}")

        print(f"\n  Status Codes:")
        for code, count in sorted(self.status_codes.items()):
            print(f"    {code}: {count}")

        print(f"\n  Endpoint Breakdown:")
        for endpoint, times in sorted(self.endpoint_times.items()):
            avg = sum(times) / len(times) * 1000
            mx = max(times) * 1000
            print(f"    {endpoint:<35} avg={avg:.0f}ms  max={mx:.0f}ms  n={len(times)}")

        if self.errors:
            print(f"\n  Errors (first 10):")
            for err in self.errors[:10]:
                print(f"    [{err['status']}] {err['endpoint']}: {err['error']}")

        # ── Verdict ──
        print("\n" + "-" * 70)
        fail_rate = self.requests_failed / max(self.requests_sent, 1)
        if fail_rate > 0.1:
            print("  ❌ FAIL — More than 10% of requests failed.")
            print("     Your infrastructure likely cannot handle 12 concurrent agents.")
        elif self.max_response_time > 5.0:
            print("  ⚠️  WARNING — Some requests took over 5 seconds.")
            print("     Users may experience sluggishness. Check DB connections and Celery.")
        elif self.avg_response_time > 1.0:
            print("  ⚠️  WARNING — Average response time over 1 second.")
            print("     Acceptable but monitor closely with real users.")
        else:
            print("  ✅ PASS — Infrastructure looks ready for 12 concurrent agents.")
        print("-" * 70 + "\n")


metrics = Metrics()


# ── HTTP Helpers ────────────────────────────────────────────────

def get_headers():
    headers = {"Content-Type": "application/json"}
    if AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {AUTH_TOKEN}"
    return headers


async def timed_request(session, method, endpoint, payload=None):
    """Make a request and record metrics."""
    url = f"{BASE_URL}{endpoint}"
    start = time.monotonic()
    try:
        async with session.request(method, url, json=payload, headers=get_headers(), timeout=aiohttp.ClientTimeout(total=30)) as resp:
            elapsed = time.monotonic() - start
            body = await resp.text()
            error = body[:200] if resp.status >= 400 else None
            metrics.record(endpoint, resp.status, elapsed, error)
            return resp.status, body
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - start
        metrics.record(endpoint, 408, elapsed, "Request timed out (30s)")
        return 408, "timeout"
    except aiohttp.ClientError as e:
        elapsed = time.monotonic() - start
        metrics.record(endpoint, 0, elapsed, str(e))
        return 0, str(e)


# ── Agent Simulation ───────────────────────────────────────────

async def simulate_heartbeat(session, user, stop_event):
    """Agent sends periodic heartbeats via hello2."""
    while not stop_event.is_set():
        await timed_request(session, "POST", "/api/agents/hello2/", {
            "user_email": user["email"],
            "agent_version": "1.0.0-beta",
            "os": random.choice(["macOS 14.2", "Windows 11", "macOS 13.6"]),
            "hostname": f"{user['name'].replace(' ', '-').lower()}-laptop",
            "timestamp": datetime.utcnow().isoformat()
        })
        await asyncio.sleep(AGENT_HEARTBEAT_INTERVAL + random.uniform(-2, 2))


async def simulate_activity_capture(session, user, stop_event):
    """Agent sends captured desktop activity."""
    while not stop_event.is_set():
        app = random.choice(SAMPLE_APPS)
        client = random.choice(SAMPLE_CLIENTS)
        await timed_request(session, "POST", "/api/raw-events/", {
            "user_email": user["email"],
            "application": app,
            "window_title": f"{client} - {app}",
            "url": f"https://app.example.com/{client.lower().replace(' ', '-')}" if "Chrome" in app else None,
            "start_time": (datetime.utcnow() - timedelta(seconds=ACTIVITY_CAPTURE_INTERVAL)).isoformat(),
            "end_time": datetime.utcnow().isoformat(),
            "duration_seconds": ACTIVITY_CAPTURE_INTERVAL,
            "is_idle": random.random() < 0.05,  # 5% chance of idle
            "timestamp": datetime.utcnow().isoformat()
        })
        await asyncio.sleep(ACTIVITY_CAPTURE_INTERVAL + random.uniform(-1, 1))


async def simulate_timesheet_actions(session, user, stop_event):
    """User views and submits timesheets periodically."""
    while not stop_event.is_set():
        # View today's time
        await timed_request(session, "GET", "/api/today-time/")
        await asyncio.sleep(2)

        # View blocks today
        await timed_request(session, "GET", "/api/blocks-today/")
        await asyncio.sleep(3)

        # View grouped blocks
        await timed_request(session, "GET", "/api/blocks/grouped/")
        await asyncio.sleep(2)

        # Submit a manual time entry
        await timed_request(session, "POST", "/api/time-entries/manual/", {
            "client": random.choice(SAMPLE_CLIENTS),
            "description": f"Working on {random.choice(['tax return', 'audit prep', 'bookkeeping', 'payroll', 'advisory meeting'])}",
            "duration_minutes": random.randint(15, 120),
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "billable": random.random() > 0.2
        })

        await asyncio.sleep(TIMESHEET_SUBMIT_INTERVAL + random.uniform(-10, 10))


async def simulate_api_browsing(session, user, stop_event):
    """User browses clients, reports, and settings."""
    endpoints = [
        ("GET", "/api/clients/list/"),
        ("GET", "/api/whoami/"),
        ("GET", "/api/categories/"),
        ("GET", "/api/timecards/summary/day/"),
        ("GET", "/api/billing/weekly/"),
        ("GET", "/api/profile/"),
        ("GET", "/api/blocks/suggestions/"),
        ("GET", "/api/integrations/status/"),
    ]
    while not stop_event.is_set():
        method, endpoint = random.choice(endpoints)
        await timed_request(session, method, endpoint)
        await asyncio.sleep(random.uniform(5, 20))


async def run_agent(user, stop_event):
    """Simulate a single agent + user."""
    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            simulate_heartbeat(session, user, stop_event),
            simulate_activity_capture(session, user, stop_event),
            simulate_timesheet_actions(session, user, stop_event),
            simulate_api_browsing(session, user, stop_event),
        ]
        await asyncio.gather(*tasks)


# ── Endpoint Discovery ─────────────────────────────────────────

async def discover_endpoints():
    """Try to find your actual API endpoints before the full test."""
    print("\n  Discovering API endpoints...")
    discovery_endpoints = [
        "/api/ping/",
        "/api/whoami/",
        "/api/agents/hello2/",
        "/api/raw-events/",
        "/api/blocks-today/",
        "/api/blocks/grouped/",
        "/api/today-time/",
        "/api/time-entries/manual/",
        "/api/clients/list/",
        "/api/categories/",
        "/api/timecards/summary/day/",
        "/api/billing/weekly/",
        "/api/profile/",
        "/api/integrations/status/",
    ]
    async with aiohttp.ClientSession() as session:
        for endpoint in discovery_endpoints:
            url = f"{BASE_URL}{endpoint}"
            try:
                async with session.get(url, headers=get_headers(), timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    status_icon = "✅" if resp.status < 400 else "⚠️ " if resp.status == 401 else "❌"
                    print(f"    {status_icon} {endpoint} → {resp.status}")
            except Exception as e:
                print(f"    ❌ {endpoint} → {type(e).__name__}")
    print()


# ── Main ────────────────────────────────────────────────────────

async def main():
    print("\n" + "=" * 70)
    print("  TIMETRACKER LOAD TEST")
    print(f"  Target:    {BASE_URL}")
    print(f"  Agents:    {NUM_AGENTS}")
    print(f"  Duration:  {TEST_DURATION_SECONDS}s")
    print(f"  Auth:      {'Token provided' if AUTH_TOKEN else '⚠️  No token (set TIMETRACKER_TOKEN)'}")
    print("=" * 70)

    # Phase 1: Discover endpoints
    await discover_endpoints()

    # Phase 2: Run load test
    print(f"  Starting {NUM_AGENTS} simulated agents...\n")
    stop_event = asyncio.Event()

    agent_tasks = []
    for i, user in enumerate(SIMULATED_USERS[:NUM_AGENTS]):
        task = asyncio.create_task(run_agent(user, stop_event))
        agent_tasks.append(task)
        print(f"    🚀 Agent {i+1}: {user['name']} ({user['role']})")
        await asyncio.sleep(0.5)  # Stagger startup

    print(f"\n  All agents running. Test will run for {TEST_DURATION_SECONDS}s...")
    print(f"  Press Ctrl+C to stop early.\n")

    try:
        await asyncio.sleep(TEST_DURATION_SECONDS)
    except KeyboardInterrupt:
        print("\n  Stopping early...")

    stop_event.set()
    await asyncio.sleep(2)  # Let in-flight requests finish

    for task in agent_tasks:
        task.cancel()

    # Phase 3: Report
    metrics.report()


if __name__ == "__main__":
    asyncio.run(main())