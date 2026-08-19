"""
End-to-end tests for WIP accrual, WIP relief, engagements, budgets, and the
burn-vs-progress math.

What these guard, in order:

  1. WIP accrues at CAPTURE, tiered. It used to be gated on `approved=True`,
     which at org 21 meant $17k of visible WIP hiding $143k of real billable
     time behind a timesheet workflow the firm doesn't run.
  2. Aging runs from the WORK DATE. Aging from `approved_at` made 90-day-old
     work look two days old the moment someone signed a timesheet.
  3-6. Engagements, budgets from prior-year actuals, burn vs progress, and
     phase inference staying in shadow (it must never overwrite what a
     preparer said).
  7-8. WIP actually DRAINS — FIFO for hourly clients, whole-period with a
     recorded write-down for flat fee. Nothing set Block.invoiced before this.

These need a database. Run against a scratch Postgres (NOT the app container,
which points at production):

    docker run --rm -i --network <net> -v <worktree>/server:/app -w /app \
      -e DJANGO_SETTINGS_MODULE=<scratch settings> <image> \
      python manage.py shell < tracker/wip_engagement_test.py

Exits non-zero if any assertion fails.
"""
import sys

import datetime as dt
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.utils import timezone

from tracker.models import (
    Block, Client, ClientBillingProfile, Engagement, Invoice, Organization,
)
from tracker.analytics_v2.metrics import get_metric
from tracker.analytics_v2.types import Scope, TimeRange
from tracker.services.engagements import (
    assign_engagements, derive_budgets, open_engagement_stats,
)
from tracker.services.phase_inference import infer_phase, refresh_inferred_phases
from tracker.services.wip_relief import relieve_org

User = get_user_model()
TODAY = timezone.localdate()
FIRM = Scope(type="firm")
WINDOW = TimeRange(start=TODAY - dt.timedelta(days=365), end=TODAY, label="test")

ok = []
fail = []


def check(name, got, want):
    (ok if got == want else fail).append((name, got, want))
    flag = "PASS" if got == want else "FAIL"
    print(f"  [{flag}] {name}: got {got!r} want {want!r}")


org = Organization.objects.create(name="Smoke CPA", billing_rate_default=Decimal("200"))
user = User.objects.create_user(username="preparer", password="x")
hourly = Client.objects.create(org=org, name="Hourly Client")
flat = Client.objects.create(org=org, name="Flat Fee Client")
ClientBillingProfile.objects.create(
    client=flat, org=org, billing_type="flat_fee",
    flat_amount=Decimal("500"), flat_period="monthly",
)


def mk(client, day, minutes, state="committed", *, title="", rt="", amount=None,
       billable=True, approved=False):
    start = timezone.make_aware(dt.datetime.combine(day, dt.time(9, 0)))
    return Block.objects.create(
        org=org, user=user, client=client, day=day,
        start=start, end=start + dt.timedelta(minutes=minutes),
        minutes=minutes, is_billable=billable,
        classification_state=state,
        is_categorized=(state == "committed"),
        approved=approved,
        billing_amount=Decimal(str(amount)) if amount is not None else None,
        billing_rate=Decimal("200"),
        window_title=title, title=title,
        tax_return_type=rt or None,
    )


print("\n=== 1. WIP accrual tiers ===")
# $200/hr. 3h committed today, 2h captured (unreviewed), 1h committed 90 days back.
mk(hourly, TODAY, 180, "committed")
mk(hourly, TODAY, 120, "captured")
mk(hourly, TODAY - dt.timedelta(days=90), 60, "committed")
mk(hourly, TODAY, 30, "suppressed")           # never WIP
mk(hourly, TODAY, 60, "committed", billable=False)  # non-billable, never WIP

wip = get_metric("wip_total").compute(org, FIRM, WINDOW)
unrev = get_metric("wip_unreviewed").compute(org, FIRM, WINDOW)
check("wip_total = 3h + 1h @200", wip.value, 800.0)
check("wip_unreviewed = 2h @200", unrev.value, 400.0)

print("\n=== 2. Aging runs from the work date, not approval ===")
aged = get_metric("wip_aged_60_plus").compute(org, FIRM, WINDOW)
check("90-day-old block lands in 60+", aged.value, 200.0)
# The old behaviour: approving it would have reset its age to zero.
Block.objects.filter(day=TODAY - dt.timedelta(days=90)).update(
    approved=True, approved_at=timezone.now())
aged2 = get_metric("wip_aged_60_plus").compute(org, FIRM, WINDOW)
check("still 60+ after being approved today", aged2.value, 200.0)

print("\n=== 3. Engagements derived from captured signals ===")
# Prior year: 10h on this client's 1040 → next year's budget.
for i in range(10):
    mk(hourly, dt.date(TODAY.year - 1, 3, 1), 60, "committed", rt="1040",
       title="UltraTax Input Screen")
# This year: 8h so far on the same return.
for i in range(8):
    mk(hourly, dt.date(TODAY.year, 3, 1), 60, "committed", rt="1040",
       title="UltraTax Input Screen")

res = assign_engagements(org, dry_run=False)
print("   ", res)
check("two tax engagements created", Engagement.objects.count(), 2)

print("\n=== 4. Budget from prior-year actual ===")
derive_budgets(org, dry_run=False, only_open=True)
this_year = Engagement.objects.get(period_label=f"TY{TODAY.year - 1}")
check("budget = prior-year 10h", float(this_year.budget_hours or 0), 10.0)
check("budget source", this_year.budget_source, "prior_year")
print("    basis:", this_year.budget_basis)

print("\n=== 5. Burn vs progress ===")
this_year.phase = "preparing"   # 55% done per the tax ladder
this_year.phase_source = "user"
this_year.save()
stats = {s.engagement.id: s for s in open_engagement_stats(org)}[this_year.id]
check("actual hours", stats.actual_hours, 8.0)
check("burn % = 8/10", stats.burn_pct, 80.0)
check("progress % = preparing", stats.progress_pct, 55.0)
check("over pace = 80 - 55", stats.overrun_pts, 25.0)
check("projected hours = 8/0.55", stats.projected_hours, 14.55)
check("projected overrun hours", stats.projected_overrun_hours, 4.55)
check("projected overrun $ @200", stats.projected_overrun_dollars, 910.0)

print("\n=== 6. Phase inference (shadow only) ===")
mk(hourly, dt.date(TODAY.year, 3, 2), 30, "committed", rt="1040",
   title="UltraTax - Critical Diagnostics")
assign_engagements(org, dry_run=False)
phase, conf, signals = infer_phase(Engagement.objects.get(id=this_year.id))
check("infers the furthest phase reached", phase, "review")
print(f"    confidence {conf}, signals {signals}")
refresh_inferred_phases(org, dry_run=False)
this_year.refresh_from_db()
check("inferred stored", this_year.inferred_phase, "review")
check("user phase NOT overwritten", this_year.phase, "preparing")

print("\n=== 7. WIP relief — hourly, FIFO to invoice amount ===")
before = get_metric("wip_total").compute(org, FIRM, WINDOW).value
Invoice.objects.create(
    org=org, client=hourly, invoice_number="INV-1", invoice_date=TODAY,
    amount=Decimal("400"), status="sent", source="manual",
)
report = relieve_org(org, dry_run=True)
check("dry run writes nothing", Block.objects.filter(invoiced=True).count(), 0)
report = relieve_org(org, dry_run=False)
print("   ", {k: v for k, v in report.items() if k != "details"})
after = get_metric("wip_total").compute(org, FIRM, WINDOW).value
check("WIP dropped by the invoice amount", round(before - after, 2), 400.0)
oldest_relieved = Block.objects.filter(invoiced=True).order_by("day").first()
check("relieved the OLDEST work first",
      oldest_relieved.day, dt.date(TODAY.year - 1, 3, 1))
check("invoice marked applied once",
      Invoice.objects.get(invoice_number="INV-1").wip_relieved_amount, Decimal("400.00"))
again = relieve_org(org, dry_run=False)
check("re-running is a no-op", again["invoices_applied"], 0)

print("\n=== 8. WIP relief — flat fee relieves the whole period ===")
for _ in range(6):
    mk(flat, TODAY, 60, "committed")     # 6h @ $200 = $1,200 of WIP
Invoice.objects.create(
    org=org, client=flat, invoice_number="INV-2", invoice_date=TODAY,
    amount=Decimal("500"), status="sent", source="manual",
)
relieve_org(org, dry_run=False)
inv2 = Invoice.objects.get(invoice_number="INV-2")
check("flat fee relieved all 6h of WIP", float(inv2.wip_relieved_amount), 1200.0)
check("write-down recorded as residual", float(inv2.wip_relief_residual), -700.0)
check("no flat-fee WIP left",
      Block.objects.filter(client=flat, invoiced=False, is_billable=True).count(), 0)

print("\n" + "=" * 60)
print(f"{len(ok)} passed, {len(fail)} failed")
for name, got, want in fail:
    print(f"  FAILED {name}: got {got!r} want {want!r}")

sys.exit(1 if fail else 0)
