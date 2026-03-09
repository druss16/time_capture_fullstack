# tracker/management/commands/verify_analytics.py
"""
Smoke-test every KPI in views_analytics against real database data.

Usage
-----
# Test default org, last 12 months:
python manage.py verify_analytics

# Specific org slug + period:
python manage.py verify_analytics --org tl-wall --period 6m

# Cross-check realization numbers against a specific client:
python manage.py verify_analytics --org tl-wall --client "Smith & Associates"

# Verbose: print every raw query result
python manage.py verify_analytics --verbose
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db.models import Sum, Count, Q
from django.db.models.functions import Coalesce
from django.utils import timezone
from decimal import Decimal
from datetime import date, timedelta

User = get_user_model()

# ── Colours for terminal output ──────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):   print(f"  {GREEN}✓{RESET}  {msg}")
def warn(msg): print(f"  {YELLOW}⚠{RESET}  {msg}")
def fail(msg): print(f"  {RED}✗{RESET}  {msg}")
def info(msg): print(f"  {CYAN}→{RESET}  {msg}")
def head(msg): print(f"\n{BOLD}{msg}{RESET}\n{'─' * 60}")


class Command(BaseCommand):
    help = "Verify every analytics KPI against real database data"

    def add_arguments(self, parser):
        parser.add_argument("--org",     default=None, help="Org slug (default: first org found)")
        parser.add_argument("--period",  default="12m", help="3m | 6m | 12m | ytd")
        parser.add_argument("--client",  default=None, help="Client name to deep-dive")
        parser.add_argument("--verbose", action="store_true", help="Print raw query rows")

    def handle(self, *args, **options):
        from tracker.models import (
            Organization, OrganizationMembership,
            Block, Invoice, Timesheet, EmployeeCostRate, Client,
        )
        from tracker.views_analytics import _parse_period

        org_slug = options["org"]
        period   = options["period"]
        verbose  = options["verbose"]
        target_client = options["client"]

        # ── Resolve org ───────────────────────────────────────────────────
        head("1 / 9  ORGANISATION")
        if org_slug:
            try:
                org = Organization.objects.get(slug=org_slug)
            except Organization.DoesNotExist:
                raise CommandError(f"Org '{org_slug}' not found")
        else:
            org = Organization.objects.first()
            if not org:
                raise CommandError("No organisations in database")

        ok(f"Org: {org.name}  (slug={org.slug}, plan={org.plan})")
        info(f"Billing rate default : ${getattr(org, 'billing_rate_default', '—')}/hr")
        info(f"Cost rate default    : ${getattr(org, 'cost_rate_default',    '—')}/hr")

        member_count = OrganizationMembership.objects.filter(organization=org).count()
        ok(f"Members: {member_count}")
        if member_count == 0:
            warn("No members — utilization & compliance KPIs will be empty")

        # ── Parse period ──────────────────────────────────────────────────
        head("2 / 9  DATE RANGE")
        start_date, end_date = _parse_period(period)
        ok(f"Period '{period}': {start_date} → {end_date}")
        days = (end_date - start_date).days
        info(f"{days} days ({days // 30} months approx)")

        # ── Blocks overview ───────────────────────────────────────────────
        head("3 / 9  BLOCKS")
        all_blocks = Block.objects.filter(org=org, day__gte=start_date, day__lte=end_date)
        total_blocks = all_blocks.count()
        billable_blocks = all_blocks.filter(is_billable=True).count()
        approved_blocks = all_blocks.filter(approved=True).count()
        uninvoiced_blocks = all_blocks.filter(approved=True, invoiced=False, is_billable=True).count()

        ok(f"Total blocks in period    : {total_blocks}")
        ok(f"Billable                  : {billable_blocks}")
        ok(f"Approved                  : {approved_blocks}")
        ok(f"Approved + not invoiced   : {uninvoiced_blocks}  ← feeds WIP")

        agg = all_blocks.aggregate(
            total_mins=Coalesce(Sum("minutes"), 0),
            bill_mins =Coalesce(Sum("minutes", filter=Q(is_billable=True)), 0),
            bill_amt  =Coalesce(Sum("billing_amount"), Decimal("0")),
        )
        total_hrs  = agg["total_mins"] / 60.0
        bill_hrs   = agg["bill_mins"]  / 60.0
        bill_rev   = float(agg["bill_amt"])
        utiliz_pct = (bill_hrs / total_hrs * 100) if total_hrs > 0 else 0

        ok(f"Total tracked hours       : {total_hrs:.1f}h")
        ok(f"Billable hours            : {bill_hrs:.1f}h")
        ok(f"Billable utilization      : {utiliz_pct:.1f}%")
        ok(f"Total billing_amount      : ${bill_rev:,.2f}")

        if total_blocks == 0:
            warn("No blocks found — agent may not be tracking or day field may be null")
        if bill_hrs > 0 and bill_rev == 0:
            warn("billing_amount is $0 — check that billing_rate is set on blocks or org default")

        if verbose:
            for b in all_blocks.select_related("client", "user").order_by("-day")[:10]:
                self.stdout.write(
                    f"    {b.day} | {getattr(b.client,'name','—'):20} | "
                    f"{getattr(b.user,'username','—'):15} | "
                    f"{b.minutes or 0:4}m | ${float(b.billing_amount or 0):8.2f} | "
                    f"billable={b.is_billable} approved={b.approved} invoiced={b.invoiced}"
                )

        # ── Invoices ──────────────────────────────────────────────────────
        head("4 / 9  INVOICES  (feeds Realization & Revenue Trend)")
        invoices = Invoice.objects.filter(org=org, invoice_date__gte=start_date, invoice_date__lte=end_date)
        inv_count = invoices.count()
        inv_agg   = invoices.aggregate(
            total_amount=Coalesce(Sum("amount"),       Decimal("0")),
            total_hours =Coalesce(Sum("hours_billed"), Decimal("0")),
        )
        inv_amt  = float(inv_agg["total_amount"])
        inv_hrs  = float(inv_agg["total_hours"])
        unmatched = invoices.filter(client__isnull=True).count()

        ok(f"Invoice count             : {inv_count}")
        ok(f"Total invoiced amount     : ${inv_amt:,.2f}")
        ok(f"Total invoiced hours      : {inv_hrs:.1f}h")

        if inv_count == 0:
            warn("No invoices → Realization Rate and Revenue Trend will show 0")
            warn("Import invoices via Settings → Invoices (CSV) or QuickBooks sync")
        if unmatched:
            warn(f"{unmatched} invoices have no client matched — realization will miss them")
            warn("Fix via Settings → Invoices → Match Client")

        if verbose:
            for inv in invoices.select_related("client").order_by("-invoice_date")[:10]:
                self.stdout.write(
                    f"    {inv.invoice_date} | {getattr(inv.client,'name','UNMATCHED'):25} | "
                    f"${float(inv.amount):10,.2f} | {float(inv.hours_billed or 0):6.1f}h | {inv.source}"
                )

        # ── Realization per client ────────────────────────────────────────
        head("5 / 9  REALIZATION RATE")
        inv_by_client = {
            r["client_id"]: {
                "name":    r["client__name"],
                "billed":  float(r["billed_hours"] or 0),
                "amount":  float(r["billed_amount"] or 0),
            }
            for r in invoices.filter(client__isnull=False)
                              .values("client_id", "client__name")
                              .annotate(
                                  billed_hours =Coalesce(Sum("hours_billed"), Decimal("0")),
                                  billed_amount=Coalesce(Sum("amount"),       Decimal("0")),
                              )
        }
        wrk_by_client = {
            r["client_id"]: float(r["worked_minutes"] or 0) / 60.0
            for r in all_blocks.filter(is_billable=True, client__isnull=False)
                               .values("client_id")
                               .annotate(worked_minutes=Coalesce(Sum("minutes"), 0))
        }
        all_cids = set(inv_by_client) | set(wrk_by_client)

        if not all_cids:
            warn("No client data for realization — need both invoices AND billable blocks with client assigned")
        else:
            ok(f"Clients with data: {len(all_cids)}")
            for cid in sorted(all_cids, key=lambda c: inv_by_client.get(c, {}).get("amount", 0), reverse=True)[:15]:
                bh = inv_by_client.get(cid, {}).get("billed", 0)
                wh = wrk_by_client.get(cid, 0)
                nm = inv_by_client.get(cid, {}).get("name") or f"client_id={cid}"
                pct = (bh / wh * 100) if wh > 0 else 0
                flag = (
                    f"{GREEN}excellent{RESET}" if pct >= 125 else
                    f"{GREEN}good{RESET}"      if pct >= 100 else
                    f"{YELLOW}warning{RESET}"  if pct >= 85  else
                    f"{RED}critical{RESET}"    if pct > 0    else
                    f"{CYAN}no_invoices{RESET}"
                )
                print(f"    {nm:30} billed={bh:5.1f}h  worked={wh:5.1f}h  realization={pct:6.1f}%  [{flag}]")

                if target_client and target_client.lower() in nm.lower():
                    info(f"  ↳ Deep-dive on '{nm}'")
                    raw_blocks = all_blocks.filter(client_id=cid, is_billable=True).order_by("day")
                    info(f"    {raw_blocks.count()} billable blocks")
                    raw_invoices = invoices.filter(client_id=cid)
                    info(f"    {raw_invoices.count()} invoices  total ${sum(float(i.amount) for i in raw_invoices):,.2f}")

        # ── WIP Pipeline ──────────────────────────────────────────────────
        head("6 / 9  WIP PIPELINE")
        wip_blocks = Block.objects.filter(org=org, approved=True, invoiced=False, is_billable=True)
        wip_count  = wip_blocks.count()
        default_rate = float(getattr(org, "billing_rate_default", 0) or 0)

        wip_total = 0.0
        now = timezone.now()
        buckets = {"0_30": 0.0, "31_60": 0.0, "61_90": 0.0, "90_plus": 0.0}
        for b in wip_blocks.select_related("client"):
            amt = float(b.billing_amount or 0)
            if not amt:
                hrs = float(b.minutes or 0) / 60.0
                rate = float(b.billing_rate or 0) or default_rate
                amt = hrs * rate
            wip_total += amt
            ref = b.approved_at or b.start
            if ref:
                if timezone.is_naive(ref):
                    ref = timezone.make_aware(ref)
                age = (now - ref).days
            else:
                age = 0
            if   age <= 30: buckets["0_30"]    += amt
            elif age <= 60: buckets["31_60"]   += amt
            elif age <= 90: buckets["61_90"]   += amt
            else:           buckets["90_plus"] += amt

        ok(f"WIP blocks (approved, not invoiced): {wip_count}")
        ok(f"WIP total value                    : ${wip_total:,.2f}")
        for bname, bval in buckets.items():
            label = bname.replace("_", "–") + " days"
            color = GREEN if bname == "0_30" else YELLOW if bname == "31_60" else RED
            print(f"    {color}{label:12}{RESET}  ${bval:,.2f}")

        if wip_count == 0:
            warn("No WIP — either all blocks are invoiced, or none are approved yet")
        if wip_total == 0 and wip_count > 0:
            warn("WIP blocks exist but total is $0 — check billing_rate and billing_amount on blocks")

        # ── Employee Cost Rates ───────────────────────────────────────────
        head("7 / 9  EMPLOYEE COST RATES  (feeds Profitability)")
        cost_rates = EmployeeCostRate.objects.filter(organization=org).select_related("user")
        cr_count = cost_rates.count()
        ok(f"Cost rate records: {cr_count}")

        if cr_count == 0:
            warn("No EmployeeCostRate records — profitability will use org default cost rate")
            warn(f"Default cost rate: ${getattr(org, 'cost_rate_default', '—')}/hr")
            warn("Add cost rates via Settings → Team → Cost Rates")
        else:
            for cr in cost_rates.order_by("user__username"):
                ok(f"  {cr.user.username:20}  ${float(cr.cost_rate):8.2f}/hr  eff={cr.effective_date}")

        # ── Timesheets ────────────────────────────────────────────────────
        head("8 / 9  TIMESHEETS  (feeds Compliance & Cycle Time)")
        ts_all = Timesheet.objects.filter(org=org, week_start__gte=start_date, week_start__lte=end_date)
        ts_count = ts_all.count()
        status_breakdown = ts_all.values("status").annotate(n=Count("id")).order_by("status")

        ok(f"Timesheets in period: {ts_count}")
        for row in status_breakdown:
            print(f"    {row['status']:12}  {row['n']}")

        GRACE = 2
        compliant, late = 0, 0
        for ts in ts_all.exclude(status="draft"):
            week_end = ts.week_start + timedelta(days=6)
            deadline = week_end + timedelta(days=GRACE)
            if ts.submitted_at:
                sub = ts.submitted_at.date() if hasattr(ts.submitted_at, "date") else ts.submitted_at
                if sub <= deadline:
                    compliant += 1
                else:
                    late += 1
            else:
                late += 1
        submitted = compliant + late
        ok(f"Compliance (within {GRACE}d of week end): {compliant}/{submitted}  = {(compliant/submitted*100) if submitted else 0:.1f}%")

        # Cycle time sample
        cycle_times = []
        for b in Block.objects.filter(org=org, day__gte=start_date, day__lte=end_date,
                                      invoiced=True, invoiced_at__isnull=False).select_related("timesheet")[:200]:
            ts = b.timesheet
            if ts and ts.approved_at and b.invoiced_at:
                days_ct = (b.invoiced_at - ts.approved_at).days
                if 0 <= days_ct <= 365:
                    cycle_times.append(days_ct)
        if cycle_times:
            ok(f"Invoice cycle time (n={len(cycle_times)}): avg={sum(cycle_times)/len(cycle_times):.1f}d")
        else:
            warn("No cycle time data — need blocks with timesheet.approved_at AND block.invoiced_at set")

        # ── Summary ───────────────────────────────────────────────────────
        head("9 / 9  SUMMARY")
        checks = {
            "Blocks with client assigned": all_blocks.filter(client__isnull=False).count() > 0,
            "Billable blocks exist":       billable_blocks > 0,
            "Invoices imported":           inv_count > 0,
            "All invoices client-matched": unmatched == 0,
            "Cost rates configured":       cr_count > 0,
            "Timesheets submitted":        submitted > 0,
        }
        all_pass = True
        for label, passed in checks.items():
            if passed:
                ok(label)
            else:
                fail(label)
                all_pass = False

        print()
        if all_pass:
            self.stdout.write(self.style.SUCCESS(
                "All checks passed — analytics endpoint should return complete data."
            ))
        else:
            self.stdout.write(self.style.WARNING(
                "Some checks failed — KPIs with missing data will return 0 / empty arrays.\n"
                "See warnings above for what to fix."
            ))

        print(f"\n  {CYAN}Test the API directly:{RESET}")
        print(f"  curl -H 'Authorization: Bearer <token>' \\")
        print(f"    '{CYAN}https://timetracker-api-k375.onrender.com/api/analytics/executive/?period={period}{RESET}'")
        print()