"""
auto_create_org_membership must actually create the org and the membership.

The signal fires when a user is added to a Django auth Group (Django admin).
It passed billing_email / billing_contact as Organization defaults, but those
fields live on OrgProfile, so every create path raised

    [ORG] Error in auto_create_org_membership: Invalid field name(s) for
    model Organization: 'billing_contact', 'billing_email'

and no Organization or OrganizationMembership was ever written.

Run against a scratch database (NOT the app container, which points at
production):

    DJANGO_SETTINGS_MODULE=settings_scratch \
      python manage.py shell < tracker/org_membership_signal_test.py

Exits non-zero if any assertion fails.
"""
import logging
import sys

from django.contrib.auth.models import Group, User

from tracker.models import Organization, OrganizationMembership, OrgProfile

failures = []


def check(label, condition, detail=""):
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}  {detail}")
        failures.append(label)


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


capture = _Capture()
signal_logger = logging.getLogger("tracker.signals")
signal_logger.addHandler(capture)
signal_logger.setLevel(logging.DEBUG)


def errors():
    return [m for m in capture.messages if "Error in auto_create_org_membership" in m]


print("New group -> org, profile and membership are created")
user = User.objects.create_user(username="sigtest-ann", password="x")
group = Group.objects.create(name="Signal Test Firm")
user.groups.add(group)

check("no signal error logged", not errors(), errors())
org = Organization.objects.filter(name="Signal Test Firm").first()
check("organization created", org is not None)
check("organization has a non-empty slug", org is not None and org.slug == "signal-test-firm",
      org and org.slug)
check("org profile created", org is not None and OrgProfile.objects.filter(org=org).exists())
membership = OrganizationMembership.objects.filter(user=user, organization=org).first()
check("membership created as member", membership is not None and membership.role == "member",
      membership and membership.role)

print("Second user in the same group reuses the org")
capture.messages.clear()
user2 = User.objects.create_user(username="sigtest-bob", password="x")
user2.groups.add(group)
check("no signal error logged", not errors(), errors())
check("still one org of that name", Organization.objects.filter(name="Signal Test Firm").count() == 1)
check("second membership created",
      OrganizationMembership.objects.filter(user=user2, organization=org).exists())

print("A second group whose name slugifies the same gets its own slug")
capture.messages.clear()
user3 = User.objects.create_user(username="sigtest-cy", password="x")
group3 = Group.objects.create(name="Signal-Test Firm")
user3.groups.add(group3)
check("no signal error logged", not errors(), errors())
org3 = Organization.objects.filter(name="Signal-Test Firm").first()
check("colliding slug was suffixed", org3 is not None and org3.slug == "signal-test-firm-1",
      org3 and org3.slug)

signal_logger.removeHandler(capture)

if failures:
    print(f"\n{len(failures)} FAILED")
    sys.exit(1)
print("\nALL PASS")
