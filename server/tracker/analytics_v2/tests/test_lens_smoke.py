"""
Every lens assembles, against a real (empty-ish) database.

These are cheap and they catch the failure mode static checks cannot: an ORM
expression that is only wrong at query time — a field that does not exist, an
aggregate filter Postgres/SQLite rejects, a `values()` grouping that collides
with an annotation name. The executive dashboard added four lenses and two
grouped-aggregation modules, all of which build their querysets dynamically.

The assertions are deliberately shallow. The point is "it runs and produces a
serializable payload", not the specific numbers — those belong in the
reconciliation tests, which need a fixture of real time.

NEEDS POSTGRES. Several tracker migrations run raw Postgres SQL, and the
models carry Postgres-only constructs, so the schema will not build on sqlite —
these tests cannot be run against a sqlite stand-in. Point them at a local
Postgres, never at the prod-connected container (it would try to create a test
database on the live Neon instance):

    python manage.py test tracker.analytics_v2.tests.test_lens_smoke

The sibling suites (test_series_bucketing, test_filters_and_redaction) are
SimpleTestCase and need no database at all.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from tracker.analytics_v2.lenses import all_lens_keys, get_lens
from tracker.analytics_v2.types import Scope, TimeRange
from tracker.models import Block, Client, Organization, OrganizationMembership

User = get_user_model()

# Lenses the executive dashboard introduced, plus the ones they reuse.
DASHBOARD_LENSES = ["overview", "clients", "team", "distribution"]


class LensSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(
            name="Test CPA", slug="test-cpa", plan="executive",
            billing_rate_default=150, cost_rate_default=50,
        )
        cls.user = User.objects.create(username="tester", email="t@example.com")
        OrganizationMembership.objects.create(
            organization=cls.org, user=cls.user, role="owner")
        cls.client_a = Client.objects.create(org=cls.org, name="Acme Co")

        today = date.today()
        now = timezone.now()
        for i in range(6):
            day = today - timedelta(days=i)
            Block.objects.create(
                org=cls.org, user=cls.user, hostname="h",
                start=now - timedelta(days=i, hours=1),
                end=now - timedelta(days=i),
                day=day, minutes=60,
                client=cls.client_a if i % 2 == 0 else None,
                is_billable=(i % 2 == 0),
                classification_state="committed",
                is_categorized=True,
            )

        cls.time = TimeRange(today - timedelta(days=30), today, "Last 30 days")
        cls.compare = TimeRange(today - timedelta(days=61),
                                today - timedelta(days=31), "Prior period")

    def _assemble(self, key, scope, compare=None):
        sections = get_lens(key).assemble(self.org, scope, self.time, compare)
        payload = [s.to_dict() for s in sections]
        # Must survive the trip through JSON — the view serializes this.
        json.dumps(payload)
        return payload

    def test_every_dashboard_lens_assembles_at_firm_scope(self):
        firm = Scope(type="firm")
        for key in DASHBOARD_LENSES:
            with self.subTest(lens=key):
                self.assertTrue(self._assemble(key, firm))

    def test_every_registered_lens_assembles(self):
        """Catches a shared helper change breaking a lens nobody edited."""
        firm = Scope(type="firm")
        for key in all_lens_keys():
            with self.subTest(lens=key):
                self._assemble(key, firm)

    def test_dashboard_lenses_assemble_with_a_comparison(self):
        firm = Scope(type="firm")
        for key in DASHBOARD_LENSES:
            with self.subTest(lens=key):
                self._assemble(key, firm, compare=self.compare)

    def test_client_drilldown_assembles(self):
        scope = Scope(type="client", ids=(self.client_a.id,), label="Acme Co")
        payload = self._assemble("clients", scope)
        self.assertTrue(payload)

    def test_staff_drilldown_assembles(self):
        scope = Scope(type="staff", ids=(self.user.id,), label="tester")
        self.assertTrue(self._assemble("team", scope))

    def test_filters_apply_on_every_scope_type(self):
        """A filter set in the control bar must narrow a client-scoped page too,
        not only a composite one."""
        scope = Scope(type="client", ids=(self.client_a.id,),
                      filters={"billable": "non_billable"})
        self.assertTrue(self._assemble("clients", scope))

    def test_trend_carries_a_point_per_bucket_and_every_measure(self):
        from tracker.analytics_v2.series import trend_chart

        card = trend_chart(self.org, Scope(type="firm"), self.time).to_dict()
        self.assertEqual(card["x_key"], "label")
        self.assertTrue(card["data"])
        for key in ("hours", "billable_hours", "revenue", "cost", "margin",
                    "utilization"):
            self.assertIn(key, card["data"][0])
        self.assertEqual(
            [v["key"] for v in card["toggle_views"]],
            ["hours", "billable_hours", "revenue", "cost", "margin", "utilization"],
        )

    def test_breakdown_runs_for_every_dimension(self):
        from tracker.analytics_v2.breakdowns import breakdown

        for dim in ("client", "user", "project", "category"):
            with self.subTest(dimension=dim):
                rows = breakdown(self.org, Scope(type="firm"), self.time, dim)
                for r in rows:
                    self.assertIn("hours", r)
                    self.assertIn("share", r)

    def test_unassigned_rows_are_named_not_blank(self):
        """Half the fixture blocks have no client. That row must say so."""
        from tracker.analytics_v2.breakdowns import breakdown

        labels = {r["label"] for r
                  in breakdown(self.org, Scope(type="firm"), self.time, "client")}
        self.assertIn("No client assigned", labels)
