"""
tracker/management/commands/create_demo_customer.py

Creates a fully-populated demo organization ("Pinnacle Advisory CPAs")
with 8 staff, 15 clients, and 3 months of realistic time-tracking data
designed to make every Executive Dashboard KPI tell a story.

Usage:
    python manage.py create_demo_customer
    python manage.py create_demo_customer --reset    # wipe prior demo first
    python manage.py create_demo_customer --slug demo-firm-2  # alt slug
    python manage.py create_demo_customer --owner-password mypassword

Demo story baked in:
  • Hartwell Mfg     → fixed-fee, OVER-SERVICED (negative margin)
  • Linwood Restaurant → aged WIP 60+ days
  • Crestmoor Medical → poor realization (under-billing)
  • Tyler Brooks     → consistently late timesheets
  • Sarah Chen       → low utilization (partner-style)
  • Jenna Park       → over 90% utilization (overworked)
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from tracker.models import (
    Block,
    BillingRate,
    Client,
    ClientAssignment,
    EmployeeCostRate,
    Invoice,
    Organization,
    OrganizationMembership,
    TaskType,
    Timesheet,
    DEFAULT_CPA_TASK_TYPES,
)

User = get_user_model()


# ──────────────────────────────────────────────────────────────────────────
#  Demo configuration
# ──────────────────────────────────────────────────────────────────────────

DEMO_SLUG_DEFAULT = "pinnacle-advisory"
DEMO_NAME = "Pinnacle Advisory CPAs"
DEMO_OWNER_EMAIL = "sarah.chen@pinnacle-demo.com"
DEMO_OWNER_USERNAME = "sarah.chen"

STAFF = [
    # username, first, last, role, billing_rate, cost_rate, target_util
    ("sarah.chen",      "Sarah",   "Chen",      "owner",   Decimal("295.00"), Decimal("110.00"), 0.45),
    ("marcus.webb",     "Marcus",  "Webb",      "manager", Decimal("215.00"), Decimal("88.00"),  0.75),
    ("jenna.park",      "Jenna",   "Park",      "manager", Decimal("180.00"), Decimal("72.00"),  0.92),
    ("david.okonkwo",   "David",   "Okonkwo",   "manager", Decimal("195.00"), Decimal("80.00"),  0.78),
    ("priya.raman",     "Priya",   "Raman",     "member",  Decimal("145.00"), Decimal("58.00"),  0.82),
    ("tyler.brooks",    "Tyler",   "Brooks",    "member",  Decimal("125.00"), Decimal("48.00"),  0.65),
    ("emily.castellanos","Emily",  "Castellanos","member", Decimal("130.00"), Decimal("52.00"),  0.70),
    ("ben.holloway",    "Ben",     "Holloway",  "admin",   Decimal("0.00"),   Decimal("42.00"),  0.20),
]

# story_type drives the data shape:
#   over_serviced  → lots of hours, fixed-fee invoice (negative margin)
#   aged_wip       → approved blocks, no invoice yet (WIP 60+ days)
#   under_billed   → lots of hours, low realization (<70%)
#   healthy        → balanced hours+invoices, ~110% realization
#   high_margin    → minimal hours, fat advisory invoice
#   small          → light volume
CLIENTS = [
    # (name, code, story_type, primary_task_type, notes)
    ("Hartwell Manufacturing",  "HARTWL", "over_serviced", "Audit & Assurance",   "Fixed-fee audit blew through budget"),
    ("Brennan Family Trust",    "BRENN",  "healthy",       "Tax Preparation",     "Long-time client, well-managed"),
    ("Coastal Property Group",  "COAST",  "healthy",       "Bookkeeping",         "Monthly bookkeeping retainer"),
    ("Vandermeer Holdings",     "VANDR",  "high_margin",   "Advisory/Consulting", "Strategic advisory engagement"),
    ("Linwood Restaurant Group","LINWD",  "aged_wip",      "Tax Preparation",     "Slow payer, WIP piling up"),
    ("Apex Dental Practice",    "APEX",   "healthy",       "Bookkeeping",         "Clean books, easy client"),
    ("Whitman Real Estate",     "WHITM",  "small",         "Tax Preparation",     "Small annual return"),
    ("Crestmoor Medical Group", "CREST",  "under_billed",  "Tax Preparation",     "Hours not making it onto invoices"),
    ("Sterling Wealth Partners","STERL",  "high_margin",   "Tax Planning",        "Quarterly tax planning"),
    ("Northridge Logistics",    "NORTH",  "healthy",       "Audit & Assurance",   "Annual audit"),
    ("Birchwood Construction",  "BIRCH",  "healthy",       "Tax Preparation",     "Multi-entity tax work"),
    ("Pemberton & Associates",  "PEMB",   "small",         "Tax Preparation",     "Small partnership return"),
    ("Quinlan Tech Ventures",   "QUINL",  "high_margin",   "Advisory/Consulting", "Equity advisory"),
    ("Riverstone Hospitality",  "RIVER",  "aged_wip",      "Audit & Assurance",   "Audit done, invoice delayed"),
    ("Fairmont Educational Foundation","FAIR","healthy",   "Tax Preparation",     "Form 990 nonprofit"),
]

# Approximate windows-title patterns the agent would have captured
TITLE_TEMPLATES = {
    "Tax Preparation":     ["UltraTax CS - {client} - 1040", "UltraTax CS - {client} - 1120S", "Form 1040 - {client}.pdf - Adobe Acrobat", "{client} Tax Workpapers.xlsx - Excel"],
    "Tax Planning":        ["{client} - Tax Projection Model.xlsx", "Tax Planning Memo - {client}.docx - Word", "BNA Tax Planner - {client}"],
    "Audit & Assurance":   ["CCH Engagement - {client} Audit FY25", "{client} - Audit Workpapers.xlsx", "{client} Audit Lead Sheets.pdf", "Confirmation Tracker - {client}"],
    "Bookkeeping":         ["QuickBooks Online - {client}", "{client} - Bank Reconciliation March", "{client} - Monthly Close.xlsx"],
    "Payroll":             ["Gusto - {client}", "{client} Payroll - ADP RUN"],
    "Advisory/Consulting": ["{client} - Strategic Plan.docx - Word", "{client} - KPI Dashboard.xlsx", "Advisory Memo - {client}"],
    "Client Communication":["Inbox - Outlook", "Teams - Meeting with {client}", "Re: {client} - Question on entries"],
    "Research":            ["Checkpoint - Research - {client} issue", "BNA Tax Library", "AICPA Standards Lookup"],
    "Document Review":     ["{client} - Source Documents.pdf", "Reviewing {client} workpapers", "{client} - Trial Balance.xlsx"],
    "Admin/Internal":      ["Inbox - Outlook", "Karbon - Internal", "Pinnacle Advisory - Internal Wiki"],
    "Training":            ["Becker CPE - Tax Update 2026", "AICPA Webinar - Audit Standards"],
}

INTERNAL_TITLES = ["Inbox - Outlook", "Calendar - Outlook", "Slack - Pinnacle Advisory", "Karbon - Tasks"]


# ──────────────────────────────────────────────────────────────────────────
#  Command
# ──────────────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = "Create a fully-populated demo organization for product demos."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Delete the existing demo org (by slug) before creating.")
        parser.add_argument("--slug", default=DEMO_SLUG_DEFAULT,
                            help=f"Org slug (default: {DEMO_SLUG_DEFAULT})")
        parser.add_argument("--owner-password", default="DemoPass123!",
                            help="Password for the owner login (default: DemoPass123!)")
        parser.add_argument("--days", type=int, default=90,
                            help="Days of history to generate (default: 90)")

    def handle(self, *args, **opts):
        slug = opts["slug"]
        owner_password = opts["owner_password"]
        days_back = opts["days"]
        do_reset = opts["reset"]

        random.seed(42)  # deterministic demo data

        if do_reset:
            self._reset(slug)

        with transaction.atomic():
            org = self._create_org(slug)
            users = self._create_users(org, owner_password)
            task_types = self._create_task_types(org)
            self._create_billing_rates(org, users)
            self._create_cost_rates(org, users)
            clients = self._create_clients(org)
            self._create_assignments(org, clients, users)
            blocks_created = self._create_blocks(org, users, clients, task_types, days_back)
            self._create_invoices(org, clients, users)
            self._create_timesheets(org, users)

        self._summary(org, len(users), len(clients), blocks_created, owner_password)

    # ── reset ────────────────────────────────────────────────────────────
    def _reset(self, slug: str):
        try:
            org = Organization.all_objects.get(slug=slug)
        except Organization.DoesNotExist:
            self.stdout.write(self.style.WARNING(f"No existing org with slug '{slug}' — nothing to reset."))
            return

        self.stdout.write(self.style.WARNING(f"Wiping existing demo org id={org.id} ('{org.name}')..."))

        with transaction.atomic():
            # Delete in order to avoid FK issues
            Block.all_objects.filter(org=org).delete()
            Invoice.objects.filter(org=org).delete()
            Timesheet.objects.filter(org=org).delete()
            BillingRate.objects.filter(org=org).delete()
            EmployeeCostRate.objects.filter(organization=org).delete()
            ClientAssignment.objects.filter(organization=org).delete()
            Client.objects.filter(org=org).delete()
            TaskType.objects.filter(org=org).delete()

            # Delete users that ONLY belong to this org
            user_ids = list(OrganizationMembership.objects.filter(
                organization=org).values_list("user_id", flat=True))
            OrganizationMembership.objects.filter(organization=org).delete()

            for uid in user_ids:
                # Only delete if user has no other memberships
                if not OrganizationMembership.objects.filter(user_id=uid).exists():
                    User.objects.filter(id=uid, email__endswith="@pinnacle-demo.com").delete()

            org.delete()

        self.stdout.write(self.style.SUCCESS("  ✓ Reset complete"))

    # ── org ──────────────────────────────────────────────────────────────
    def _create_org(self, slug: str) -> Organization:
        self.stdout.write("Creating organization...")
        org = Organization.objects.create(
            name=DEMO_NAME,
            slug=slug,
            industry_type="cpa",
            plan="executive",
            timezone="America/New_York",
            billing_rate_default=Decimal("175.00"),
            cost_rate_default=Decimal("70.00"),
            onboarding_completed=True,
            onboarding_step=99,
            seat_count=10,
            is_demo=True,
            ai_sensitivity=50,
            mouse_idle_pause_seconds=600,
        )
        self.stdout.write(self.style.SUCCESS(f"  ✓ Org: {org.name} (id={org.id}, slug={org.slug})"))
        return org

    # ── users ────────────────────────────────────────────────────────────
    def _create_users(self, org: Organization, owner_password: str) -> dict:
        self.stdout.write("Creating staff users...")
        users = {}

        for username, first, last, role, _bill, _cost, _util in STAFF:
            email = f"{username}@pinnacle-demo.com"
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": email,
                    "first_name": first,
                    "last_name": last,
                    "is_active": True,
                },
            )
            if created or not user.has_usable_password():
                user.set_password(owner_password)
                user.save()

            OrganizationMembership.objects.get_or_create(
                user=user,
                organization=org,
                defaults={"role": role},
            )
            users[username] = user
            self.stdout.write(f"  ✓ {first} {last} ({role}) — {email}")

        return users

    # ── task types ───────────────────────────────────────────────────────
    def _create_task_types(self, org: Organization) -> dict:
        self.stdout.write("Creating task types...")
        task_types = {}
        for i, t in enumerate(DEFAULT_CPA_TASK_TYPES):
            tt, _ = TaskType.objects.get_or_create(
                org=org,
                name=t["name"],
                defaults={
                    "code": t["code"],
                    "color": t["color"],
                    "is_billable": t["is_billable"],
                    "sort_order": i,
                },
            )
            task_types[t["name"]] = tt
        self.stdout.write(self.style.SUCCESS(f"  ✓ {len(task_types)} task types"))
        return task_types

    # ── billing rates ────────────────────────────────────────────────────
    def _create_billing_rates(self, org: Organization, users: dict):
        self.stdout.write("Creating billing rates...")
        effective = (timezone.now() - timedelta(days=180)).date()
        for username, _, _, _, bill_rate, _, _ in STAFF:
            if bill_rate <= 0:
                continue
            BillingRate.objects.get_or_create(
                org=org,
                user=users[username],
                client=None,
                task_type=None,
                effective_date=effective,
                defaults={"rate": bill_rate},
            )
        self.stdout.write(self.style.SUCCESS(f"  ✓ {len(STAFF)-1} billing rates set"))

    # ── cost rates ───────────────────────────────────────────────────────
    def _create_cost_rates(self, org: Organization, users: dict):
        self.stdout.write("Creating employee cost rates...")
        effective = (timezone.now() - timedelta(days=180)).date()
        for username, _, _, _, _, cost_rate, _ in STAFF:
            EmployeeCostRate.objects.get_or_create(
                organization=org,
                user=users[username],
                effective_date=effective,
                defaults={"cost_rate": cost_rate},
            )
        self.stdout.write(self.style.SUCCESS(f"  ✓ {len(STAFF)} cost rates set"))

    # ── clients ──────────────────────────────────────────────────────────
    def _create_clients(self, org: Organization) -> list:
        self.stdout.write("Creating clients...")
        clients = []
        for name, code, story, primary_task, notes in CLIENTS:
            client, created = Client.objects.get_or_create(
                org=org,
                code=code,
                defaults={"name": name, "is_active": True},
            )
            # Stash story metadata on the object for later use (not persisted)
            client._story = story
            client._primary_task = primary_task
            clients.append(client)
        self.stdout.write(self.style.SUCCESS(f"  ✓ {len(clients)} clients"))
        return clients

    # ── client assignments ───────────────────────────────────────────────
    def _create_assignments(self, org, clients, users):
        self.stdout.write("Creating client assignments...")
        # Owner + managers see all clients; staff see a subset
        manager_users = [users[u] for u in ("sarah.chen", "marcus.webb", "jenna.park", "david.okonkwo")]
        staff_users = [users[u] for u in ("priya.raman", "tyler.brooks", "emily.castellanos")]

        count = 0
        for client in clients:
            # Pick a partner (rotates), a manager, and 2 staff
            partner = manager_users[hash(client.code) % len(manager_users)]
            ClientAssignment.objects.get_or_create(
                organization=org, client=client, user=partner,
                defaults={"role": "Partner"},
            )
            count += 1

            for staff_user in random.sample(staff_users, k=2):
                ClientAssignment.objects.get_or_create(
                    organization=org, client=client, user=staff_user,
                    defaults={"role": "Staff"},
                )
                count += 1

        self.stdout.write(self.style.SUCCESS(f"  ✓ {count} assignments"))

    # ── blocks ───────────────────────────────────────────────────────────
    def _create_blocks(self, org, users, clients, task_types, days_back: int) -> int:
        self.stdout.write(f"Generating {days_back} days of blocks (this is the slow part)...")

        end_date = timezone.now().date() - timedelta(days=1)
        start_date = end_date - timedelta(days=days_back)
        tz = timezone.get_current_timezone()

        # Clients keyed by story for routing
        clients_by_story = {}
        for c in clients:
            clients_by_story.setdefault(c._story, []).append(c)

        total_blocks = 0

        # Iterate every weekday
        current = start_date
        while current <= end_date:
            if current.weekday() >= 5:  # Skip weekends
                current += timedelta(days=1)
                continue

            for username, first, last, role, _b, _c, target_util in STAFF:
                user = users[username]

                # Daily blocks per user — driven by utilization target
                #   target_util ~0.45 → 6 hours tracked, ~3 billable
                #   target_util ~0.92 → 9.5 hours tracked, ~9 billable
                base_minutes = int(420 + (target_util * 240))  # 7h–11h tracked
                # Add jitter
                day_minutes = int(base_minutes + random.gauss(0, 45))
                day_minutes = max(180, min(660, day_minutes))

                # Build day's blocks
                blocks_today = self._build_day_for_user(
                    user, current, day_minutes, target_util, role,
                    org, clients, clients_by_story, task_types, tz, username,
                )
                # Bulk create
                Block.objects.bulk_create(blocks_today, batch_size=200)
                total_blocks += len(blocks_today)

            current += timedelta(days=1)
            if current.day == 1:
                self.stdout.write(f"  …processed through {current.isoformat()}")

        self.stdout.write(self.style.SUCCESS(f"  ✓ {total_blocks:,} blocks created"))
        return total_blocks

    def _build_day_for_user(self, user, day, total_minutes, util, role,
                            org, clients, clients_by_story, task_types, tz, username) -> list:
        """Build a list of unsaved Block objects for one user-day."""
        blocks = []
        # Start time: jittered around 8:30am
        start_hour = 8 + random.choice([0, 0, 0, 1])
        start_min = random.choice([0, 15, 30, 45])
        cur_dt = timezone.make_aware(datetime.combine(day, time(start_hour, start_min)), tz)

        remaining = total_minutes
        # Lunch break (insert after ~3.5–4 hours of work)
        lunch_inserted = False
        worked_before_lunch = 0

        # Choose a "primary client" for the day for ~60% of the day
        # Heavy bias: workers spend most of the day on one client
        primary_client = self._pick_primary_client_for_day(username, role, clients, clients_by_story)

        while remaining > 30:  # Don't bother creating blocks <30 min
            # Break for lunch?
            if not lunch_inserted and worked_before_lunch >= 210 and worked_before_lunch < 270:
                lunch_dur = random.choice([30, 45, 60])
                cur_dt += timedelta(minutes=lunch_dur)
                lunch_inserted = True
                continue

            # Block duration: typical 25–90 min
            block_min = random.choice([20, 25, 30, 30, 45, 45, 60, 60, 75, 90, 120])
            if block_min > remaining:
                block_min = remaining

            # Decide what this block is
            is_billable, client, task_type, title = self._choose_block_content(
                primary_client, username, role, util, clients, task_types,
            )

            start = cur_dt
            end = cur_dt + timedelta(minutes=block_min)
            cur_dt = end
            remaining -= block_min
            worked_before_lunch += block_min

            # Build block (skip save() validation by using bulk_create later)
            billing_rate = self._lookup_billing_rate(username) if is_billable else None
            billing_amount = (Decimal(block_min) / 60 * billing_rate) if (is_billable and billing_rate) else Decimal("0.00")

            blk = Block(
                org=org,
                user=user,
                device_id=f"demo-{username[:8]}",
                hostname=f"{username.split('.')[0]}-pc",
                start=start,
                end=end,
                day=day,
                minutes=block_min,
                title=title,
                window_title=title,
                app_name=self._app_for_title(title),
                client=client,
                task_type=task_type,
                ai_category=task_type.name if task_type else "",
                category_hours={task_type.name: round(block_min / 60, 2)} if task_type else {},
                is_categorized=True,
                categorized_at=timezone.now(),
                categorized_by="ai",
                ai_confidence=round(random.uniform(0.78, 0.97), 2),
                ai_processed_at=timezone.now(),
                is_billable=is_billable,
                billing_rate=billing_rate,
                billing_amount=billing_amount,
            )
            blocks.append(blk)

        return blocks

    def _pick_primary_client_for_day(self, username, role, clients, clients_by_story):
        """Different staff focus on different clients."""
        # Tyler tends to work on Crestmoor (under-billed scenario)
        if username == "tyler.brooks" and random.random() < 0.4:
            return clients_by_story["under_billed"][0]
        # Priya works heavy on Hartwell (over-serviced audit)
        if username == "priya.raman" and random.random() < 0.45:
            return clients_by_story["over_serviced"][0]
        # Jenna splits between aged_wip and over_serviced (overworked manager)
        if username == "jenna.park":
            return random.choice(clients_by_story["over_serviced"] +
                                 clients_by_story["aged_wip"] +
                                 clients_by_story["under_billed"])
        # Marcus is the audit guy
        if username == "marcus.webb":
            return random.choice(clients_by_story.get("over_serviced", []) +
                                 clients_by_story.get("aged_wip", []) +
                                 clients_by_story.get("healthy", [])[:3])
        # Sarah (owner) does mostly internal/advisory, occasional client
        if username == "sarah.chen":
            return random.choice(clients_by_story["high_margin"] + clients_by_story["healthy"][:2])
        # Ben (admin) — no primary client, mostly internal
        if username == "ben.holloway":
            return None
        # Default: weighted random pick from all
        return random.choice(clients)

    def _choose_block_content(self, primary_client, username, role, util,
                              clients, task_types):
        """Returns (is_billable, client, task_type, title)."""
        roll = random.random()
        # Some baseline non-billable time per role
        non_billable_floor = {
            "owner": 0.55,    # owners do lots of admin / internal
            "admin": 0.95,
            "manager": 0.30,
            "member": 0.20,
        }.get(role, 0.25)

        if roll < non_billable_floor:
            # Non-billable: internal admin, training, communication
            tt_name = random.choice(["Admin/Internal", "Client Communication", "Training"])
            tt = task_types.get(tt_name)
            title = random.choice(INTERNAL_TITLES + TITLE_TEMPLATES.get(tt_name, ["Internal"]))
            return False, None, tt, title.replace("{client}", "")

        # Billable — pick client (70% primary, 30% secondary)
        if primary_client and random.random() < 0.70:
            client = primary_client
        else:
            client = random.choice(clients)

        # Pick task type — biased toward client's primary work
        primary_tt_name = getattr(client, "_primary_task", "Tax Preparation")
        if random.random() < 0.65:
            tt_name = primary_tt_name
        else:
            tt_name = random.choice(["Document Review", "Research", "Client Communication", "Tax Preparation"])

        tt = task_types.get(tt_name) or task_types["Tax Preparation"]
        title_template = random.choice(TITLE_TEMPLATES.get(tt_name, ["{client} - work"]))
        title = title_template.replace("{client}", client.name)

        # Tyler under-bills Crestmoor: mark some hours non-billable
        if username == "tyler.brooks" and client.code == "CREST" and random.random() < 0.35:
            return False, client, tt, title

        return True, client, tt, title

    def _app_for_title(self, title: str) -> str:
        t = title.lower()
        if "ultratax" in t: return "UltraTax CS"
        if "quickbooks" in t: return "QuickBooks"
        if "outlook" in t: return "Outlook"
        if "excel" in t or ".xlsx" in t: return "Excel"
        if "word" in t or ".docx" in t: return "Word"
        if "acrobat" in t or ".pdf" in t: return "Acrobat"
        if "teams" in t: return "Microsoft Teams"
        if "slack" in t: return "Slack"
        if "karbon" in t: return "Karbon"
        if "checkpoint" in t or "bna" in t: return "Browser"
        if "becker" in t: return "Browser"
        if "cch" in t: return "CCH ProSystem fx"
        if "gusto" in t or "adp" in t: return "Browser"
        return "Browser"

    def _lookup_billing_rate(self, username: str) -> Decimal:
        for u, _, _, _, bill, _, _ in STAFF:
            if u == username:
                return bill if bill > 0 else Decimal("0.00")
        return Decimal("175.00")

    # ── invoices ─────────────────────────────────────────────────────────
    def _create_invoices(self, org, clients, users):
        """
        Create invoices that drive the realization / profitability story.

        Mapping from client._story → invoice behavior:
          over_serviced → 1 fixed-fee invoice WAY below worked $$
          healthy       → 3 monthly invoices, ~110% realization
          high_margin   → 1 advisory invoice, well above hours
          aged_wip      → NO invoice yet (creates aged WIP)
          under_billed  → 2 invoices, but only ~65% of worked hours billed
          small         → 1 small invoice
        """
        self.stdout.write("Creating invoices...")
        owner = users["sarah.chen"]
        today = timezone.now().date()
        created_count = 0
        invoice_num = 4001

        for client in clients:
            story = client._story

            # Sum the worked $ for this client (rough)
            worked = Block.objects.filter(
                org=org, client=client, is_billable=True
            ).aggregate(
                total_amt=Sum("billing_amount"),
                total_min=Sum("minutes"),
            )
            worked_amt = float(worked["total_amt"] or 0)
            worked_hrs = float(worked["total_min"] or 0) / 60.0

            if story == "over_serviced":
                # Fixed-fee audit, way below cost
                invoice_amount = Decimal(str(round(worked_amt * 0.55, 2)))
                billed_hours = Decimal(str(round(worked_hrs * 0.55, 1)))
                Invoice.objects.create(
                    org=org, client=client,
                    invoice_number=f"INV-{invoice_num}",
                    invoice_date=today - timedelta(days=20),
                    amount=invoice_amount,
                    hours_billed=billed_hours,
                    client_code=client.code, client_name=client.name,
                    source="manual", status="sent",
                    created_by=owner,
                )
                invoice_num += 1
                created_count += 1

            elif story == "healthy":
                # 3 monthly invoices that total ~110% of worked $
                target = worked_amt * 1.10
                per = Decimal(str(round(target / 3, 2)))
                hrs_per = Decimal(str(round(worked_hrs / 3, 1)))
                for offset_days in [70, 40, 10]:
                    Invoice.objects.create(
                        org=org, client=client,
                        invoice_number=f"INV-{invoice_num}",
                        invoice_date=today - timedelta(days=offset_days),
                        amount=per, hours_billed=hrs_per,
                        client_code=client.code, client_name=client.name,
                        source="manual",
                        status="paid" if offset_days > 30 else "sent",
                        created_by=owner,
                    )
                    invoice_num += 1
                    created_count += 1

            elif story == "high_margin":
                # Single fat advisory invoice
                amt = Decimal(str(round(max(worked_amt * 1.8, 8500), 2)))
                Invoice.objects.create(
                    org=org, client=client,
                    invoice_number=f"INV-{invoice_num}",
                    invoice_date=today - timedelta(days=15),
                    amount=amt,
                    hours_billed=Decimal(str(round(worked_hrs, 1))),
                    client_code=client.code, client_name=client.name,
                    source="manual", status="sent",
                    created_by=owner,
                )
                invoice_num += 1
                created_count += 1

            elif story == "aged_wip":
                # No invoice — leave WIP to age
                pass

            elif story == "under_billed":
                # Hours are way more than what gets billed
                amt = Decimal(str(round(worked_amt * 0.62, 2)))
                hrs = Decimal(str(round(worked_hrs * 0.62, 1)))
                # Two installments
                for offset, frac in [(50, 0.5), (15, 0.5)]:
                    Invoice.objects.create(
                        org=org, client=client,
                        invoice_number=f"INV-{invoice_num}",
                        invoice_date=today - timedelta(days=offset),
                        amount=amt * Decimal(str(frac)),
                        hours_billed=hrs * Decimal(str(frac)),
                        client_code=client.code, client_name=client.name,
                        source="manual",
                        status="paid" if offset > 30 else "sent",
                        created_by=owner,
                    )
                    invoice_num += 1
                    created_count += 1

            elif story == "small":
                Invoice.objects.create(
                    org=org, client=client,
                    invoice_number=f"INV-{invoice_num}",
                    invoice_date=today - timedelta(days=25),
                    amount=Decimal(str(round(max(worked_amt * 1.05, 850), 2))),
                    hours_billed=Decimal(str(round(worked_hrs, 1))),
                    client_code=client.code, client_name=client.name,
                    source="manual", status="paid",
                    created_by=owner,
                )
                invoice_num += 1
                created_count += 1

        self.stdout.write(self.style.SUCCESS(f"  ✓ {created_count} invoices created"))

        # Mark some blocks as approved+invoiced so WIP analytics light up
        self._mark_block_states(org, clients, users)

    def _mark_block_states(self, org, clients, users):
        """
        Mark block states for the WIP / approval / invoice cycle KPIs:
          - All blocks > 14 days old: approved
          - aged_wip clients: approved but NOT invoiced (creates WIP age)
          - other clients: blocks paired with their invoice → invoiced=True
        """
        self.stdout.write("Setting block approval/invoice states...")
        today = timezone.now().date()
        approve_cutoff = today - timedelta(days=14)
        owner = users["sarah.chen"]

        # Approve all blocks older than 14 days
        approved_count = Block.objects.filter(
            org=org, day__lte=approve_cutoff, approved=False,
        ).update(
            approved=True,
            approved_at=timezone.now() - timedelta(days=10),
            approved_by=owner,
        )

        # Mark blocks invoiced for non-aged-WIP, non-under_billed clients
        invoiced_clients = [
            c for c in clients
            if c._story not in ("aged_wip",)
        ]
        invoiced_block_count = 0
        for client in invoiced_clients:
            qs = Block.objects.filter(
                org=org, client=client, approved=True, invoiced=False,
                day__lte=today - timedelta(days=20),
            )
            if client._story == "under_billed":
                # Only invoice ~65% of approved blocks
                ids = list(qs.values_list("id", flat=True))
                random.shuffle(ids)
                ids = ids[: int(len(ids) * 0.65)]
                qs = Block.objects.filter(id__in=ids)
            updated = qs.update(
                invoiced=True,
                invoiced_at=timezone.now() - timedelta(days=8),
            )
            invoiced_block_count += updated

        self.stdout.write(self.style.SUCCESS(
            f"  ✓ {approved_count:,} blocks approved · {invoiced_block_count:,} marked invoiced"
        ))

    # ── timesheets ───────────────────────────────────────────────────────
    def _create_timesheets(self, org, users):
        """
        Create timesheets for each user × each week, with status that drives
        the compliance KPI.

        Story:
          - sarah, marcus, david, priya, emily: submit on time
          - jenna: usually on time, occasionally late
          - tyler: chronically late (60%) — flagged in compliance dashboard
          - ben: always submits on time (admin)
        """
        self.stdout.write("Creating timesheets...")

        today = timezone.now().date()
        # Find Monday of the week containing 90 days ago
        oldest = today - timedelta(days=90)
        start_monday = oldest - timedelta(days=oldest.weekday())

        weeks = []
        cur = start_monday
        # Stop at the most recent COMPLETED week
        while cur + timedelta(days=6) < today:
            weeks.append(cur)
            cur += timedelta(days=7)

        late_profile = {
            "sarah.chen":       0.05,
            "marcus.webb":      0.10,
            "jenna.park":       0.25,
            "david.okonkwo":    0.10,
            "priya.raman":      0.15,
            "tyler.brooks":     0.60,   # ← chronic offender
            "emily.castellanos":0.10,
            "ben.holloway":     0.00,
        }

        created_count = 0
        for username in [s[0] for s in STAFF]:
            user = users[username]
            late_rate = late_profile[username]

            for week_start in weeks:
                week_end = week_start + timedelta(days=6)
                # Decide: submitted on time / late / not submitted
                roll = random.random()
                is_late = roll < late_rate
                # 5% chance not submitted at all (unless tyler, then higher)
                missing_chance = 0.20 if username == "tyler.brooks" else 0.04
                is_missing = roll < missing_chance

                ts, created = Timesheet.objects.get_or_create(
                    org=org, user=user, week_start=week_start,
                    defaults={"status": "draft"},
                )
                if not created:
                    continue

                # Recalc totals from blocks
                blocks = Block.objects.filter(
                    org=org, user=user, day__gte=week_start, day__lte=week_end,
                )
                total_min = sum(b.minutes or 0 for b in blocks)
                bill_min = sum((b.minutes or 0) for b in blocks if b.is_billable)
                total_amt = sum(float(b.billing_amount or 0) for b in blocks)

                ts.total_hours = Decimal(str(round(total_min / 60, 2)))
                ts.billable_hours = Decimal(str(round(bill_min / 60, 2)))
                ts.non_billable_hours = ts.total_hours - ts.billable_hours
                ts.total_amount = Decimal(str(round(total_amt, 2)))

                if is_missing:
                    ts.status = "draft"  # Never submitted
                else:
                    if is_late:
                        # Submitted 5–14 days after week end (past 2-day grace)
                        offset = random.randint(5, 14)
                    else:
                        # Submitted within grace (0–2 days after week end)
                        offset = random.randint(0, 2)

                    submit_date = week_end + timedelta(days=offset)
                    if submit_date > today:
                        submit_date = today

                    submit_dt = timezone.make_aware(
                        datetime.combine(submit_date, time(17, 0)),
                        timezone.get_current_timezone(),
                    )
                    ts.status = "approved"
                    ts.submitted_at = submit_dt
                    ts.approved_at = submit_dt + timedelta(hours=18)
                    ts.approved_by = users["sarah.chen"]

                ts.save()

                # Link blocks to the timesheet
                Block.objects.filter(
                    org=org, user=user, day__gte=week_start, day__lte=week_end,
                ).update(timesheet=ts)

                created_count += 1

        self.stdout.write(self.style.SUCCESS(f"  ✓ {created_count} timesheets created"))

    # ── summary ──────────────────────────────────────────────────────────
    def _summary(self, org, n_users, n_clients, n_blocks, password):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 64))
        self.stdout.write(self.style.SUCCESS(f"  Demo organization created: {org.name}"))
        self.stdout.write(self.style.SUCCESS("=" * 64))
        self.stdout.write("")
        self.stdout.write(f"  Org slug:    {org.slug}")
        self.stdout.write(f"  Org ID:      {org.id}")
        self.stdout.write(f"  Plan:        {org.plan}")
        self.stdout.write(f"  Staff:       {n_users}")
        self.stdout.write(f"  Clients:     {n_clients}")
        self.stdout.write(f"  Blocks:      {n_blocks:,}")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("  LOGIN AS THE OWNER:"))
        self.stdout.write(f"     Username:  {DEMO_OWNER_USERNAME}")
        self.stdout.write(f"     Email:     {DEMO_OWNER_EMAIL}")
        self.stdout.write(f"     Password:  {password}")
        self.stdout.write("")
        self.stdout.write("  Demo story planted in the analytics:")
        self.stdout.write("     • Hartwell Mfg     → over-serviced (negative margin)")
        self.stdout.write("     • Linwood/Riverstone → aged WIP 60+ days")
        self.stdout.write("     • Crestmoor Medical → poor realization (~65%)")
        self.stdout.write("     • Tyler Brooks      → chronically late timesheets (60%)")
        self.stdout.write("     • Sarah Chen        → low utilization (partner)")
        self.stdout.write("     • Jenna Park        → over-utilized (90%+)")
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("  Done."))
        self.stdout.write("")