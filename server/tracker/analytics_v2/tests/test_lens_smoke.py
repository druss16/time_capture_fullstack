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
        # `is_internal_client_name` matches "Internal" and "Internal - <x>".
        cls.internal = Client.objects.create(org=cls.org, name="Internal - Tax")

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
        # Internal work, flagged billable — the state that put $10,489 of
        # "billable value" on an Internal - Tax row.
        for i in range(2):
            Block.objects.create(
                org=cls.org, user=cls.user, hostname="h",
                start=now - timedelta(days=i, hours=2),
                end=now - timedelta(days=i, hours=1),
                day=today - timedelta(days=i), minutes=60,
                client=cls.internal, is_billable=True,
                classification_state="committed", is_categorized=True,
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
        """Half the fixture blocks have no client. `breakdown` still reports
        that row, and names it rather than leaving the label blank — it is the
        CALLER that decides whether a client ranking should show it."""
        from tracker.analytics_v2.breakdowns import breakdown

        labels = {r["label"] for r
                  in breakdown(self.org, Scope(type="firm"), self.time, "client")}
        self.assertIn("No client assigned", labels)

    def test_client_ranking_holds_out_unassigned_and_internal(self):
        """Neither is a client. "No client assigned" has no value, no margin
        and no drilldown; internal work is never billable by definition, so it
        cannot be ranked on margin against work that is."""
        from tracker.analytics_v2.breakdowns import breakdown, split_client_rows

        rows, unassigned, internal = split_client_rows(
            breakdown(self.org, Scope(type="firm"), self.time, "client"))

        self.assertIsNotNone(unassigned)
        self.assertEqual([r["label"] for r in internal], ["Internal - Tax"])
        labels = {r["label"] for r in rows}
        self.assertNotIn("No client assigned", labels)
        self.assertNotIn("Internal - Tax", labels)
        self.assertIn("Acme Co", labels)

    def test_internal_work_earns_no_revenue(self):
        """Internal time was showing billable VALUE because the breakdown
        priced it with the utilization rule (canonical PLUS billable-effort
        clients) instead of the canonical billing rule the Revenue tile uses.
        The row may carry hours; it must never carry money."""
        from tracker.analytics_v2.breakdowns import breakdown

        rows = breakdown(self.org, Scope(type="firm"), self.time, "client")
        internal = next(r for r in rows if r["label"] == "Internal - Tax")

        self.assertGreater(internal["hours"], 0)
        self.assertEqual(internal["revenue"], 0.0)
        self.assertEqual(internal["cost"], 0.0)
        self.assertEqual(internal["margin"], 0.0)

    def test_table_revenue_ties_to_the_revenue_tile(self):
        """The whole point of the two-rule split: the money in these tables has
        to add up to the money on the tile above them."""
        from tracker.analytics_v2.breakdowns import breakdown
        from tracker.analytics_v2.metrics.base import get_metric
        from tracker.analytics_v2.types import MetricState

        scope = Scope(type="firm")
        rows = breakdown(self.org, scope, self.time, "client")
        table_total = sum(r["revenue"] for r in rows)

        tile = get_metric("revenue").compute(self.org, scope, self.time)
        tile_total = tile.value if tile.state == MetricState.READY else 0.0

        self.assertAlmostEqual(table_total, tile_total or 0.0, delta=1.0)

    def test_holding_them_out_rescales_the_shares(self):
        """Shares must still sum to 100% over what is actually shown, or the
        "share of time" column silently stops being a share of anything."""
        from tracker.analytics_v2.breakdowns import breakdown, split_client_rows

        rows, _, _ = split_client_rows(
            breakdown(self.org, Scope(type="firm"), self.time, "client"))
        if rows:
            self.assertAlmostEqual(sum(r["share"] for r in rows), 100.0, delta=0.5)

    def test_the_held_out_hours_are_still_named_somewhere(self):
        """Dropping a quarter of the firm's hours with no trace would leave a
        client table whose hours don't tie to the firm's hours."""
        from tracker.analytics_v2.breakdowns import (
            breakdown, held_out_note, split_client_rows,
        )

        _, unassigned, internal = split_client_rows(
            breakdown(self.org, Scope(type="firm"), self.time, "client"))
        note = held_out_note(unassigned, internal).lower()
        self.assertIn("no client", note)
        self.assertIn("internal", note)

    def test_client_ranking_shows_the_top_20_and_collapses_the_rest(self):
        """A CPA firm's client list has a long thin tail — 52 clients in a
        quarter where the busiest is under 40 hours. Forty rows is an export,
        not a ranking."""
        from tracker.analytics_v2.lenses.clients import _RANKING_ROWS

        for i in range(30):
            # `code` is unique per org and defaults to "", so it must be set
            # when creating more than one client in a test.
            c = Client.objects.create(
                org=self.org, name=f"Tail Client {i}", code=f"TAIL{i}")
            Block.objects.create(
                org=self.org, user=self.user, hostname="h",
                start=timezone.now() - timedelta(hours=2),
                end=timezone.now() - timedelta(hours=1),
                day=date.today(), minutes=60 + i, client=c,
                is_billable=True, classification_state="committed",
                is_categorized=True,
            )

        payload = self._assemble("clients", Scope(type="firm"))
        main = next(c for s in payload for c in s.get("children", [])
                    if c.get("id") == "clients_ranked")
        tail = next((c for s in payload for c in s.get("children", [])
                     if c.get("id") == "clients_tail"), None)

        self.assertLessEqual(len(main["rows"]), _RANKING_ROWS)
        self.assertIsNotNone(tail, "the rest must still be reachable")
        # And the tail section is folded shut, not dumped on the page.
        tail_section = next(s for s in payload if s.get("id") == "client_tail")
        self.assertTrue(tail_section["collapsible"])
        self.assertTrue(tail_section["collapsed"])

    def test_the_cutoff_is_display_only_and_does_not_move_the_flag_baseline(self):
        """The flags are computed over every material client BEFORE the top-20
        cut. If the cut came first, the bar a client is judged against would
        depend on how many rows the table happens to show."""
        from tracker.analytics_v2.lenses.clients import flag_rows
        from tracker.analytics_v2.stats import quantile

        rows = [{
            "id": i + 1, "label": f"C{i}", "hours": 100.0 - i,
            "billable_hours": (100.0 - i) * (0.4 + i * 0.015),
            "billable_pct": 40.0 + i * 1.5, "revenue": 5000.0,
            "cost": 2000.0, "margin": 3000.0, "margin_pct": 60.0,
            "people": 1, "share": 0.0, "is_internal": False,
        } for i in range(40)]

        all_rows = [dict(r) for r in rows]
        flag_rows(all_rows, None)
        baseline = quantile([r["billable_pct"] for r in all_rows], 0.25)

        # Flagging only the visible twenty would compute a different quartile.
        top_only = [dict(r) for r in rows[:20]]
        flag_rows(top_only, None)
        narrowed = quantile([r["billable_pct"] for r in top_only], 0.25)

        self.assertNotAlmostEqual(baseline, narrowed, places=1)
        # The shipped order flags against the full set: a client near the
        # bottom of all 40 stays flagged whatever the table shows.
        worst = min(all_rows, key=lambda r: r["billable_pct"])
        self.assertTrue(worst["flags"])

    def test_kpi_tiles_carry_a_sparkline(self):
        """`Metric.sparkline()` was declared on the base class, never called by
        safe_compute and never implemented, so MetricValue.sparkline was always
        None and the frontend's sparkline branch was dead code. It is now fed
        from one shared `build_series` pass per KPI row."""
        payload = self._assemble("overview", Scope(type="firm"))
        row = next(s for s in payload if s["type"] == "kpi_row")
        withspark = [t for t in row["tiles"] if t["metric"].get("sparkline")]

        self.assertTrue(withspark, "no tile carried a sparkline")
        for t in withspark:
            self.assertGreaterEqual(len(t["metric"]["sparkline"]), 3)
            self.assertTrue(all(isinstance(v, (int, float))
                                for v in t["metric"]["sparkline"]))

    def test_sparklines_come_from_one_series_pass(self):
        """Seven tiles must not mean seven trend queries.

        The invariant is that the cost is FLAT in the number of metrics, not
        that it is any particular number: one `build_series` pass plus the
        fixed overhead of the shared rule helpers (internal-client ids, rate
        maps, the utilization exclusions) covers every line on the row. Pinning
        an absolute count would just break whenever a helper adds a lookup.
        """
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        from tracker.analytics_v2.series import sparklines_for

        with CaptureQueriesContext(connection) as ctx:
            sparks = sparklines_for(self.org, Scope(type="firm"), self.time)
        one_pass = len(ctx.captured_queries)

        self.assertGreaterEqual(len(sparks), 5,
                                "one pass should cover most of the KPI row")
        # Per-metric trend queries would cost at least one round trip each on
        # top of this; flat means the whole row costs about what one does.
        self.assertLess(one_pass, len(sparks) * 5)

    def test_sparkline_drops_empty_buckets_rather_than_plotting_zero(self):
        """A week that billed nothing has no margin percentage. Plotting it as
        0% would draw a crash to the floor that never happened."""
        from tracker.analytics_v2.series import build_series, sparklines_for

        points, _ = build_series(self.org, Scope(type="firm"), self.time)
        sparks = sparklines_for(self.org, Scope(type="firm"), self.time)
        if "gross_margin" in sparks:
            nulls = sum(1 for p in points if p.get("margin_pct") is None)
            self.assertEqual(len(sparks["gross_margin"]), len(points) - nulls)

    def test_no_project_and_uncategorized_still_appear(self):
        """Only the CLIENT dimension holds its unassigned row back. A missing
        project or category is an ordinary state for real work, and on a
        "where does the time go" page it is part of the answer."""
        from tracker.analytics_v2.breakdowns import breakdown

        for dim, expected in (("project", "No project"),
                              ("category", "Uncategorized")):
            with self.subTest(dimension=dim):
                labels = {r["label"] for r in breakdown(
                    self.org, Scope(type="firm"), self.time, dim)}
                self.assertIn(expected, labels)
