"""
Capture basis — what the denominator is allowed to assume.

The first version divided captured hours by SCHEDULED capacity, which answers a
different question than "did we see the work" and answered it by accusing
people: a part-timer who worked eight full days read as 33%, and an admin the
firm had already excluded from utilization read as 21% with a perfectly healthy
agent.

Run against a scratch database (NOT the app container, which points at
production):

    docker run --rm -i -v <worktree>/server:/app -w /app --network <net> \
      -e DJANGO_SETTINGS_MODULE=settings_scratch <image> \
      python manage.py shell < tracker/capture_test.py

Exits non-zero if any assertion fails.
"""
import datetime as dt
import sys
from decimal import Decimal

from django.contrib.auth import get_user_model

from tracker.models import (
    Block, Client, CostTier, Organization, OrganizationMembership, WorkCalendar,
)
from tracker.services.capture import capture_by_user, firm_capture, standard_day_hours

failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        failures.append(label)


U = get_user_model()
Organization.objects.filter(slug="capture-test").delete()
U.objects.filter(username__startswith="cap_").delete()

org = Organization.objects.create(name="Capture Test Co", slug="capture-test",
                                  billing_rate_default=Decimal("75.00"))
WorkCalendar.objects.create(org=org, hours_per_day=Decimal("8.00"),
                            working_weekdays=[0, 1, 2, 3, 4])
client = Client.objects.create(org=org, name="A Client", code="AC")

chargeable = CostTier.objects.create(organization=org, label="Staff",
                                     cost_rate=Decimal("30.00"),
                                     hours_per_week=Decimal("40"),
                                     counts_toward_utilization=True)
admin_tier = CostTier.objects.create(organization=org, label="Admin",
                                     cost_rate=Decimal("25.00"),
                                     counts_toward_utilization=False)


def member(name, tier):
    u = U.objects.create_user(f"cap_{name}", password="x")
    OrganizationMembership.objects.create(organization=org, user=u, role="member",
                                          cost_tier=tier)
    return u


def work(user, day, hours):
    """Committed, categorised time — `working_qs` counts nothing else, so a
    fixture that skips this measures an empty queryset and passes for the
    wrong reason."""
    start = dt.datetime.combine(day, dt.time(9, 0))
    minutes = int(round(hours * 60))
    Block.objects.create(org=org, user=user, client=client, day=day, start=start,
                         end=start + dt.timedelta(minutes=minutes), minutes=minutes,
                         is_billable=True, is_categorized=True,
                         classification_state="committed",
                         billing_amount=Decimal(minutes) / 60 * Decimal("75"))


MON = dt.date(2026, 8, 3)          # a Monday
days = [MON + dt.timedelta(days=i) for i in range(5)]      # Mon-Fri
SAT = MON + dt.timedelta(days=5)

print("\n1. The firm's own working day is the denominator")
check("hours_per_day read from the calendar", standard_day_hours(org) == 8.0,
      f"got {standard_day_hours(org)}")

print("\n2. A full-timer seen for 6h of an 8h day reads 75%, not 100%")
full = member("full", chargeable)
for d in days:
    work(full, d, 6.0)
caps = capture_by_user(org, [full.id], MON, SAT)
check("75%", abs(caps[full.id] - 0.75) < 0.001, f"got {caps.get(full.id)}")

print("\n3. A part-timer is judged on the days she worked, not the ones she didn't")
# Two days, fully captured. Against a five-day week this would read 30%.
part = member("part", chargeable)
for d in days[:2]:
    work(part, d, 7.5)
caps = capture_by_user(org, [part.id], MON, SAT)
check("94%, not 38%", abs(caps[part.id] - 0.9375) < 0.001, f"got {caps.get(part.id)}")

print("\n4. A few minutes on a Saturday is not a working day")
# Without the floor this 0.5h day would add 8h of denominator and halve her.
work(part, SAT, 0.5)
caps = capture_by_user(org, [part.id], MON, SAT)
check("unchanged by the Saturday glance", abs(caps[part.id] - 0.9375) < 0.001,
      f"got {caps.get(part.id)}")

print("\n5. Non-chargeable staff are not measured at all")
adm = member("admin", admin_tier)
for d in days:
    work(adm, d, 2.0)
caps = capture_by_user(org, [full.id, adm.id], MON, SAT)
check("admin absent", adm.id not in caps, f"got {list(caps)}")
check("colleague still there", full.id in caps)

print("\n6. The firm number pools days, so a two-day colleague does not outweigh a full one")
pooled = firm_capture(org, [full.id, part.id, adm.id], MON, SAT)
# full: 5 days x 6h = 30h of 40h. part: 2 days x 7.5h = 15h of 16h. → 45/56
check("pooled, not averaged", abs(pooled - (45.0 / 56.0)) < 0.001, f"got {pooled}")

print("\n7. Nobody with no working days is invented")
absent = member("absent", chargeable)
caps = capture_by_user(org, [absent.id], MON, SAT)
check("absent user absent", absent.id not in caps, f"got {list(caps)}")
check("firm number is None when nobody worked",
      firm_capture(org, [absent.id], MON, SAT) is None)

print("\n8. Capture is capped at 1.0")
over = member("over", chargeable)
work(over, days[0], 14.0)
caps = capture_by_user(org, [over.id], MON, SAT)
check("100%, not 175%", caps[over.id] == 1.0, f"got {caps.get(over.id)}")

print()
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("All capture-basis checks passed.")
