"""
What the fee schedule has to guarantee.

Before this existed a fee was written only onto the engagements that happened
to be open when someone typed it, which failed in both directions:

  1. A schedule handed over during onboarding had nothing to land on —
     engagements are derived from captured time, so on day one there are no
     jobs — and 168 rows of a firm's own pricing were reported as "no open
     engagements" and thrown away.
  2. A fee typed in March was gone by April. Next month's engagement is a new
     row with no budget, so derive_budget handed it an estimate off an
     under-captured month: the exact number a person had already corrected.

Run against a scratch database (NOT the app container, which points at
production):

    docker cp server/. <container>:/tmp/scratch
    docker exec -w /tmp/scratch -e DJANGO_SETTINGS_MODULE=<sqlite settings> \
      <container> python manage.py shell < tracker/fee_schedule_test.py

Exits non-zero if any assertion fails.
"""
import datetime as dt
import sys
from decimal import Decimal

from tracker.models import Client, Organization
from tracker.models_engagements import Engagement, FeeScheduleEntry
from tracker.services.engagements import derive_budget
from tracker.services.fee_schedule import record_fee

failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        failures.append(label)


org = Organization.objects.create(name="Fee Schedule Test Co", slug="fee-sched-test",
                                  billing_rate_default=Decimal("75.00"))
client = Client.objects.create(org=org, name="Assumption Church", code="AC")


def period(label, start, end, **kw):
    return Engagement.objects.create(
        org=org, client=client, engagement_type="bookkeeping",
        period_label=label, period_start=start, period_end=end,
        status="open", **kw)


print("\n1. record_fee stores the price at client x job-type grain")
entry = record_fee(org, client.id, "bookkeeping", 6.0, fee=450, set_in="Fees")
check("entry created", FeeScheduleEntry.objects.filter(org=org).count() == 1)
check("hours stored", float(entry.budget_hours) == 6.0, f"got {entry.budget_hours}")
check("quoted fee kept", float(entry.fee_quoted) == 450.0, f"got {entry.fee_quoted}")

print("\n2. Re-pricing updates in place rather than piling up rows")
record_fee(org, client.id, "bookkeeping", 8.0, fee=600, set_in="Settings")
check("still one row", FeeScheduleEntry.objects.filter(org=org).count() == 1)
check("new price wins",
      float(FeeScheduleEntry.objects.get(org=org).budget_hours) == 8.0)

print("\n3. A NEW period takes the fee instead of an estimate")
# The bug this closes: without a schedule this engagement has no budget, so
# derive_budget reaches for a prior month or a median of comparable jobs.
aug = period("2026-08", dt.date(2026, 8, 1), dt.date(2026, 8, 31))
result = derive_budget(aug, dry_run=False)
aug.refresh_from_db()
check("budget came from the schedule", result["basis"] == "fee schedule",
      f"got {result.get('basis')!r}")
check("budget is the firm's number", float(aug.budget_hours) == 8.0,
      f"got {aug.budget_hours}")
check("source is manual", aug.budget_source == "manual", f"got {aug.budget_source}")
check("amount uses the firm rate", float(aug.budget_amount) == 600.0,
      f"got {aug.budget_amount}")

print("\n4. And so does the period after it — the fee outlives the calendar")
sep = period("2026-09", dt.date(2026, 9, 1), dt.date(2026, 9, 30))
derive_budget(sep, dry_run=False)
sep.refresh_from_db()
check("next period priced too", float(sep.budget_hours) == 8.0,
      f"got {sep.budget_hours}")
entry.refresh_from_db()
check("applications counted", entry.applied_count == 2, f"got {entry.applied_count}")

print("\n5. dry_run really is dry")
oct_ = period("2026-10", dt.date(2026, 10, 1), dt.date(2026, 10, 31))
derive_budget(oct_, dry_run=True)
oct_.refresh_from_db()
check("nothing written", oct_.budget_hours is None, f"got {oct_.budget_hours}")

print("\n6. A job with no schedule still falls back to estimating")
other = Client.objects.create(org=org, name="No Schedule Ltd", code="NSL")
lone = Engagement.objects.create(
    org=org, client=other, engagement_type="payroll", period_label="2026-08",
    period_start=dt.date(2026, 8, 1), period_end=dt.date(2026, 8, 31), status="open")
res = derive_budget(lone, dry_run=False)
check("no basis without history or schedule", res["action"] == "no_basis",
      f"got {res}")

print("\n7. A budget a person already set by hand is never overwritten")
manual = period("2026-11", dt.date(2026, 11, 1), dt.date(2026, 11, 30),
                budget_hours=Decimal("3.00"), budget_source="manual")
res = derive_budget(manual, dry_run=False)
manual.refresh_from_db()
check("kept_manual", res["action"] == "kept_manual", f"got {res}")
check("hours untouched", float(manual.budget_hours) == 3.0, f"got {manual.budget_hours}")

print("\n8. The schedule is scoped to its own org and job type")
check("other type unaffected",
      not FeeScheduleEntry.objects.filter(org=org, engagement_type="payroll").exists())

print()
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("All fee-schedule checks passed.")
