"""
enrich_demo_titles.py

Run this in Django shell to give every Block in the Pinnacle demo a richer,
more varied window title and app_name. Also re-generates RawEvents so the
timesheet/daily review shows the new titles.

Usage:
    docker compose exec api python manage.py shell < enrich_demo_titles.py

Or paste the whole thing into `python manage.py shell`.
"""

import random
from datetime import timedelta
from tracker.models import Block, RawEvent, Organization, Client

random.seed(123)

org = Organization.objects.get(slug='pinnacle-advisory')

# ──────────────────────────────────────────────────────────────────────────
#  Rich title library — many variants per category, with realistic filenames
# ──────────────────────────────────────────────────────────────────────────

TITLES_BY_CATEGORY = {
    "Tax Preparation": [
        ("UltraTax CS - {client} - Form 1040",                 "UltraTax CS"),
        ("UltraTax CS - {client} - Form 1120S",                "UltraTax CS"),
        ("UltraTax CS - {client} - Form 1065 K-1",             "UltraTax CS"),
        ("UltraTax CS - {client} - Schedule C",                "UltraTax CS"),
        ("UltraTax CS - {client} - Schedule E Rentals",        "UltraTax CS"),
        ("UltraTax CS - {client} - Form 990",                  "UltraTax CS"),
        ("UltraTax CS - {client} - Estimated Payments Q2",     "UltraTax CS"),
        ("Lacerte - {client} - 1040 Diagnostic",               "Lacerte"),
        ("CCH ProSystem fx - {client} 1120S",                  "CCH ProSystem fx"),
        ("{client} - Tax Workpapers TY2025.xlsx - Excel",      "Excel"),
        ("{client} - Depreciation Schedule.xlsx - Excel",      "Excel"),
        ("{client} - Basis Calculation.xlsx - Excel",          "Excel"),
        ("Form 8879 - {client} signed.pdf - Adobe Acrobat",    "Acrobat"),
        ("{client} - Prior Year Return.pdf - Adobe Acrobat",   "Acrobat"),
        ("Form 4562 - {client}.pdf - Adobe Acrobat",           "Acrobat"),
        ("{client} - K-1 Schedule.pdf - Adobe Acrobat",        "Acrobat"),
        ("SafeSend Returns - {client} eSign Tracking",         "Browser"),
    ],
    "Tax Planning": [
        ("BNA Tax Planner - {client} - 5yr Projection",        "BNA Tax Planner"),
        ("BNA Tax Planner - {client} - Roth Conversion",       "BNA Tax Planner"),
        ("BNA Tax Planner - {client} - QBI Optimization",      "BNA Tax Planner"),
        ("{client} - Tax Projection Model.xlsx - Excel",       "Excel"),
        ("{client} - Multi-State Apportionment.xlsx - Excel",  "Excel"),
        ("{client} - 1031 Exchange Analysis.xlsx - Excel",     "Excel"),
        ("{client} - Estate Tax Planning.xlsx - Excel",        "Excel"),
        ("Tax Planning Memo - {client}.docx - Word",           "Word"),
        ("Year-End Strategy Letter - {client}.docx - Word",    "Word"),
        ("Checkpoint - Sec 199A Analysis - {client}",          "Browser"),
        ("Checkpoint - Cost Segregation - {client}",           "Browser"),
    ],
    "Audit & Assurance": [
        ("CCH Engagement - {client} Audit FY25",               "CCH Engagement"),
        ("CCH Engagement - {client} - Lead Sheets",            "CCH Engagement"),
        ("CCH Engagement - {client} - Sampling Workpapers",    "CCH Engagement"),
        ("{client} - Audit Workpapers.xlsx - Excel",           "Excel"),
        ("{client} - Trial Balance Reconciliation.xlsx",       "Excel"),
        ("{client} - Substantive Testing.xlsx - Excel",        "Excel"),
        ("{client} - AP Confirmations.xlsx - Excel",           "Excel"),
        ("{client} - AR Aging Detail.xlsx - Excel",            "Excel"),
        ("{client} - Risk Assessment.docx - Word",             "Word"),
        ("{client} - Management Letter.docx - Word",           "Word"),
        ("Audit Confirmations Tracker - {client}",             "Browser"),
        ("{client} - Audit Lead Sheets.pdf - Adobe Acrobat",   "Acrobat"),
        ("{client} - Internal Controls Memo.pdf",              "Acrobat"),
        ("PPC Smart Practice Aids - {client}",                 "PPC SMART"),
    ],
    "Bookkeeping": [
        ("QuickBooks Online - {client} - Dashboard",           "QuickBooks Online"),
        ("QuickBooks Online - {client} - Banking",             "QuickBooks Online"),
        ("QuickBooks Online - {client} - Reconcile",           "QuickBooks Online"),
        ("QuickBooks Online - {client} - Chart of Accounts",   "QuickBooks Online"),
        ("QuickBooks Online - {client} - P&L Report",          "QuickBooks Online"),
        ("Xero - {client} - Bank Reconciliation",              "Xero"),
        ("Xero - {client} - Invoice Awaiting Approval",        "Xero"),
        ("{client} - Bank Reconciliation March 2026.xlsx",     "Excel"),
        ("{client} - Monthly Close Checklist.xlsx - Excel",    "Excel"),
        ("{client} - General Ledger Detail.xlsx - Excel",      "Excel"),
        ("{client} - AP Aging Report.xlsx - Excel",            "Excel"),
        ("Bill.com - {client} - AP Approval Queue",            "Browser"),
        ("Dext Prepare - {client} - Receipt Capture",          "Browser"),
    ],
    "Payroll": [
        ("Gusto - {client} - Run Payroll",                     "Gusto"),
        ("Gusto - {client} - Quarterly 941",                   "Gusto"),
        ("ADP RUN - {client} - Payroll Register",              "ADP RUN"),
        ("ADP RUN - {client} - W-2 Preview",                   "ADP RUN"),
        ("Paychex Flex - {client}",                            "Browser"),
        ("{client} - Payroll Reconciliation.xlsx - Excel",     "Excel"),
        ("{client} - 1099 Vendor Tracking.xlsx - Excel",       "Excel"),
    ],
    "Advisory/Consulting": [
        ("{client} - Strategic Plan FY26.docx - Word",         "Word"),
        ("{client} - Quarterly Business Review.docx - Word",   "Word"),
        ("{client} - Cash Flow Forecast.xlsx - Excel",         "Excel"),
        ("{client} - 13-Week Cash Flow Model.xlsx - Excel",    "Excel"),
        ("{client} - KPI Dashboard.xlsx - Excel",              "Excel"),
        ("{client} - Budget vs Actual Q1.xlsx - Excel",        "Excel"),
        ("{client} - Equity Waterfall Model.xlsx - Excel",     "Excel"),
        ("{client} - Valuation Analysis.xlsx - Excel",         "Excel"),
        ("Advisory Memo - {client} - M&A Diligence.docx",      "Word"),
        ("{client} - Strategic Recommendations.pptx",          "PowerPoint"),
        ("Teams - Strategy Call with {client}",                "Microsoft Teams"),
        ("Zoom Meeting - {client} Quarterly Review",           "Zoom"),
    ],
    "Client Communication": [
        ("Inbox - Outlook",                                     "Outlook"),
        ("Re: {client} - Question on entries - Outlook",        "Outlook"),
        ("FW: {client} - Document request - Outlook",           "Outlook"),
        ("Re: {client} - K-1 timing - Outlook",                 "Outlook"),
        ("Calendar - Outlook",                                  "Outlook"),
        ("Teams - Meeting with {client}",                       "Microsoft Teams"),
        ("Teams - {client} weekly check-in",                    "Microsoft Teams"),
        ("Slack - #client-{client_short}",                      "Slack"),
        ("Karbon - {client} - Email Triage",                    "Karbon"),
        ("Karbon - {client} - Client Tasks",                    "Karbon"),
        ("Zoom - Meeting with {client}",                        "Zoom"),
    ],
    "Research": [
        ("Checkpoint - {client} issue research",                "Browser"),
        ("Checkpoint - Section 263A Analysis",                  "Browser"),
        ("Checkpoint - State Nexus Research - {client}",        "Browser"),
        ("BNA Tax Library - Bonus Depreciation",                "Browser"),
        ("BNA Tax Library - Sec 199A Aggregation",              "Browser"),
        ("AICPA Standards - SAS 145 Update",                    "Browser"),
        ("IRS.gov - Rev Proc 2024-08",                          "Browser"),
        ("Research Memo - {client}.docx - Word",                "Word"),
        ("Tax Notes - Pass-through Entity Tax Update",          "Browser"),
    ],
    "Document Review": [
        ("{client} - Source Documents.pdf - Adobe Acrobat",     "Acrobat"),
        ("{client} - Bank Statements.pdf - Adobe Acrobat",      "Acrobat"),
        ("{client} - Brokerage 1099-B.pdf - Adobe Acrobat",     "Acrobat"),
        ("{client} - Closing Documents.pdf - Adobe Acrobat",    "Acrobat"),
        ("{client} - Legal Agreement.pdf - Adobe Acrobat",      "Acrobat"),
        ("{client} - Prior Year Workpapers.pdf",                "Acrobat"),
        ("{client} - Trial Balance.xlsx - Excel",               "Excel"),
        ("{client} - GL Detail Review.xlsx - Excel",            "Excel"),
        ("Reviewing {client} workpapers - SmartVault",          "Browser"),
        ("ShareFile - {client} Documents",                      "Browser"),
    ],
    "Admin/Internal": [
        ("Inbox - Outlook",                                     "Outlook"),
        ("Calendar - Outlook",                                  "Outlook"),
        ("Karbon - Internal Tasks",                             "Karbon"),
        ("Karbon - Workflow Triage",                            "Karbon"),
        ("Slack - Pinnacle Advisory - #general",                "Slack"),
        ("Slack - Pinnacle Advisory - #partners",               "Slack"),
        ("Pinnacle Advisory - Internal Wiki",                   "Browser"),
        ("Practice Management Dashboard",                       "Browser"),
        ("Time Off Request - HR Portal",                        "Browser"),
        ("Expense Report - April 2026.xlsx - Excel",            "Excel"),
        ("Pinnacle Advisory - Staff Scheduling.xlsx",           "Excel"),
        ("Teams - All Hands Meeting",                           "Microsoft Teams"),
        ("Teams - Partner Standup",                             "Microsoft Teams"),
    ],
    "Training": [
        ("Becker CPE - Tax Update 2026 Module 3",               "Browser"),
        ("Becker CPE - Audit Standards Refresher",              "Browser"),
        ("AICPA Webinar - SAS 145 Implementation",              "Browser"),
        ("AICPA Webinar - Cybersecurity for CPAs",              "Browser"),
        ("Surgent CPE - Multi-State Tax Update",                "Browser"),
        ("CCH Webinar - Form 1040 Changes for 2025",            "Browser"),
        ("LinkedIn Learning - Excel Power Pivot",               "Browser"),
    ],
}

# ──────────────────────────────────────────────────────────────────────────
#  Step 1: re-title every block based on its task_type + client
# ──────────────────────────────────────────────────────────────────────────

print("Step 1/3: Re-titling blocks with rich variety...")

total_blocks = Block.objects.filter(org=org).count()
processed = 0

for blk in Block.objects.filter(org=org).select_related('client', 'task_type').iterator(chunk_size=500):
    tt_name = blk.task_type.name if blk.task_type else "Admin/Internal"
    pool = TITLES_BY_CATEGORY.get(tt_name, TITLES_BY_CATEGORY["Admin/Internal"])

    title_template, app_name = random.choice(pool)
    client_name = blk.client.name if blk.client else "Internal"
    client_short = (blk.client.code if blk.client else "internal").lower()

    new_title = (
        title_template
        .replace("{client}", client_name)
        .replace("{client_short}", client_short)
    )

    blk.title = new_title
    blk.window_title = new_title
    blk.app_name = app_name
    blk.save(update_fields=['title', 'window_title', 'app_name'])

    processed += 1
    if processed % 1000 == 0:
        print(f"  …re-titled {processed:,}/{total_blocks:,}")

print(f"  ✓ Re-titled {processed:,} blocks")

# ──────────────────────────────────────────────────────────────────────────
#  Step 2: wipe existing RawEvents for this org's blocks
# ──────────────────────────────────────────────────────────────────────────

print("Step 2/3: Wiping old RawEvents...")
deleted, _ = RawEvent.objects.filter(block__org=org).delete()
print(f"  ✓ Deleted {deleted:,} old events")

# ──────────────────────────────────────────────────────────────────────────
#  Step 3: regenerate dense RawEvents for every block (every 2 min)
# ──────────────────────────────────────────────────────────────────────────

print("Step 3/3: Regenerating dense RawEvents (one every 2 minutes)...")

EVENT_INTERVAL = 120
total_events = 0
processed_blocks = 0

# Iterate by ID batches, not iterator()
for i in range(0, total_blocks, BATCH_SIZE):
    batch_ids = all_block_ids[i:i + BATCH_SIZE]
    blocks = list(
        Block.objects.filter(id__in=batch_ids).select_related('user')
    )
    
    events_buffer = []
    for blk in blocks:
        duration_seconds = int((blk.end - blk.start).total_seconds())
        num_events = max(2, duration_seconds // EVENT_INTERVAL)
        for n in range(num_events):
            ts = blk.start + timedelta(seconds=n * EVENT_INTERVAL)
            if ts >= blk.end:
                break
            events_buffer.append(RawEvent(
                ts_utc=ts,
                app_name=blk.app_name or 'Unknown',
                bundle_id='',
                window_title=blk.window_title or blk.title or '',
                url='', file_path='',
                user=blk.user,
                device_id=blk.device_id or 'demo',
                hostname=blk.hostname or 'demo-pc',
                ctx={},
                current_client_id=blk.client_id,
                block=blk,
            ))
    
    if events_buffer:
        RawEvent.objects.bulk_create(events_buffer, batch_size=1000)
        total_events += len(events_buffer)
    
    processed_blocks += len(blocks)
    if processed_blocks % 1000 == 0 or processed_blocks == total_blocks:
        print(f"  …block {processed_blocks:,}/{total_blocks:,}, events: {total_events:,}")

print(f"  ✓ Created {total_events:,} RawEvents")

# ──────────────────────────────────────────────────────────────────────────
#  Done
# ──────────────────────────────────────────────────────────────────────────

print()
print("=" * 60)
print("Demo enrichment complete!")
print(f"  Blocks re-titled:  {processed:,}")
print(f"  RawEvents created: {total_events:,}")
print()
print("Refresh My Timesheet — you should now see:")
print("  • 8-12 distinct rows for Sarah's week")
print("  • Mix of UltraTax / Excel / Word / Outlook / Teams titles")
print("  • Realistic file names per task type")
print("=" * 60)