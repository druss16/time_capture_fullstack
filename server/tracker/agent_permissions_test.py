"""
Mac agent privacy-permission status: hello2 stores it, Settings → Devices and
MavOps serve it (tracker/agent_permissions.py).

Real database, so run against a THROWAWAY Postgres, never the default settings
(the local docker DB is production):

    python manage.py test tracker.agent_permissions_test --noinput < /dev/null
"""
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from datetime import timedelta

from tracker.agent_permissions import (
    ax_capture_state, normalize_permission_status, permission_issues, setup_level,
)
from tracker.models import AgentDevice, Organization, OrganizationMembership
from tracker.views_mavops import _org_health

User = get_user_model()

FULL = {
    "accessibility": "granted",
    "automation": {"com.google.Chrome": "granted", "com.adobe.Photoshop": "unknown"},
    "capture_mode": "full",
    "extension": "seen",
    "required_missing": [],
    "checked_at": "2026-09-30T22:25:05+00:00",
}
NO_AX = {**FULL, "accessibility": "missing", "capture_mode": "no_accessibility"}
DENIED = {**FULL, "automation": {"com.google.Chrome": "denied"},
          "required_missing": ["Google Chrome"]}
# mac_agent/permissions.disabled_report(): `disable_ax` in the agent config.
AX_OFF = {"accessibility": "disabled", "capture_mode": "ax_disabled",
          "checked_at": "2026-10-08T15:00:00+00:00"}
MAC = "macOS-26.6.2-arm64-arm-64bit"


class NormalizeTest(SimpleTestCase):
    def test_keeps_known_values(self):
        self.assertEqual(normalize_permission_status(FULL), FULL)

    def test_drops_garbage(self):
        raw = {
            "accessibility": "maybe",
            "automation": {"com.google.Chrome": "granted", "x": "pwned", 5: "granted",
                           "": "denied"},
            "capture_mode": "<script>",
            "extension": 3,
            "required_missing": ["Safari", {"a": 1}, "x" * 500],
            "stale_entry_reset": "yes",
            "evil": {"nested": True},
        }
        out = normalize_permission_status(raw)
        self.assertEqual(out["automation"], {"com.google.Chrome": "granted"})
        self.assertNotIn("accessibility", out)
        self.assertNotIn("capture_mode", out)
        self.assertNotIn("extension", out)
        self.assertNotIn("stale_entry_reset", out)
        self.assertNotIn("evil", out)
        self.assertEqual(out["required_missing"][0], "Safari")
        self.assertEqual(len(out["required_missing"][1]), 120)

    def test_not_a_status(self):
        for raw in (None, "granted", [], {}, {"checked_at": "x"}):
            self.assertIsNone(normalize_permission_status(raw), raw)

    def test_caps_target_count(self):
        raw = {"automation": {f"com.x.{i}": "granted" for i in range(500)}}
        self.assertEqual(len(normalize_permission_status(raw)["automation"]), 40)


class IssuesTest(SimpleTestCase):
    def test_full_capture_has_no_issues(self):
        self.assertEqual(permission_issues(FULL), [])
        self.assertEqual(permission_issues(None), [])

    def test_no_accessibility_is_amber_limited_capture(self):
        (issue,) = permission_issues(NO_AX)
        self.assertEqual(issue["severity"], "amber")
        self.assertIn("Limited capture", issue["message"])
        self.assertIn("Slack", issue["message"])

    def test_denied_optional_app_is_amber_not_red(self):
        # Finder/Office are optional extras: Accessibility already gives
        # their titles (Alannah, 2026-10-09: a red Finder badge overstated it).
        st = {**FULL, "automation": {"com.apple.finder": "denied",
                                     "com.microsoft.Excel": "denied"}}
        (issue,) = permission_issues(st)
        self.assertEqual((issue["severity"], issue["code"]),
                         ("amber", "automation_optional_denied"))
        self.assertIn("Excel, Finder", issue["message"])
        both = {**st, "automation": {**st["automation"], "com.google.Chrome": "denied"}}
        self.assertEqual([i["severity"] for i in permission_issues(both)], ["red", "amber"])

    def test_setup_level(self):
        # Alannah, 2026-10-09: AX on, Chrome/Acrobat granted, only Finder off.
        alannah = {**FULL, "automation": {"com.google.Chrome": "granted",
                                          "com.adobe.Acrobat.Pro": "granted",
                                          "com.apple.finder": "denied",
                                          "com.adobe.Photoshop": "unknown"}}
        self.assertEqual(setup_level(alannah, MAC), "full", "optional off is still full")
        self.assertEqual(setup_level(NO_AX, MAC), "limited")
        self.assertEqual(setup_level(AX_OFF, MAC), "limited")
        self.assertEqual(setup_level(DENIED, MAC), "blocked")
        self.assertEqual(setup_level({**FULL, "extension": "not_seen"}, MAC), "blocked")
        self.assertEqual(setup_level({**FULL, "required_missing": ["Safari"]}, MAC), "blocked")
        self.assertEqual(setup_level(None, MAC), "unreported")
        self.assertIsNone(setup_level(FULL, "Windows-11-10.0.26100-SP0"))

    def test_never_reported_mac_is_amber(self):
        (issue,) = permission_issues(None, MAC)
        self.assertEqual((issue["severity"], issue["code"]),
                         ("amber", "permissions_unreported"))
        self.assertEqual(permission_issues(None, "Darwin-23.1.0-x86_64-i386-64bit")[0]["code"],
                         "permissions_unreported")
        self.assertEqual(permission_issues(None, "Windows-11-10.0.26100-SP0"), [])
        self.assertEqual(permission_issues(None, ""), [])

    def test_config_disabled_is_amber_and_survives_normalizing(self):
        self.assertEqual(normalize_permission_status(AX_OFF), AX_OFF)
        (issue,) = permission_issues(AX_OFF, MAC)
        self.assertEqual((issue["severity"], issue["code"]),
                         ("amber", "accessibility_disabled"))
        self.assertIn("disable_ax", issue["message"])

    def test_denied_automation_and_extension_are_red(self):
        st = {**DENIED, "extension": "not_seen"}
        sev = [(i["severity"], i["code"]) for i in permission_issues(st)]
        self.assertEqual(sev, [("red", "automation_denied"), ("red", "extension_off")])
        self.assertIn("Google Chrome", permission_issues(st)[0]["message"])

    def test_org_health_flags_but_never_critical(self):
        h = _org_health(plan="pro", seat_count=5, member_count=3, active_devices=3,
                        deactivated_devices=0, now=timezone.now(),
                        permission_blocked_devices=1, limited_capture_devices=2)
        self.assertEqual(h["status"], "warn")
        self.assertIn("1 Mac with Automation/extension off", h["reasons"])
        self.assertIn("2 Macs with limited capture (Accessibility off or unreported, or an optional app off)",
                      h["reasons"])
        ok = _org_health(plan="pro", seat_count=5, member_count=3, active_devices=3,
                         deactivated_devices=0, now=timezone.now())
        self.assertEqual(ok["status"], "ok")


class Base(TestCase):
    def setUp(self):
        # plan='none' makes AgentKeyAuthentication refuse every agent call.
        self.org = Organization.objects.create(name="Firm", slug="firm", plan="professional")
        self.other = Organization.objects.create(name="Other", slug="other", plan="professional")
        self.owner = self._user("owner", "owner", self.org)
        self.member = self._user("member", "member", self.org)
        self.stranger = self._user("stranger", "owner", self.other)
        self.dev = AgentDevice.objects.create(
            user=self.member, device_id="mac-1", hostname="Janes-MacBook",
            platform="macOS", app_version="1.9.17", api_key="k" * 32,
            is_active=True, last_seen_at=timezone.now())
        self.other_dev = AgentDevice.objects.create(
            user=self.stranger, device_id="mac-2", hostname="Other-Mac",
            api_key="o" * 32, is_active=True, last_seen_at=timezone.now(),
            permission_status=DENIED)

    def _user(self, name, role, org):
        u = User.objects.create_user(name, email=f"{name}@x.com", password="x")
        OrganizationMembership.objects.create(user=u, organization=org, role=role)
        return u

    def hello(self, payload, key=None):
        c = APIClient()
        return c.post("/api/agents/hello2/", payload, format="json",
                      HTTP_X_AGENT_KEY=key or self.dev.api_key)


class Hello2StoresStatusTest(Base):
    def test_stores_config_disabled_status(self):
        r = self.hello({"hostname": "Janes-MacBook", "permissions": AX_OFF})
        self.assertEqual(r.status_code, 200, r.content)
        self.dev.refresh_from_db()
        self.assertEqual(self.dev.permission_status, AX_OFF)

    def test_stores_sanitised_status(self):
        r = self.hello({"hostname": "Janes-MacBook", "app_version": "1.9.18",
                        "device_id": "mac-1",
                        "permissions": {**NO_AX, "junk": 1}})
        self.assertEqual(r.status_code, 200, r.content)
        self.dev.refresh_from_db()
        self.assertEqual(self.dev.permission_status, NO_AX)
        self.assertEqual(self.dev.app_version, "1.9.18")

    def test_absent_or_garbage_keeps_previous(self):
        self.dev.permission_status = FULL
        self.dev.save(update_fields=["permission_status"])
        self.assertEqual(self.hello({"hostname": "Janes-MacBook"}).status_code, 200)
        self.assertEqual(self.hello({"hostname": "Janes-MacBook",
                                     "permissions": "lol"}).status_code, 200)
        self.dev.refresh_from_db()
        self.assertEqual(self.dev.permission_status, FULL)

    def test_device_can_only_write_its_own_row(self):
        self.hello({"hostname": "Janes-MacBook", "device_id": "mac-2",
                    "permissions": FULL})
        self.other_dev.refresh_from_db()
        self.assertEqual(self.other_dev.permission_status, DENIED)

    def test_requires_a_device_key(self):
        r = APIClient().post("/api/agents/hello2/", {"permissions": FULL}, format="json")
        self.assertIn(r.status_code, (401, 403))


class SettingsDevicesTest(Base):
    URL = "/api/settings/devices/"

    def test_admin_sees_badges_for_own_org_only(self):
        self.dev.permission_status = NO_AX
        self.dev.save(update_fields=["permission_status"])
        c = APIClient()
        c.force_authenticate(self.owner)
        r = c.get(self.URL)
        self.assertEqual(r.status_code, 200, r.content)
        rows = {d["machine_name"]: d for d in r.json()}
        self.assertEqual(set(rows), {"Janes-MacBook"}, "no other org's devices")
        row = rows["Janes-MacBook"]
        self.assertEqual(row["permission_status"]["capture_mode"], "no_accessibility")
        self.assertEqual([i["severity"] for i in row["permission_issues"]], ["amber"])

    def test_never_reported_mac_is_flagged(self):
        # A silent Mac used to show a clean "Active" while every title was
        # empty (More Than Cars, 2026-10-08).
        c = APIClient()
        c.force_authenticate(self.owner)
        row = c.get(self.URL).json()[0]
        self.assertIsNone(row["permission_status"])
        self.assertEqual([i["code"] for i in row["permission_issues"]],
                         ["permissions_unreported"])

    def test_never_reported_windows_is_not_an_error(self):
        self.dev.platform = "Windows-11-10.0.26100-SP0"
        self.dev.save(update_fields=["platform"])
        c = APIClient()
        c.force_authenticate(self.owner)
        self.assertEqual(c.get(self.URL).json()[0]["permission_issues"], [])

    def test_member_cannot_list_devices(self):
        c = APIClient()
        c.force_authenticate(self.member)
        self.assertEqual(c.get(self.URL).status_code, 403)

    def test_org_admin_cannot_peek_at_another_org(self):
        c = APIClient()
        c.force_authenticate(self.owner)
        rows = c.get(self.URL, {"org_id": self.other.id}).json()
        self.assertNotIn("Other-Mac", {d["machine_name"] for d in rows})


class MavOpsTest(Base):
    def test_staff_sees_status_and_org_health(self):
        staff = User.objects.create_user("ops", email="ops@mavops.ai", password="x",
                                         is_staff=True)
        c = APIClient()
        c.force_authenticate(staff)
        devs = c.get("/api/mavops/devices/").json()["devices"]
        other = next(d for d in devs if d["machine_name"] == "Other-Mac")
        self.assertEqual(other["permission_issues"][0]["code"], "automation_denied")
        orgs = {o["name"]: o for o in c.get("/api/mavops/orgs/").json()["orgs"]}
        self.assertIn("1 Mac with Automation/extension off", orgs["Other"]["health"]["reasons"])
        self.assertEqual(orgs["Firm"]["mac_setup"],
                         {"full": 0, "limited": 0, "blocked": 0, "unreported": 1})
        body = c.get("/api/mavops/devices/").json()
        self.assertIn("com.google.Chrome", body["required_automation"])
        self.assertNotIn("com.apple.finder", body["required_automation"])
        jane = next(d for d in body["devices"] if d["machine_name"] == "Janes-MacBook")
        self.assertEqual(jane["setup_level"], "unreported")
        # Firm's Mac never reported: limited, not blocked.
        self.assertIn("1 Mac with limited capture (Accessibility off or unreported, or an optional app off)",
                      orgs["Firm"]["health"]["reasons"])
        self.assertFalse(any("Automation" in r for r in orgs["Firm"]["health"]["reasons"]))

    def test_non_staff_is_refused(self):
        c = APIClient()
        c.force_authenticate(self.owner)
        self.assertEqual(c.get("/api/mavops/devices/").status_code, 403)


class AxSwitchTest(Base):
    """MavOps' remote Accessibility switch (mac_agent/ax_switch.py)."""

    def setUp(self):
        super().setUp()
        self.dev.platform = MAC
        self.dev.app_version = "1.9.34"
        self.dev.permission_status = AX_OFF
        self.dev.save()
        self.staff = User.objects.create_user("ops", email="ops@mavops.ai", password="x",
                                              is_staff=True)

    def flip(self, state, user=None, pk=None):
        c = APIClient()
        c.force_authenticate(user or self.staff)
        return c.post(f"/api/mavops/devices/{pk or self.dev.pk}/ax-capture/",
                      {"state": state}, format="json")

    def control(self):
        return APIClient().get("/api/agent/control/", {"host": "Janes-MacBook"},
                               HTTP_X_AGENT_KEY=self.dev.api_key).json()

    def test_control_is_silent_until_someone_flips_it(self):
        self.assertNotIn("ax_capture", self.control())

    def test_flip_on_reaches_the_agent_with_a_stable_id(self):
        r = self.flip("on")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["ax_capture"], "turning_on")
        d1, d2 = self.control(), self.control()
        self.assertEqual(d1["ax_capture"], "on")
        self.assertEqual(d1["ax_capture_id"], d2["ax_capture_id"], "same click, same id")
        self.flip("off")
        d3 = self.control()
        self.assertEqual(d3["ax_capture"], "off")
        self.assertNotEqual(d3["ax_capture_id"], d1["ax_capture_id"])

    def test_state_follows_what_the_agent_reports_after_the_click(self):
        self.flip("on")
        self.dev.refresh_from_db()
        self.assertEqual(ax_capture_state(self.dev), "turning_on")
        after = (self.dev.ax_switch_at + timedelta(seconds=20)).isoformat()
        self.dev.permission_status = {**NO_AX, "checked_at": after}
        self.assertEqual(ax_capture_state(self.dev), "waiting")
        self.dev.permission_status = {**FULL, "checked_at": after}
        self.assertEqual(ax_capture_state(self.dev), "on")
        self.dev.permission_status = {**AX_OFF, "rolled_back": True, "checked_at": after}
        self.assertEqual(ax_capture_state(self.dev), "rolled_back")
        self.assertEqual(permission_issues(self.dev.permission_status, MAC)[0]["code"],
                         "accessibility_rolled_back")

    def test_state_without_a_click(self):
        self.assertEqual(ax_capture_state(self.dev), "off")
        self.dev.permission_status = None
        self.assertEqual(ax_capture_state(self.dev), "unknown")
        self.dev.platform = "Windows-11-10.0.26100-SP0"
        self.assertIsNone(ax_capture_state(self.dev))

    def test_rolled_back_survives_normalizing(self):
        st = {**AX_OFF, "rolled_back": True}
        self.assertEqual(normalize_permission_status(st), st)

    def test_old_agent_windows_and_bad_state_are_refused(self):
        self.assertEqual(self.flip("sideways").status_code, 400)
        self.dev.app_version = "1.9.33"
        self.dev.save(update_fields=["app_version"])
        self.assertEqual(self.flip("on").status_code, 409)
        self.dev.app_version, self.dev.platform = "1.9.34", "Windows-11"
        self.dev.save(update_fields=["app_version", "platform"])
        self.assertEqual(self.flip("on").status_code, 400)
        self.assertEqual(self.flip("on", pk=999999).status_code, 404)
        self.dev.refresh_from_db()
        self.assertEqual(self.dev.ax_switch, "")

    def test_staff_only(self):
        self.assertEqual(self.flip("on", user=self.owner).status_code, 403)

    def test_mavops_list_carries_the_state(self):
        self.flip("on")
        c = APIClient()
        c.force_authenticate(self.staff)
        row = next(d for d in c.get("/api/mavops/devices/").json()["devices"]
                   if d["machine_name"] == "Janes-MacBook")
        self.assertEqual(row["ax_capture"], "turning_on")
        self.assertTrue(row["ax_switch_supported"])
