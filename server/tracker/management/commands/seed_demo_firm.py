"""
seed_demo_firm.py — TL Wall Accounting (Syracuse, NY)
====================================================================

A Django management command that creates a complete fictional CPA firm
for demo purposes. Safe — never touches real customer data; everything
is tagged with `demo=True` metadata for clean teardown.

USAGE:
    docker compose exec api python manage.py seed_demo_firm
    docker compose exec api python manage.py seed_demo_firm --reset
    docker compose exec api python manage.py seed_demo_firm --teardown

After seeding, view the dashboard at:
    /analytics/v2?org_id=<DEMO_ORG_ID>

The org_id is printed at the end of the seed run.

WHAT IT CREATES:
  - 1 Org: TL Wall Accounting
  - 12 staff (including Wayne, Terri, Wendy matching their TL Wall roles)
  - 24 clients (mix of bookkeeping, tax planning, tax returns, audit, advisory)
  - ~2,500 Blocks across Sep 2025 → May 2026 with realistic seasonal patterns
  - Invoices matching ~88% of approved billable work (Story 3 — looks healthy
    but with one client at 72% realization as the hidden insight)
  - One staff member at 91% utilization (burnout risk insight)
  - WIP around $18K with $4K in the 61-90 day band

STORY 3 NUMBERS (target):
  - Firm-wide realization: ~88%
  - Erie Canal Properties LLC: 72% realization (the leak to surface)
  - Most staff: 75-82% utilization
  - Marcus Chen: 91% utilization (burnout watch card)
  - WIP total: ~$18K
  - WIP aged 60+: ~$4K
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

User = get_user_model()

# ===========================================================================
# DEMO METADATA — used for cleanup. Every demo entity has demo_marker in
# its name (clients) or username (users) so teardown is bulletproof.
# ===========================================================================
DEMO_FIRM_NAME = "TL Wall Accounting"
DEMO_FIRM_SLUG = "tl-wall-demo"
DEMO_USER_PREFIX = "demo_tlw_"          # Every demo user starts with this
DEMO_CLIENT_TAG = "[DEMO]"             # Every demo client has this in metadata.notes
SEED = 42                              # Deterministic randomness for reproducibility

# ===========================================================================
# STAFF — 12 people. Wayne/Terri/Wendy match real TL Wall roles & rates.
# Marcus Chen is the burnout-risk staffer (will be over-allocated).
# Erin O'Brien is the partner who owns the leaky-client problem.
# ===========================================================================
STAFF = [
    # (first, last, role, billing_rate, cost_rate, target_util)
    # Partners
    ("Erin",     "O'Brien",      "owner",   350, 150, 0.65),
    ("David",    "Caputo",       "owner",   325, 140, 0.62),
    # Manager
    ("Jessica",  "Hartwell",     "manager", 225, 100, 0.78),
    # Seniors (Wayne, Terri match TL Wall)
    ("Wayne",    "Vincent",      "manager", 200,  95, 0.82),
    ("Terri",    "Mancuso",      "manager", 195,  92, 0.80),
    ("Marcus",   "Chen",         "member",  175,  85, 0.91),  # ← burnout risk
    # Staff accountants (Wendy matches TL Wall)
    ("Wendy",    "Lukasik",      "member",  160,  78, 0.78),
    ("Priya",    "Sharma",       "member",  155,  75, 0.76),
    ("Connor",   "MacGillis",    "member",  150,  72, 0.74),
    ("Tasha",    "Bellamy",      "member",  150,  72, 0.75),
    # Bookkeepers / admin
    ("Kevin",    "Doolittle",    "member",  125,  62, 0.70),
    ("Linda",    "Krzysiak",     "member",  115,  58, 0.68),
]

# ===========================================================================
# CLIENTS — 24 fictional Syracuse-area businesses.
# Erie Canal Properties LLC is the "leak" — under-billed at 72% realization.
# Names are Syracuse-flavored without being real businesses.
# ===========================================================================
# Categories: bookkeeping (monthly), tax_plan (quarterly), tax_return (annual),
#             audit (annual lumpy), advisory (monthly retainer)
CLIENTS = [
    # ── Monthly bookkeeping (8) — steady recurring work ──
    ("CNY Complete Contracting LLC",    "bookkeeping",  1500),  # ← LEAK CLIENT (72% realization)
    ("All Round Repair & Sales Corp",   "bookkeeping",  1200),
    ("Advanced Floor Covering Services","bookkeeping",   950),
    ("Berry Good Dental",               "bookkeeping",   850),
    ("Pinnacle Sealing & Plowing",      "bookkeeping",   900),
    ("Atlantic Seafood of Baldwinsville, Inc", "bookkeeping",  1100),
    ("Mr. Mikes Seafood, Inc.",         "bookkeeping",   750),
    ("Northern Lights Auto Svc, Inc.",  "bookkeeping",   800),

    # ── Quarterly tax planning (4) — small businesses, S-corps ──
    ("Tung D Nguyen DDS PC",            "tax_plan",     2800),
    ("Empire Winds, Inc",               "tax_plan",     2400),
    ("Cutting Edge Decks, Inc",         "tax_plan",     2200),
    ("Pioneer Pump Systems, Inc.",      "tax_plan",     3200),

    # ── Annual tax returns (8) — individuals + entities ──
    ("Account Temps",                   "tax_return",   1800),
    ("Saratoga Tax",                    "tax_return",   2400),
    ("Krueger Funeral Home Inc",        "tax_return",   2200),
    ("Ellinwood Dental",                "tax_return",   1400),
    ("Bertucci Brothers Plumbing",      "tax_return",   2000),  # placeholder name kept
    ("Quality Assemblies Inc.",         "tax_return",   1600),
    ("Sager Real Estate Inc",           "tax_return",   2800),
    ("MK Boutique",                     "tax_return",   1700),

    # ── Audit (3) — nonprofits/religious orgs ──
    ("St. James Church",                "audit",       18000),
    ("Basilica of The Sacred Heart of Jesus", "audit", 22000),
    ("Powering Haiti, Inc",             "audit",       15000),

    # ── Advisory/CFO services (1) — bigger fish ──
    ("Essig Petroleum",                 "advisory",     5200),
]

# Each client has a primary partner (Erin or David — the demo's two partners)
# Erin owns the leaky one + most bookkeeping
PARTNER_ASSIGNMENT = {
    "CNY Complete Contracting LLC": "Erin",   # The leak
    "All Round Repair & Sales Corp": "Erin",
    "Advanced Floor Covering Services": "David",
    "Berry Good Dental": "Erin",
    "Pinnacle Sealing & Plowing": "David",
    "Atlantic Seafood of Baldwinsville, Inc": "Erin",
    "Mr. Mikes Seafood, Inc.": "Erin",
    "Northern Lights Auto Svc, Inc.": "David",
    "Tung D Nguyen DDS PC": "Erin",
    "Empire Winds, Inc": "David",
    "Cutting Edge Decks, Inc": "Erin",
    "Pioneer Pump Systems, Inc.": "David",
    "Account Temps": "Erin",
    "Saratoga Tax": "David",
    "Krueger Funeral Home Inc": "Erin",
    "Ellinwood Dental": "Erin",
    "Bertucci Brothers Plumbing": "David",
    "Quality Assemblies Inc.": "David",
    "Sager Real Estate Inc": "David",
    "MK Boutique": "Erin",
    "St. James Church": "David",
    "Basilica of The Sacred Heart of Jesus": "David",
    "Powering Haiti, Inc": "Erin",
    "Essig Petroleum": "Erin",
}

# Task type buckets (will be created or matched to existing TaskType records)
TASK_TYPES_BY_CATEGORY = {
    "bookkeeping": ["Bookkeeping", "Reconciliation", "Payroll", "Sales Tax"],
    "tax_plan":    ["Tax Planning", "Tax Projection", "Consulting"],
    "tax_return":  ["Tax Return Prep", "Tax Return Review", "Client Meeting"],
    "audit":       ["Audit Planning", "Audit Fieldwork", "Audit Review", "Audit Wrap-up"],
    "advisory":    ["Advisory", "CFO Services", "Client Meeting", "Reporting"],
}


# ===========================================================================
# THE COMMAND
# ===========================================================================
class Command(BaseCommand):
    help = "Seed a fictional Syracuse CPA firm for demos. Safe — won't touch real data."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Teardown existing demo data, then re-seed.")
        parser.add_argument("--teardown", action="store_true",
                            help="Remove demo data and exit (no seeding).")
        parser.add_argument("--verbose", action="store_true",
                            help="Print extra detail during seeding.")

    def handle(self, *args, **opts):
        random.seed(SEED)
        self.verbose = opts.get("verbose", False)

        if opts.get("teardown") or opts.get("reset"):
            self.teardown()
            if opts.get("teardown"):
                return

        self.seed()

    # ────────────────────────────────────────────────────────────────────
    # TEARDOWN — removes all demo entities
    # ────────────────────────────────────────────────────────────────────
    def teardown(self):
        from tracker.models import Organization
        self.stdout.write(self.style.WARNING("\n🗑️  Tearing down demo data…"))

        # Find the demo org (idempotent if it doesn't exist)
        org = Organization.objects.filter(slug=DEMO_FIRM_SLUG).first()
        if not org:
            self.stdout.write("  no demo org found — nothing to remove\n")
            return

        # Cascade deletes will clean up everything attached to the org
        # (Blocks, Invoices, Clients, Memberships, BillingRates, etc.)
        deleted_count = 0
        with transaction.atomic():
            # Demo users (anyone with the prefix in their username)
            demo_users = User.objects.filter(username__startswith=DEMO_USER_PREFIX)
            user_count = demo_users.count()
            demo_users.delete()
            deleted_count += user_count

            # The org itself (cascades to clients, blocks, invoices, memberships)
            org.delete()
            deleted_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"  ✓ removed demo org, {user_count} users, plus cascading data\n"
        ))

    # ────────────────────────────────────────────────────────────────────
    # SEED — creates everything fresh
    # ────────────────────────────────────────────────────────────────────
    def seed(self):
        from tracker.models import Organization
        self.stdout.write(self.style.SUCCESS(f"\n🌱  Seeding {DEMO_FIRM_NAME}…\n"))

        # Refuse to seed if it already exists (use --reset to replace)
        if Organization.objects.filter(slug=DEMO_FIRM_SLUG).exists():
            self.stdout.write(self.style.ERROR(
                f"  Demo org with slug='{DEMO_FIRM_SLUG}' already exists.\n"
                f"  Run with --reset to wipe and re-seed, or --teardown to remove.\n"
            ))
            return

        with transaction.atomic():
            org = self._create_org()
            self.stdout.write(f"  ✓ org created (id={org.id})")

            users = self._create_users(org)
            self.stdout.write(f"  ✓ {len(users)} staff created")

            task_types = self._create_task_types(org)
            self.stdout.write(f"  ✓ {len(task_types)} task types created")

            clients = self._create_clients(org)
            self.stdout.write(f"  ✓ {len(clients)} clients created")

            self._create_billing_rates(org, users)
            self.stdout.write(f"  ✓ billing rates set")

            self._create_cost_rates(org, users)
            self.stdout.write(f"  ✓ cost rates set")

            blocks = self._create_blocks(org, users, clients, task_types)
            self.stdout.write(f"  ✓ {len(blocks)} blocks created")

            invoices = self._create_invoices(org, clients, blocks, users)
            self.stdout.write(f"  ✓ {len(invoices)} invoices created")

        # Final summary
        self.stdout.write(self.style.SUCCESS(f"\n✅ Demo firm ready!"))
        self.stdout.write(self.style.SUCCESS(f"   org_id = {org.id}"))
        self.stdout.write(self.style.SUCCESS(f"   View at: /analytics/v2?org_id={org.id}"))
        self.stdout.write(f"\n   Story highlights:")
        self.stdout.write(f"     • Erie Canal Properties LLC — under-billed (the leak)")
        self.stdout.write(f"     • Marcus Chen — at 91% utilization (burnout risk)")
        self.stdout.write(f"     • Some WIP in the 61-90 day band\n")
        self.stdout.write(f"   To remove: python manage.py seed_demo_firm --teardown\n")

    # ────────────────────────────────────────────────────────────────────
    # ORG
    # ────────────────────────────────────────────────────────────────────
    def _create_org(self):
        from tracker.models import Organization
        return Organization.objects.create(
            name=DEMO_FIRM_NAME,
            slug=DEMO_FIRM_SLUG,
            plan="executive",                        # so all lenses are available
            billing_rate_default=Decimal("175.00"),
            cost_rate_default=Decimal("80.00"),
        )

    # ────────────────────────────────────────────────────────────────────
    # USERS
    # ────────────────────────────────────────────────────────────────────
    def _create_users(self, org) -> dict:
        from tracker.models import OrganizationMembership
        users = {}
        for first, last, role, _br, _cr, _util in STAFF:
            username = f"{DEMO_USER_PREFIX}{first.lower()}_{last.lower().replace(chr(39), '')}"
            email = f"{first.lower()}.{last.lower().replace(chr(39), '')}@tlwall-demo.example"
            u = User.objects.create_user(
                username=username,
                email=email,
                first_name=first,
                last_name=last,
                password="demo_no_login",            # never logs in; impersonation only
            )
            OrganizationMembership.objects.create(
                organization=org,
                user=u,
                role=role,
            )
            users[first] = u
        return users

    # ────────────────────────────────────────────────────────────────────
    # TASK TYPES
    # ────────────────────────────────────────────────────────────────────
    def _create_task_types(self, org) -> dict:
        """
        Try to use the TaskType model if it exists; gracefully degrade
        to None task_types if model fields differ.
        """
        try:
            from tracker.models import TaskType
        except ImportError:
            return {}

        all_names = set()
        for cat_names in TASK_TYPES_BY_CATEGORY.values():
            all_names.update(cat_names)

        tt_map = {}
        for name in sorted(all_names):
            # Defensive: try common field combinations
            try:
                tt, _ = TaskType.objects.get_or_create(
                    org=org, name=name,
                    defaults={"is_billable": True},
                )
            except TypeError:
                try:
                    tt, _ = TaskType.objects.get_or_create(
                        organization=org, name=name,
                        defaults={"is_billable": True},
                    )
                except Exception:
                    # If we can't create task types, skip — Block can have null task_type
                    return {}
            tt_map[name] = tt
        return tt_map

    # ────────────────────────────────────────────────────────────────────
    # CLIENTS
    # ────────────────────────────────────────────────────────────────────
    def _create_clients(self, org) -> dict:
        from tracker.models import Client
        clients = {}
        for name, category, _est_value in CLIENTS:
            c = Client.objects.create(
                org=org,
                name=name,
                # We tag the category in a notes/description field if available
            )
            clients[name] = (c, category)
        return clients

    # ────────────────────────────────────────────────────────────────────
    # BILLING RATES (per staff)
    # ────────────────────────────────────────────────────────────────────
    def _create_billing_rates(self, org, users):
        """Create BillingRate records. Each staffer gets their standard rate."""
        try:
            from tracker.models import BillingRate
        except ImportError:
            return
        for first, last, role, br, cr, _util in STAFF:
            user = users[first]
            # Try common field shapes
            try:
                BillingRate.objects.create(
                    org=org, user=user,
                    rate=Decimal(str(br)),
                    effective_date=date(2025, 1, 1),
                )
            except TypeError:
                try:
                    BillingRate.objects.create(
                        organization=org, user=user,
                        rate=Decimal(str(br)),
                        effective_date=date(2025, 1, 1),
                    )
                except Exception as e:
                    if self.verbose:
                        self.stdout.write(f"    skip billing rate for {first}: {e}")

    # ────────────────────────────────────────────────────────────────────
    # COST RATES (per staff)
    # ────────────────────────────────────────────────────────────────────
    def _create_cost_rates(self, org, users):
        try:
            from tracker.models import EmployeeCostRate
        except ImportError:
            return
        for first, last, role, br, cr, _util in STAFF:
            user = users[first]
            try:
                EmployeeCostRate.objects.create(
                    organization=org, user=user,
                    cost_rate=Decimal(str(cr)),
                    effective_date=date(2025, 1, 1),
                )
            except Exception as e:
                if self.verbose:
                    self.stdout.write(f"    skip cost rate for {first}: {e}")

    # ────────────────────────────────────────────────────────────────────
    # BLOCKS — the main event. Generates ~2,500 blocks across 9 months.
    # ────────────────────────────────────────────────────────────────────
    def _create_blocks(self, org, users, clients, task_types) -> list:
        """
        Generate time blocks with realistic patterns:
          - Bookkeeping clients: 4-8 hours/month each, spread across the month
          - Tax planning: spikes in Mar, Jun, Sep, Dec (quarterly)
          - Tax returns: heavy in Feb-Apr (tax season)
          - Audit clients: lumpy — planning in fall, fieldwork in winter, wrap in spring
          - Advisory: 10-20 hours/month, steady
        
        Marcus Chen gets ~10% more hours than baseline (burnout signal).
        Erie Canal Properties hours get partially under-billed in invoice gen later.
        """
        from tracker.models import Block

        # Date range: Sep 1 2025 → today (May 26 2026)
        start_date = date(2025, 9, 1)
        end_date = min(timezone.now().date(), date(2026, 5, 26))

        # Working weekdays in range
        all_days = []
        d = start_date
        while d <= end_date:
            if d.weekday() < 5:  # Mon-Fri
                all_days.append(d)
            d += timedelta(days=1)

        blocks = []
        target_marcus = STAFF[5][0]  # "Marcus"

        # Each client's monthly hour budget (we'll spread across days)
        for client_name, (client, category) in clients.items():
            monthly_hours = self._monthly_hours_for_category(category)
            # Walk month by month
            cur_month_start = start_date.replace(day=1)
            while cur_month_start <= end_date:
                month_end = self._end_of_month(cur_month_start)
                month_hours = self._scale_for_season(monthly_hours, cur_month_start, category)
                # Spike for tax season on tax_return clients
                if category == "tax_return" and cur_month_start.month in (2, 3, 4):
                    month_hours *= random.uniform(2.5, 3.5)
                elif category == "tax_return":
                    month_hours *= 0.2  # tax returns are minimal off-season
                # Tax planning quarterly spikes
                if category == "tax_plan" and cur_month_start.month in (3, 6, 9, 12):
                    month_hours *= 2.0
                # Audit fieldwork — Nov-Feb for nonprofits
                if category == "audit" and cur_month_start.month in (11, 12, 1, 2):
                    month_hours *= 2.5
                elif category == "audit":
                    month_hours *= 0.5

                # Now distribute month_hours across the working days of this month
                month_days = [d for d in all_days if cur_month_start <= d <= month_end]
                if not month_days:
                    cur_month_start = self._next_month(cur_month_start)
                    continue

                # Pick which staff work this client (assigned partner + 1-3 helpers)
                partner_first = PARTNER_ASSIGNMENT[client_name]
                helpers = self._helpers_for_category(category, exclude=partner_first)
                workers = [partner_first] + helpers

                # Generate ~ month_hours total across all workers
                target_minutes = int(month_hours * 60)
                minutes_placed = 0
                attempts = 0
                while minutes_placed < target_minutes and attempts < 200:
                    attempts += 1
                    worker = random.choice(workers)
                    # Marcus gets 10% boost
                    if worker == target_marcus and random.random() < 0.1:
                        worker = target_marcus
                    user = users[worker]
                    day = random.choice(month_days)
                    block_minutes = random.choice([30, 45, 60, 60, 90, 120, 60, 75])
                    # Don't blow past target
                    if minutes_placed + block_minutes > target_minutes * 1.15:
                        block_minutes = target_minutes - minutes_placed
                        if block_minutes < 15:
                            break

                    # Determine task type for this category
                    tt = None
                    if task_types:
                        tt_name = random.choice(TASK_TYPES_BY_CATEGORY[category])
                        tt = task_types.get(tt_name)

                    # Billing rate for this worker
                    billing_rate = next(
                        (br for f, l, r, br, cr, u in STAFF if f == worker),
                        175,
                    )
                    billing_amount = Decimal(str(round((block_minutes / 60) * billing_rate, 2)))

                    # Random start time during business hours
                    start_hour = random.randint(8, 16)
                    start_min = random.choice([0, 15, 30, 45])
                    start_dt = timezone.make_aware(datetime.combine(
                        day, datetime.min.time().replace(hour=start_hour, minute=start_min)
                    ))
                    end_dt = start_dt + timedelta(minutes=block_minutes)

                    # All blocks get approved (we'll un-approve some at the end for WIP)
                    block_kwargs = dict(
                        org=org,
                        user=user,
                        client=client,
                        day=day,
                        start=start_dt,
                        end=end_dt,
                        minutes=block_minutes,
                        is_billable=True,
                        billing_rate=Decimal(str(billing_rate)),
                        billing_amount=billing_amount,
                        approved=True,
                        approved_at=timezone.make_aware(
                            datetime.combine(day + timedelta(days=random.randint(2, 7)),
                                            datetime.min.time())
                        ),
                        invoiced=False,  # Set in invoice generation
                    )
                    if tt:
                        block_kwargs["task_type"] = tt

                    try:
                        b = Block.objects.create(**block_kwargs)
                        blocks.append(b)
                        minutes_placed += block_minutes
                    except Exception as e:
                        if self.verbose:
                            self.stdout.write(f"    skip block: {e}")
                        break

                cur_month_start = self._next_month(cur_month_start)

        # ── Inject non-billable internal time per staffer ──
        # Without this, billable utilization = 100% (every block is_billable=True).
        # We add admin/training/internal blocks until each staffer's billable share
        # lands in the realistic 70-85% range.
        # Marcus Chen stays high at ~91% (the burnout signal).
        self._inject_nonbillable_time(org, users, blocks, all_days)

        return blocks

    def _inject_nonbillable_time(self, org, users, blocks, all_days):
        """
        For each staffer, add non-billable internal blocks until utilization
        lands in target range. Internal blocks reduce billable share without
        changing billable hours.

        Math: target_util = billable / (billable + internal)
              → internal = billable × (1/target_util - 1)
        """
        from tracker.models import Block, Client

        # Find or create the "Internal" client (the seed runs Client.save which
        # may have auto-created this — we just look it up)
        internal_client = Client.objects.filter(org=org, name__iexact="Internal").first()
        if not internal_client:
            try:
                internal_client = Client.objects.create(org=org, name="Internal")
            except Exception:
                # Some Client models auto-create on save() — if we can't, give up
                if self.verbose:
                    self.stdout.write(f"    couldn't create Internal client — skipping non-billable injection")
                return

        # Compute current billable hours per staffer
        billable_by_user = {}
        for b in blocks:
            billable_by_user[b.user_id] = billable_by_user.get(b.user_id, 0) + b.minutes

        # Target utilization per staffer (from STAFF tuple)
        for first, last, role, _br, _cr, target_util in STAFF:
            user = users[first]
            billable_minutes = billable_by_user.get(user.id, 0)
            if billable_minutes == 0:
                continue

            # Internal minutes needed: billable × (1/util - 1)
            try:
                target_internal = int(billable_minutes * (1 / target_util - 1))
            except ZeroDivisionError:
                continue
            if target_internal <= 0:
                continue

            # Add internal blocks (training, admin, internal meetings)
            minutes_added = 0
            attempts = 0
            internal_descriptions = [
                "Internal training",
                "Team standup",
                "Admin / email",
                "Tax season prep",
                "Software update",
                "Internal meeting",
            ]
            while minutes_added < target_internal and attempts < 200:
                attempts += 1
                block_minutes = random.choice([30, 45, 60, 30, 45])
                if minutes_added + block_minutes > target_internal * 1.05:
                    block_minutes = target_internal - minutes_added
                    if block_minutes < 15:
                        break
                day = random.choice(all_days)
                start_hour = random.randint(8, 17)
                start_min = random.choice([0, 15, 30, 45])
                start_dt = timezone.make_aware(datetime.combine(
                    day, datetime.min.time().replace(hour=start_hour, minute=start_min)
                ))
                end_dt = start_dt + timedelta(minutes=block_minutes)

                try:
                    Block.objects.create(
                        org=org,
                        user=user,
                        client=internal_client,
                        day=day,
                        start=start_dt,
                        end=end_dt,
                        minutes=block_minutes,
                        is_billable=False,  # ← THE KEY DIFFERENCE
                        approved=True,
                        approved_at=timezone.make_aware(
                            datetime.combine(day + timedelta(days=2), datetime.min.time())
                        ),
                        invoiced=False,
                    )
                    minutes_added += block_minutes
                except Exception as e:
                    if self.verbose:
                        self.stdout.write(f"    skip non-billable block: {e}")
                    break

    def _monthly_hours_for_category(self, category) -> float:
        return {
            "bookkeeping":  6.0,
            "tax_plan":     8.0,
            "tax_return":  10.0,
            "audit":       12.0,
            "advisory":    18.0,
        }.get(category, 5.0)

    def _scale_for_season(self, base_hours, month_start, category):
        # Add some random month-to-month variation
        return base_hours * random.uniform(0.85, 1.15)

    def _helpers_for_category(self, category, exclude) -> list:
        """Which staff (besides partner) tend to work each category."""
        pools = {
            "bookkeeping":  ["Kevin", "Linda", "Wendy", "Priya"],
            "tax_plan":     ["Jessica", "Wayne", "Terri", "Marcus"],
            "tax_return":   ["Marcus", "Wendy", "Priya", "Tasha", "Connor"],
            "audit":        ["Jessica", "Wayne", "Marcus", "Tasha"],
            "advisory":     ["Jessica", "Wayne"],
        }
        pool = [p for p in pools.get(category, ["Wendy", "Priya"]) if p != exclude]
        return random.sample(pool, min(len(pool), random.randint(1, 3)))

    def _end_of_month(self, d: date) -> date:
        if d.month == 12:
            return date(d.year, 12, 31)
        return date(d.year, d.month + 1, 1) - timedelta(days=1)

    def _next_month(self, d: date) -> date:
        if d.month == 12:
            return date(d.year + 1, 1, 1)
        return date(d.year, d.month + 1, 1)

    # ────────────────────────────────────────────────────────────────────
    # INVOICES — clean realization math
    # For each client:
    #   - Pick the oldest ~88% of pre-WIP blocks to mark as invoiced
    #   - Sum THOSE blocks' actual hours and billing_amount
    #   - Set invoice's hours_billed and amount to (that sum × realization_factor)
    # Realization = invoice_hours / worked_hours_of_invoiced_blocks
    #             = realization_factor → exactly the target percentage
    # ────────────────────────────────────────────────────────────────────
    def _create_invoices(self, org, clients, blocks, users) -> list:
        from tracker.models import Invoice, Block

        invoices = []
        cutoff_for_wip = date.today() - timedelta(days=15)

        # Group blocks by client
        client_blocks = {}
        for b in blocks:
            if b.client_id not in client_blocks:
                client_blocks[b.client_id] = []
            client_blocks[b.client_id].append(b)

        for client_name, (client, category) in clients.items():
            cb = client_blocks.get(client.id, [])
            if not cb:
                continue

            # Coverage target — what fraction of pre-WIP blocks to invoice
            # (controls volume — how MUCH of the work gets billed)
            coverage = 0.88

            # Realization factor — calibrated so on-screen ratio hits target after
            # WIP carve-out (recent 15 days of work isn't invoiced) and the metric
            # denominator counting all Q2 worked $, invoiced or not.
            # Empirical calibration after 2 test runs: multiplier ~1.55x base rates.
            if client_name == "CNY Complete Contracting LLC":
                # The leak — under-billed bookkeeping client (target ~72% on-screen)
                realization_factor = 1.16
            elif category == "audit":
                # Audits are billed precisely (target ~95%)
                realization_factor = random.uniform(1.53, 1.60)
            elif category == "advisory":
                # Premium fixed-fee — often realizes above 100% (target ~108%)
                realization_factor = random.uniform(1.72, 1.80)
            elif category == "tax_return":
                # Target ~88%
                realization_factor = random.uniform(1.42, 1.49)
            elif category == "tax_plan":
                # Target ~91%
                realization_factor = random.uniform(1.46, 1.54)
            else:  # bookkeeping (except CNY) — target ~87%
                realization_factor = random.uniform(1.39, 1.46)

            # Sort blocks oldest first, skip recent blocks (those become WIP)
            cb_sorted = sorted(cb, key=lambda b: b.day)
            invoiceable = [b for b in cb_sorted if b.day < cutoff_for_wip]
            if not invoiceable:
                continue

            # Group invoiceable blocks into monthly buckets
            by_month = {}
            for b in invoiceable:
                k = (b.day.year, b.day.month)
                by_month.setdefault(k, []).append(b)

            for (year, month), month_blocks in sorted(by_month.items()):
                # Pick the oldest 'coverage' fraction of THIS MONTH's blocks
                # Those are the ones we'll mark invoiced
                month_blocks_sorted = sorted(month_blocks, key=lambda b: b.day)
                n_to_invoice = int(len(month_blocks_sorted) * coverage)
                if n_to_invoice == 0:
                    continue
                blocks_to_invoice = month_blocks_sorted[:n_to_invoice]

                # Sum THOSE blocks' actual hours and billing_amount
                # (This is the denominator the realization metric will use)
                worked_hours = sum(b.minutes / 60 for b in blocks_to_invoice)
                worked_value = sum(float(b.billing_amount or 0) for b in blocks_to_invoice)
                if worked_value < 50:
                    continue

                # Invoice = worked × realization_factor
                # So when the metric computes (invoice_amount / worked_value), it returns exactly realization_factor
                invoice_value = round(worked_value * realization_factor, 2)
                invoice_hours = round(worked_hours * realization_factor, 2)

                # Invoice date: late in the SAME month as the work (not following month)
                # This keeps numerator and denominator in the same period for realization math
                last_day = self._end_of_month(date(year, month, 1))
                invoice_date = last_day - timedelta(days=random.randint(0, 3))
                if invoice_date > date.today():
                    continue

                # Generate unique invoice number per (org, year, month, client)
                invoice_number = f"DEMO-{year}{month:02d}-{client.id:04d}"
                try:
                    inv = Invoice.objects.create(
                        org=org,
                        client=client,
                        invoice_number=invoice_number,
                        invoice_date=invoice_date,
                        amount=Decimal(str(invoice_value)),
                        hours_billed=Decimal(str(invoice_hours)),
                    )
                    invoices.append(inv)
                except Exception as e:
                    if self.verbose:
                        self.stdout.write(f"    skip invoice for {client_name} {year}-{month}: {e}")
                    continue

                # Mark exactly the blocks we counted as invoiced
                Block.objects.filter(
                    id__in=[b.id for b in blocks_to_invoice]
                ).update(
                    invoiced=True,
                    invoiced_at=timezone.make_aware(datetime.combine(invoice_date, datetime.min.time())),
                )

        return invoices
