"""
Bucketing rules for the Performance Trend chart.

These are SimpleTestCase (no database): they pin the pure date arithmetic that
decides how a window is sliced. The tie-out between the summed series and the
KPI tiles above it is a database test and lives in
`test_series_reconciliation.py`.

Run:
    python manage.py test tracker.analytics_v2.tests.test_series_bucketing

Do NOT run through the prod-connected container — see test_revenue_sources.py.
"""
from datetime import date

from django.test import SimpleTestCase

from tracker.analytics_v2.scopes import (
    parse_compare, parse_grain, parse_request_body, resolve_relative_time,
)
from tracker.analytics_v2.series import (
    _bucket_label, _grain_options, _next_bucket, bucket_starts, choose_grain,
    quarter_window, whole_buckets,
)
from tracker.analytics_v2.types import TimeRange


def _range(start: str, end: str) -> TimeRange:
    return TimeRange(date.fromisoformat(start), date.fromisoformat(end), "test")


class ChooseGrainTests(SimpleTestCase):
    def test_a_month_or_less_is_daily(self):
        self.assertEqual(choose_grain(_range("2026-09-01", "2026-09-30")), "day")

    def test_a_quarter_is_weekly(self):
        self.assertEqual(choose_grain(_range("2026-07-01", "2026-09-30")), "week")

    def test_a_year_is_monthly(self):
        self.assertEqual(choose_grain(_range("2026-01-01", "2026-12-31")), "month")

    def test_a_single_day_still_produces_one_bucket(self):
        t = _range("2026-09-13", "2026-09-13")
        self.assertEqual(len(bucket_starts(t, choose_grain(t))), 1)


class BucketStartsTests(SimpleTestCase):
    def test_empty_buckets_are_present(self):
        """A quiet week must be a gap in the line, not a missing point.

        Dropping empty buckets would let the chart draw straight from the week
        before to the week after, which reads as steady work through a week
        nobody billed.
        """
        t = _range("2026-09-01", "2026-09-30")
        self.assertEqual(len(bucket_starts(t, "day")), 30)

    def test_weekly_buckets_start_on_monday(self):
        # 2026-09-01 is a Tuesday; its week starts Monday 2026-08-31.
        buckets = bucket_starts(_range("2026-09-01", "2026-09-21"), "week")
        self.assertEqual(buckets[0], date(2026, 8, 31))
        self.assertTrue(all(b.weekday() == 0 for b in buckets))

    def test_monthly_buckets_cover_partial_months(self):
        buckets = bucket_starts(_range("2026-01-15", "2026-03-02"), "month")
        self.assertEqual(buckets,
                         [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)])


class PartialBucketTests(SimpleTestCase):
    """A clipped bucket under-counts by construction and reads as a slump.

    This is the "why does it look like we're collapsing?" bug: on "this
    quarter" the last weekly bucket holds only the days so far, and the FIRST
    one is clipped too — a quarter starting Wednesday 1 Jul gets a week that
    began Monday 29 Jun, two days of which are outside the window.
    """

    def test_the_week_in_progress_is_dropped(self):
        # Quarter to date: 1 Jul .. Wed 12 Aug, "today" being that Wednesday.
        t = _range("2026-07-01", "2026-08-12")
        kept = whole_buckets(bucket_starts(t, "week"), t, "week",
                             today=date(2026, 8, 12))
        # Monday 10 Aug's week runs to Sunday 16 Aug — not finished.
        self.assertNotIn(date(2026, 8, 10), kept)

    def test_the_clipped_first_week_is_dropped_too(self):
        t = _range("2026-07-01", "2026-08-12")
        buckets = bucket_starts(t, "week")
        self.assertEqual(buckets[0], date(2026, 6, 29))   # starts before 1 Jul
        kept = whole_buckets(buckets, t, "week", today=date(2026, 8, 12))
        self.assertNotIn(date(2026, 6, 29), kept)

    def test_whole_weeks_in_the_middle_survive(self):
        t = _range("2026-07-01", "2026-08-12")
        kept = whole_buckets(bucket_starts(t, "week"), t, "week",
                             today=date(2026, 8, 12))
        self.assertIn(date(2026, 7, 6), kept)
        self.assertIn(date(2026, 8, 3), kept)

    def test_a_finished_period_keeps_every_bucket(self):
        """Last quarter is entirely in the past: nothing is in progress, and
        its calendar edges line up, so nothing should be trimmed."""
        t = _range("2026-04-01", "2026-06-30")
        buckets = bucket_starts(t, "month")
        kept = whole_buckets(buckets, t, "month", today=date(2026, 9, 14))
        self.assertEqual(kept, buckets)

    def test_today_is_dropped_at_daily_grain(self):
        """Today is half a day for the same reason this week is half a week."""
        t = _range("2026-09-01", "2026-09-14")
        kept = whole_buckets(bucket_starts(t, "day"), t, "day",
                             today=date(2026, 9, 14))
        self.assertNotIn(date(2026, 9, 14), kept)
        self.assertIn(date(2026, 9, 13), kept)

    def test_trimming_never_empties_the_chart(self):
        """A one-week window is entirely "partial" by this rule. Showing a
        short bar the label explains beats showing nothing at all."""
        t = _range("2026-09-14", "2026-09-14")
        buckets = bucket_starts(t, "day")
        kept = whole_buckets(buckets, t, "day", today=date(2026, 9, 14))
        self.assertEqual(kept, buckets)


class SamePeriodLastYearTests(SimpleTestCase):
    def test_partial_quarter_compares_with_the_same_partial_slice(self):
        """Mid-quarter, "same period last year" must not compare a partial
        quarter against a whole one — that would read as a collapse in volume
        every time somebody opened the dashboard before quarter end."""
        base = _range("2026-07-01", "2026-08-15")
        prior = parse_compare(
            {"type": "relative", "value": "same_period_last_year"}, base)
        self.assertEqual(prior.start, date(2025, 7, 1))
        self.assertEqual(prior.end, date(2025, 8, 15))
        self.assertEqual(prior.days(), base.days())

    def test_leap_day_clamps_rather_than_raising(self):
        base = _range("2024-02-29", "2024-02-29")
        prior = parse_compare(
            {"type": "relative", "value": "same_period_last_year"}, base)
        self.assertEqual(prior.start, date(2023, 2, 28))

    def test_prior_period_is_the_window_immediately_before(self):
        base = _range("2026-07-01", "2026-09-30")
        prior = parse_compare({"type": "relative", "value": "prior_period"}, base)
        self.assertEqual(prior.end, date(2026, 6, 30))
        self.assertEqual(prior.days(), base.days())

    def test_no_comparison_stays_none(self):
        self.assertIsNone(parse_compare(None, _range("2026-07-01", "2026-09-30")))


class RelativeTimeTests(SimpleTestCase):
    def test_named_quarter_resolves_to_full_quarter(self):
        t = resolve_relative_time("q3_2026")
        self.assertEqual((t.start, t.end), (date(2026, 7, 1), date(2026, 9, 30)))


class QuarterGrainTests(SimpleTestCase):
    """Quarter buckets, and the window widening that makes them worth drawing.

    Asking for quarters over a single quarter is one dot, so choosing the
    grain moves the CHART's window back to put that quarter among its
    neighbours. Nothing else on the page moves.
    """

    def test_quarter_buckets_start_on_the_quarter(self):
        t = _range("2025-02-11", "2026-08-20")
        starts = bucket_starts(t, "quarter")
        self.assertEqual(starts[0], date(2025, 1, 1))
        self.assertEqual(starts[1], date(2025, 4, 1))
        self.assertIn(date(2026, 1, 1), starts)
        # Every start is the first day of a quarter month.
        self.assertTrue(all(b.day == 1 and b.month in (1, 4, 7, 10) for b in starts))

    def test_bucket_label_is_the_quarter_name(self):
        self.assertEqual(_bucket_label(date(2026, 7, 1), "quarter"), "Q3 2026")
        self.assertEqual(_bucket_label(date(2026, 1, 1), "quarter"), "Q1 2026")
        self.assertEqual(_bucket_label(date(2025, 10, 1), "quarter"), "Q4 2025")

    def test_december_rolls_into_the_next_year(self):
        self.assertEqual(_next_bucket(date(2026, 10, 1), "quarter"), date(2027, 1, 1))

    def test_window_widens_to_eight_quarters_ending_with_the_selected_one(self):
        # "This quarter", Q3 2026, part-way through.
        wide = quarter_window(_range("2026-07-01", "2026-09-15"))
        self.assertEqual(wide.start, date(2024, 10, 1))   # Q4 2024, 8 back
        self.assertEqual(wide.end, date(2026, 9, 30))
        self.assertEqual(len(bucket_starts(wide, "quarter")), 8)
        self.assertEqual(wide.label, "Q4 2024 → Q3 2026")

    def test_widening_never_shortens_the_selected_window(self):
        # A custom range ending mid-quarter keeps its own end if it is later
        # than the quarter's — the chart may show more than was asked for,
        # never less.
        wide = quarter_window(_range("2026-01-01", "2026-09-30"))
        self.assertGreaterEqual(wide.end, date(2026, 9, 30))

    def test_the_part_quarter_in_progress_is_dropped_like_a_part_week(self):
        wide = quarter_window(_range("2026-07-01", "2026-09-15"))
        kept = whole_buckets(bucket_starts(wide, "quarter"), wide, "quarter",
                             today=date(2026, 9, 15))
        self.assertNotIn(date(2026, 7, 1), kept)          # Q3 is still filling
        self.assertEqual(kept[-1], date(2026, 4, 1))      # ends on whole Q2
        self.assertEqual(len(kept), 7)

    def test_a_finished_quarter_is_plotted(self):
        # "Last quarter" — Q2 2026 is over, so it must appear.
        wide = quarter_window(_range("2026-04-01", "2026-06-30"))
        kept = whole_buckets(bucket_starts(wide, "quarter"), wide, "quarter",
                             today=date(2026, 9, 15))
        self.assertEqual(kept[-1], date(2026, 4, 1))


class GrainOptionTests(SimpleTestCase):
    """Which bucketings a window is allowed to offer."""

    def test_a_quarter_offers_week_and_quarter(self):
        opts = _grain_options(_range("2026-07-01", "2026-09-30"), "week")
        self.assertEqual([o["key"] for o in opts], ["auto", "quarter"])
        self.assertEqual(opts[0]["label"], "By week")

    def test_a_year_offers_month_and_quarter(self):
        opts = _grain_options(_range("2026-01-01", "2026-12-31"), "month")
        self.assertEqual([o["key"] for o in opts], ["auto", "quarter"])

    def test_a_single_week_offers_nothing(self):
        # Two years of history arriving behind a control labelled "This week"
        # is a trap, not a view — so there is no control at all.
        self.assertEqual(_grain_options(_range("2026-09-07", "2026-09-13"), "day"), [])

    def test_a_month_is_the_shortest_window_that_offers_quarters(self):
        self.assertEqual(
            [o["key"] for o in _grain_options(_range("2026-09-01", "2026-09-28"), "day")],
            ["auto", "quarter"],
        )


class ParseGrainTests(SimpleTestCase):
    """A grain arrives from a URL, so it is attacker-shaped until validated."""

    def test_known_grains_survive(self):
        for g in ("auto", "day", "week", "month", "quarter"):
            self.assertEqual(parse_grain(g), g)

    def test_case_and_whitespace_are_forgiven(self):
        self.assertEqual(parse_grain("  Quarter "), "quarter")

    def test_anything_else_is_none_rather_than_an_error(self):
        # A stale or hand-edited link should open on the default view, not on
        # an HTTP 400 the viewer can do nothing about.
        for bad in ("fortnight", "", "1=1", None, 7, {"key": "quarter"}):
            self.assertIsNone(parse_grain(bad))

    def test_the_body_puts_the_grain_on_the_time_range(self):
        _, _, time, compare = parse_request_body({
            "scope": {"type": "firm"}, "lens": "overview",
            "time": {"type": "relative", "value": "last_quarter"},
            "compare": {"type": "relative", "value": "prior_period"},
            "grain": "quarter",
        })
        self.assertEqual(time.grain, "quarter")
        # The comparison window is one aggregate, never a series.
        self.assertIsNone(compare.grain)
