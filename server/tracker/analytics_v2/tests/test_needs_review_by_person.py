"""
Needs review, by person — the manager's "who is behind" view on Team.

The count per person must be the number that person sees in Daily Review, so
it is pinned against `needs_you` (which shares Daily Review's predicate), and
narrowing to one person must list exactly their items, oldest first.

NEEDS POSTGRES. See test_lens_smoke.py.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from tracker.analytics_v2.lenses import get_lens
from tracker.analytics_v2.metrics import attribution
from tracker.analytics_v2.types import Scope, TimeRange
from tracker.cost_visibility import redact_cost_sections
from tracker.models import Block, Client, Organization, OrganizationMembership

User = get_user_model()


class NeedsReviewByPersonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(
            name="Review Co", slug="review-co", plan="executive",
            billing_rate_default=150, cost_rate_default=50)
        cls.acme = Client.objects.create(org=cls.org, name="Acme Co")

        def member(username):
            u = User.objects.create(username=username, email=f"{username}@x.test",
                                    first_name=username.title())
            OrganizationMembership.objects.create(
                organization=cls.org, user=u, role="member")
            return u

        cls.behind = member("behind")
        cls.caught_up = member("caughtup")

        now = timezone.now()
        today = date.today()
        # Three unattributed, material blocks on past days: Needs You items.
        for days_ago in (5, 3, 2):
            Block.objects.create(
                org=cls.org, user=cls.behind, hostname="h",
                start=now - timedelta(days=days_ago, hours=1),
                end=now - timedelta(days=days_ago),
                day=today - timedelta(days=days_ago), minutes=30,
                app_name="Excel", window_title=f"Workpapers {days_ago}",
                classification_state="captured", is_categorized=False,
            )
        # Confirmed time for both, so both have a Team row.
        for u in (cls.behind, cls.caught_up):
            Block.objects.create(
                org=cls.org, user=u, hostname="h",
                start=now - timedelta(days=1, hours=2),
                end=now - timedelta(days=1, hours=1),
                day=today - timedelta(days=1), minutes=60,
                client=cls.acme, is_billable=True,
                classification_state="committed", is_categorized=True,
            )
        cls.time = TimeRange(today - timedelta(days=30), today, "Last 30 days")

    def setUp(self):
        attribution._needs_you_cache.clear()

    def _assemble(self, scope):
        return [s.to_dict() for s in get_lens("team").assemble(self.org, scope, self.time)]

    def _child(self, payload, child_id):
        for sec in payload:
            for c in sec.get("children", []) or []:
                if c.get("id") == child_id:
                    return c
        return None

    def test_team_rows_carry_the_same_count_daily_review_does(self):
        expected = attribution.needs_you(self.org.id, self.time)[3]
        self.assertEqual(expected.get(self.behind.id), 3)

        table = self._child(self._assemble(Scope(type="firm")), "team_rows")
        by_id = {r["id"]: r["needs_review"] for r in table["rows"]}
        self.assertEqual(by_id[self.behind.id], 3)
        self.assertEqual(by_id[self.caught_up.id], 0)

    def test_chart_ranks_whoever_is_most_behind_first(self):
        chart = self._child(self._assemble(Scope(type="firm")), "team_needs_review")
        self.assertEqual(chart["data"][0]["label"], "Behind")
        self.assertEqual(chart["data"][0]["items"], 3)
        self.assertAlmostEqual(chart["data"][0]["hours"], 1.5, places=1)

    def test_firm_view_lists_no_items(self):
        """Everyone's items at once is a wall, not an answer; the list appears
        only once the view is narrowed to people."""
        self.assertIsNone(
            self._child(self._assemble(Scope(type="firm")), "team_needs_review_items"))

    def test_employee_filter_lists_their_items_oldest_first(self):
        scope = Scope(type="firm", filters={"staff": [self.behind.id]})
        items = self._child(self._assemble(scope), "team_needs_review_items")
        self.assertEqual([r["what"] for r in items["rows"]],
                         ["Workpapers 5", "Workpapers 3", "Workpapers 2"])
        chart = self._child(self._assemble(scope), "team_needs_review")
        self.assertEqual([d["label"] for d in chart["data"]], ["Behind"])

    def test_staff_scope_lists_their_items(self):
        items = self._child(
            self._assemble(Scope(type="staff", ids=[self.behind.id])),
            "team_needs_review_items")
        self.assertEqual(len(items["rows"]), 3)

    def test_managers_keep_it_after_cost_redaction(self):
        """Counts and hours, no cost: a manager is exactly who this is for."""
        out = redact_cost_sections(self._assemble(Scope(type="firm")))
        self.assertIsNotNone(self._child(out, "team_needs_review"))
        table = self._child(out, "team_rows")
        self.assertIn("needs_review", [c["key"] for c in table["columns"]])
