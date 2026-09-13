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
