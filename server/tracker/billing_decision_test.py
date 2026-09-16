"""
What the Fees worklist has to guarantee.

The page used to be a report: eighty-two rows, nothing to show which clients a
partner had already settled, and no trace afterwards of what they decided to
charge. These cover the two things that turn it into a finite piece of work —
a decision that sticks, and a decision that becomes next period's anchor.

Run against a scratch database (NOT the app container, which points at
production):

    docker run --rm -i -v <worktree>/server:/app -w /app --network <net> \
      -e DJANGO_SETTINGS_MODULE=settings_scratch <image> \
      python manage.py shell < tracker/billing_decision_test.py

Exits non-zero if any assertion fails.
"""
import datetime as dt
import sys
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework.test import APIRequestFactory, force_authenticate

from tracker.models import BillingDecision, Block, Client, Organization
from tracker.models_engagements import Engagement

failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        failures.append(label)


User = get_user_model()

# Re-runnable: a scratch database gets used more than once, and a test that
# only passes on a virgin schema is a test people stop running.
Organization.objects.filter(slug="worklist-test").delete()
User.objects.filter(username__startswith="worklist_").delete()

org = Organization.objects.create(name="Worklist Test Co", slug="worklist-test",
                                  billing_rate_default=Decimal("75.00"))
owner = User.objects.create_user("worklist_owner", password="x")
from tracker.models import OrganizationMembership
OrganizationMembership.objects.create(organization=org, user=owner, role="owner")
client = Client.objects.create(org=org, name="St Peters Church", code="SPC")

AUG = (dt.date(2026, 8, 1), dt.date(2026, 8, 31))
SEP = (dt.date(2026, 9, 1), dt.date(2026, 9, 30))

for day, minutes in ((dt.date(2026, 9, 3), 300), (dt.date(2026, 9, 10), 342)):
    start = dt.datetime.combine(day, dt.time(9, 0))
    Block.objects.create(org=org, user=owner, client=client, day=day,
                         start=start, end=start + dt.timedelta(minutes=minutes),
                         minutes=minutes, is_billable=True,
                         billing_amount=Decimal(minutes) / 60 * Decimal("75"))

# The views are called directly rather than over the test client: this is about
# what fee_basis and fee_decision do, and routing a request through the token
# auth stack to find that out only adds a way for the test to fail for reasons
# that are nothing to do with billing.
from tracker.views_fee_basis import fee_basis, fee_decision

factory = APIRequestFactory()


def call(view, method, user, path, data=None, params=""):
    req = getattr(factory, method)(path + params, data, format="json")
    force_authenticate(req, user=user)
    return view(req)


def post_decision(amount, period=SEP, user=None):
    return call(fee_decision, "post", user or owner, "/api/billing/fee-decision/",
                {"client_id": client.id, "start": period[0].isoformat(),
                 "end": period[1].isoformat(), "amount": amount})


def basis(period=SEP):
    res = call(fee_basis, "get", owner, "/api/billing/fee-basis/",
               params=f"?start={period[0]}&end={period[1]}")
    return res.data


print("\n1. A period starts with nothing settled")
d = basis()
check("client is listed", any(c["client_id"] == client.id for c in d["clients"]))
check("nothing decided", d["decided"]["clients"] == 0, f"got {d['decided']}")
row = next(c for c in d["clients"] if c["client_id"] == client.id)
check("no decision on the row", row["decision"] is None, f"got {row['decision']}")

print("\n2. Marking it billed records the call and what it was made against")
res = post_decision(869)
check("accepted", res.status_code == 200, f"got {res.status_code} {res.data}")
saved = BillingDecision.objects.get(org=org, client=client, period_start=SEP[0])
check("amount stored", float(saved.amount) == 869.0, f"got {saved.amount}")
check("hours snapshotted", float(saved.hours_at_decision) == 10.7,
      f"got {saved.hours_at_decision}")
check("decider recorded", saved.decided_by_id == owner.id)

print("\n3. The list gets shorter")
d = basis()
check("counted as done", d["decided"]["clients"] == 1, f"got {d['decided']}")
check("total charged", d["decided"]["amount"] == 869.0, f"got {d['decided']}")
row = next(c for c in d["clients"] if c["client_id"] == client.id)
check("row carries the decision", row["decision"]["amount"] == 869.0)

print("\n4. Changing your mind edits, never duplicates")
post_decision(750)
check("still one row",
      BillingDecision.objects.filter(org=org, client=client,
                                     period_start=SEP[0]).count() == 1)
check("new amount wins", basis()["decided"]["amount"] == 750.0)

print("\n5. Two decisions for the same client and period cannot coexist")
try:
    with transaction.atomic():
        BillingDecision.objects.create(org=org, client=client,
                                       period_start=SEP[0], period_end=SEP[1],
                                       amount=Decimal("1.00"))
    check("constraint held", False, "a duplicate was accepted")
except IntegrityError:
    check("constraint held", True)

print("\n6. Undo puts the row back on the list")
res = call(fee_decision, "delete", owner, "/api/billing/fee-decision/",
           {"client_id": client.id, "start": SEP[0].isoformat(),
            "end": SEP[1].isoformat()})
check("accepted", res.status_code == 200, f"got {res.status_code}")
check("gone", not BillingDecision.objects.filter(org=org, client=client,
                                                 period_start=SEP[0]).exists())
check("back to nothing settled", basis()["decided"]["clients"] == 0)

print("\n7. What you charged last period becomes this period's anchor")
# August's decision, read from September — the anchor that needed no invoice
# to be imported from anywhere.
BillingDecision.objects.create(org=org, client=client, period_start=AUG[0],
                               period_end=AUG[1], amount=Decimal("640.00"))
row = next(c for c in basis()["clients"] if c["client_id"] == client.id)
check("last charged surfaces", row["last_charged"]
      and row["last_charged"]["amount"] == 640.0, f"got {row.get('last_charged')}")

print("\n8. A member cannot bill on the firm's behalf")
member = User.objects.create_user("worklist_member", password="x")
OrganizationMembership.objects.create(organization=org, user=member, role="member")
res = post_decision(1, user=member)
check("refused", res.status_code == 403, f"got {res.status_code}")

print("\n9. Rubbish in the amount is refused, not stored as zero")
res = post_decision("not a number")
check("refused", res.status_code == 400, f"got {res.status_code}")

print()
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("All worklist checks passed.")


# ── The tail ───────────────────────────────────────────────────────────────
# Added after Dan asked, twice, what the page is for: 44 of org 21's 103
# clients had under an hour in August, and a partner pricing his month should
# not have to scroll past them.
print("\n10. The sub-hour tail is marked, not dropped")
tiny = Client.objects.create(org=org, name="Half Hour Ltd", code="HHL")
day = dt.date(2026, 9, 4)
start = dt.datetime.combine(day, dt.time(11, 0))
Block.objects.create(org=org, user=owner, client=tiny, day=day, start=start,
                     end=start + dt.timedelta(minutes=30), minutes=30,
                     is_billable=True, billing_amount=Decimal("37.50"))
d = basis()
rows = {c["name"]: c for c in d["clients"]}
check("tail client still listed", "Half Hour Ltd" in rows)
check("marked immaterial", rows["Half Hour Ltd"]["material"] is False,
      f"got {rows['Half Hour Ltd'].get('material')}")
check("the real client stays material", rows["St Peters Church"]["material"] is True)
check("tail is summarised", d["tail"]["clients"] == 1 and d["tail"]["hours"] == 0.5,
      f"got {d['tail']}")

if failures:
    print(f"\n{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("Tail checks passed too.")
