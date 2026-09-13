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

from tracker.analytics_v2.scopes import parse_compare, resolve_relative_time
from tracker.analytics_v2.series import bucket_starts, choose_grain
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
