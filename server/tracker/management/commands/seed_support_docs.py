"""
Seed the support knowledge base.

Lives at: tracker/support/management/commands/seed_support_docs.py
(the management/ and management/commands/ dirs each need an empty __init__.py)

Run it:
    docker compose exec api python manage.py seed_support_docs

It's idempotent — ingest_doc() clears each doc's old chunks before
re-inserting, so you can edit a doc below and re-run any time.

Docs here are seeded with org=None → GLOBAL (visible to every firm).
To seed an org-specific doc, look up the Organization and pass it.
"""
from django.core.management.base import BaseCommand
from tracker.support.embeddings import ingest_doc


# ── KB content. Edit freely, then re-run the command. ──────────────────
# Each entry: (title, source-slug, markdown body)
DOCS = [
    (
        "Installing the Desktop Agent",
        "agent-install",
        """# Installing the TimeTracker Desktop Agent

The desktop agent runs quietly in the background and captures your activity
so time is tracked automatically. You install it once per computer.

## Windows
1. Go to Account → Connections (or the Download page) and download the Windows installer.
2. Run the installer. It sets itself up to start automatically and recover on its own — no admin prompts after the first run.
3. Pair the agent to your account using the pairing code shown in the app.

## Mac
1. Download the Mac installer from the same Download page.
2. Open the downloaded package and follow the prompts.
3. Grant the requested screen and accessibility permissions so the agent can read window titles.
4. Pair using your pairing code.

## Confirming it's working
Once paired, your activity starts appearing in Daily Review within a few minutes.
If nothing shows up after 10 minutes, check that the agent is running and that
your computer isn't in a paused or idle state.
""",
    ),
    (
        "The Billing Workflow",
        "billing-workflow",
        """# How Time Flows from Capture to Invoice

TimeTracker moves your time through five stages. Each stage hands off to the next.

## 1. My Timesheet
Your captured time is grouped into a weekly timesheet. You review entries,
fix any misclassified clients or categories, and submit the week. You can only
submit after the week has ended.

## 2. Approvals
A manager reviews submitted timesheets and either approves or rejects them.
Rejected timesheets come back to you with a reason so you can correct and resubmit.
Owners' timesheets are auto-approved.

## 3. Client Billing
Approved time becomes billable. This is where invoices are generated per client,
with line items drawn from your approved entries.

## 4. Profitability
Shows margins per client — billing rate versus cost rate — so the firm can see
which engagements are profitable.

## 5. History
Invoiced and locked time is archived here for record-keeping. Locked entries
can no longer be edited.

## Editing rules
You can edit entries while they're in draft. Once a timesheet is approved,
entries are locked unless a manager reopens it.
""",
    ),
    (
        "Connecting Your Calendar",
        "calendar-connect",
        """# Connecting Your Calendar

Connecting your calendar helps TimeTracker match meetings to the right client
automatically, improving how your time is classified.

## How to connect
1. Go to Account → Connections.
2. Find the calendar option and click Connect.
3. Sign in with your work account and approve the requested permissions.

## What it does
Once connected, meetings that have audio or video are matched to clients based
on attendees and meeting details, then surfaced in Daily Review. Your calendar
data is used only to improve classification.

## If sync stops
If your calendar disconnects, go back to Account → Connections and reconnect.
Reconnecting re-establishes the link without losing any of your existing time entries.

## Disconnecting
You can disconnect at any time from the same screen. Disconnecting removes the
calendar data TimeTracker pulled in.
""",
    ),
]


class Command(BaseCommand):
    help = "Seed (or re-seed) the global support knowledge base."

    def handle(self, *args, **options):
        total_chunks = 0
        for title, source, body in DOCS:
            n = ingest_doc(title=title, source=source, markdown=body, org=None)
            total_chunks += n
            self.stdout.write(self.style.SUCCESS(f"  ✓ {title} → {n} chunks"))
        self.stdout.write(self.style.SUCCESS(
            f"\nSeeded {len(DOCS)} docs / {total_chunks} chunks into SupportDoc."
        ))