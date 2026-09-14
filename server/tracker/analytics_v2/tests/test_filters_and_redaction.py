"""
Two things that must not fail quietly.

1. A filter the control bar shows and the backend ignores. The dashboard would
   answer a different question than the one on screen, with every number on it
   looking authoritative.
2. A cost figure reaching a viewer who is not a firm owner. `cost_visibility`
   is the whole of that guarantee, and the Performance Trend added a new place
   cost can hide — inside a chart's toggle views.

Run:
    python manage.py test tracker.analytics_v2.tests.test_filters_and_redaction
"""
from django.test import SimpleTestCase

from tracker.analytics_v2.scopes import RequestParseError, parse_filters, parse_scope
from tracker.cost_visibility import redact_cost_sections


class ParseFiltersTests(SimpleTestCase):
    def test_known_dimensions_are_kept(self):
        out = parse_filters({"client": [1, 2], "engagement": [7],
                             "service": [3], "staff": [9]})
        self.assertEqual(out, {"client": [1, 2], "engagement": [7],
                               "service": [3], "staff": [9]})

    def test_unknown_dimension_is_rejected_not_dropped(self):
        """Silently dropping it would leave the UI claiming a filter is active
        while the numbers behind it are unfiltered."""
        with self.assertRaises(RequestParseError):
            parse_filters({"team": [1]})

    def test_billable_accepts_only_known_values(self):
        self.assertEqual(parse_filters({"billable": "billable"}),
                         {"billable": "billable"})
        self.assertEqual(parse_filters({"billable": "all"}), {})
        with self.assertRaises(RequestParseError):
            parse_filters({"billable": "sometimes"})

    def test_empty_id_lists_are_dropped(self):
        self.assertEqual(parse_filters({"client": []}), {})

    def test_non_integer_ids_are_rejected(self):
        with self.assertRaises(RequestParseError):
            parse_filters({"client": ["'; drop table"]})

    def test_filters_survive_scope_parsing(self):
        scope = parse_scope({"type": "firm", "filters": {"billable": "billable"}})
        self.assertEqual(scope.filters, {"billable": "billable"})


class FlagRarityTests(SimpleTestCase):
    """A flag has to be rare to carry information.

    The first rule compared each client with the firm's MEDIAN, which flags
    half the table by definition — at org 21 that was 26 of 52 clients wearing
    a badge. Comparing against the bottom quartile caps each rule at about a
    quarter and makes the badge worth reading.
    """

    def _rows(self, n=40):
        """A smooth spread of clients, all material, none pathological."""
        rows = []
        for i in range(n):
            hours = 20.0 + i
            billable_pct = 40.0 + i * 1.5      # 40% .. 98.5%
            revenue = 4000.0 + i * 100
            margin_pct = 10.0 + i * 1.5        # 10% .. 68.5%
            margin = revenue * margin_pct / 100
            rows.append({
                "id": i + 1, "label": f"Client {i}", "hours": hours,
                "billable_hours": hours * billable_pct / 100,
                "billable_pct": billable_pct, "revenue": revenue,
                "cost": revenue - margin, "margin": margin,
                "margin_pct": margin_pct, "people": 1, "share": 0.0,
                "is_internal": False,
            })
        return rows

    def test_a_smooth_spread_flags_about_a_quarter_not_a_half(self):
        from tracker.analytics_v2.lenses.clients import flag_rows

        rows = self._rows()
        flag_rows(rows, None)
        flagged = [r for r in rows if r["flags"]]

        # Comfortably under half — the failure this test exists for.
        self.assertLess(len(flagged), len(rows) * 0.40,
                        f"{len(flagged)} of {len(rows)} flagged — too many to mean anything")
        self.assertGreater(len(flagged), 0, "the rule should still flag the worst")

    def test_only_the_bottom_of_the_spread_is_flagged(self):
        """Whoever is flagged must actually be at the bottom of the list."""
        from tracker.analytics_v2.lenses.clients import flag_rows

        rows = self._rows()
        flag_rows(rows, None)
        non_billable_flagged = [
            r["billable_pct"] for r in rows
            if any(f["key"] == "heavy_non_billable" for f in r["flags"])
        ]
        others = [
            r["billable_pct"] for r in rows
            if not any(f["key"] == "heavy_non_billable" for f in r["flags"])
        ]
        if non_billable_flagged and others:
            self.assertLess(max(non_billable_flagged), min(others))

    def test_a_client_losing_money_is_always_flagged(self):
        """The one objective rule must not be quantile-gated away."""
        from tracker.analytics_v2.lenses.clients import flag_rows

        rows = self._rows()
        rows.append({
            "id": 999, "label": "Underwater", "hours": 60.0,
            "billable_hours": 55.0, "billable_pct": 91.0, "revenue": 5000.0,
            "cost": 7000.0, "margin": -2000.0, "margin_pct": -40.0,
            "people": 1, "share": 0.0, "is_internal": False,
        })
        flag_rows(rows, None)
        loser = next(r for r in rows if r["label"] == "Underwater")
        self.assertIn("losing_money", [f["key"] for f in loser["flags"]])


class CostRedactionTests(SimpleTestCase):
    def _trend_card(self):
        return {
            "type": "chart_card",
            "id": "performance_trend",
            "subtitle": "By week · Q3 · median margin 42%",
            "series": [{"key": "hours", "label": "Total hours"}],
            "toggle_views": [
                {"key": "hours", "label": "Total hours", "series": ["hours"]},
                {"key": "revenue", "label": "Billable value", "series": ["revenue"]},
                {"key": "cost", "label": "Labor cost", "series": ["cost"]},
                {"key": "margin", "label": "Gross margin", "series": ["margin"]},
            ],
            "data": [{"label": "w/c 1 Sep", "hours": 10.0, "revenue": 750.0,
                      "cost": 260.0, "margin": 490.0}],
        }

    def test_cost_toggle_views_are_removed_not_just_emptied(self):
        """Leaving a 'Labor cost' tab that draws nothing is worse than removing
        it: an empty chart reads as "this firm has no labor cost"."""
        card = redact_cost_sections([{
            "type": "section", "children": [self._trend_card()],
        }])[0]["children"][0]

        keys = {v["key"] for v in card["toggle_views"]}
        self.assertEqual(keys, {"hours", "revenue"})
        self.assertNotIn("cost", card["data"][0])
        self.assertNotIn("margin", card["data"][0])

    def test_non_cost_views_survive(self):
        card = redact_cost_sections([{
            "type": "section", "children": [self._trend_card()],
        }])[0]["children"][0]
        self.assertEqual(card["data"][0]["hours"], 10.0)
        self.assertEqual(card["data"][0]["revenue"], 750.0)

    def test_margin_clause_is_scrubbed_from_the_subtitle(self):
        card = redact_cost_sections([{
            "type": "section", "children": [self._trend_card()],
        }])[0]["children"][0]
        self.assertNotIn("margin", card["subtitle"].lower())
        self.assertIn("Q3", card["subtitle"])

    def test_margin_derived_flags_are_stripped_but_others_survive(self):
        """Stripping the margin column while leaving a "Losing money" badge in
        the next cell would defeat the entire redaction."""
        row = {
            "id": 1, "label": "Acme", "hours": 10.0, "cost": 500.0,
            "margin": -100.0, "margin_pct": -25.0,
            "flags": [{"key": "losing_money", "label": "Losing money"},
                      {"key": "heavy_non_billable", "label": "Heavy non-billable"}],
            "flag_label": "Losing money · Heavy non-billable",
        }
        table = redact_cost_sections([{
            "type": "section",
            "children": [{
                "type": "data_table", "subtitle": "",
                "columns": [{"key": "label", "label": "Client", "format": "text"},
                            {"key": "flag_label", "label": "Flag", "format": "text"},
                            {"key": "margin", "label": "Margin", "format": "currency_0dp"}],
                "rows": [row],
            }],
        }])[0]["children"][0]

        out = table["rows"][0]
        self.assertEqual(out["flag_label"], "Heavy non-billable")
        self.assertEqual([f["key"] for f in out["flags"]], ["heavy_non_billable"])
        self.assertNotIn("margin", out)

    def test_redactor_and_lens_agree_on_which_flags_are_cost(self):
        """The two sets are declared in different modules on purpose — the lens
        should not import the redactor. This is what keeps them in step: add a
        margin-derived flag to the lens and forget the redactor, and this fails
        instead of the flag quietly leaking."""
        from tracker.analytics_v2.lenses.clients import COST_DERIVED_FLAGS
        from tracker.cost_visibility import COST_FLAG_KEYS

        self.assertEqual(set(COST_DERIVED_FLAGS), set(COST_FLAG_KEYS))

    def test_team_margin_column_is_stripped(self):
        """The team table's 'Contribution margin' must use a key the redactor
        knows. This test fails if somebody renames it to something prettier."""
        from tracker.analytics_v2.lenses.team import team_columns

        cols = {c["key"] for c in team_columns()}
        table = redact_cost_sections([{
            "type": "section",
            "children": [{
                "type": "data_table", "subtitle": "",
                "columns": team_columns(),
                "rows": [{k: 1 for k in cols}],
                "default_sort": {"key": "margin", "direction": "desc"},
            }],
        }])[0]["children"][0]

        surviving = {c["key"] for c in table["columns"]}
        self.assertNotIn("cost", surviving)
        self.assertNotIn("margin", surviving)
        self.assertIn("billable_pct", surviving)
        # The default sort pointed at a column that is now gone.
        self.assertNotEqual(table["default_sort"]["key"], "margin")
