"""
Unit tests for flat-fee proration — the money math behind mixed-billing revenue.

These exercise the pure function `_prorate_flat_fee` (no database rows needed).
Run locally against a TEST database:

    python manage.py test tracker.analytics_v2.tests.test_revenue_sources

Do NOT run the project test suite through the prod-connected container — it would
try to create a test database on the live Neon instance. Use a local Postgres.
"""
from django.test import SimpleTestCase

from tracker.analytics_v2.metrics.revenue_sources import _prorate_flat_fee


class ProrateFlatFeeTests(SimpleTestCase):
    def test_equivalent_periods_recognize_equal_value(self):
        """A monthly, quarterly, and annual retainer of equal annualized value
        must recognize (approximately) the same revenue over the same window."""
        days = 90
        monthly = _prorate_flat_fee(3000, "monthly", days)      # $36k/yr
        quarterly = _prorate_flat_fee(9000, "quarterly", days)  # $36k/yr
        annual = _prorate_flat_fee(36000, "annual", days)       # $36k/yr
        self.assertAlmostEqual(monthly, quarterly, delta=1.0)
        self.assertAlmostEqual(monthly, annual, delta=1.0)
        # ~ 90/365.25 * 36000
        self.assertAlmostEqual(annual, 8870.64, delta=1.0)

    def test_partial_window_prorates(self):
        """A one-week window of a monthly retainer is ~ 7/30 of the fee."""
        week = _prorate_flat_fee(3000, "monthly", 7)
        self.assertAlmostEqual(week, 3000 / 30.4375 * 7, places=2)

    def test_blank_period_falls_back_to_monthly(self):
        """A fee with a missing period must still contribute (treated monthly),
        not silently read as $0."""
        blank = _prorate_flat_fee(3000, "", 30)
        monthly = _prorate_flat_fee(3000, "monthly", 30)
        self.assertEqual(blank, monthly)
        self.assertGreater(blank, 0)

    def test_per_project_is_one_time(self):
        """Per-project fees are not time-prorated — full amount once."""
        self.assertEqual(_prorate_flat_fee(5000, "per_project", 90), 5000.0)
        self.assertEqual(_prorate_flat_fee(5000, "per_project", 7), 5000.0)

    def test_edge_cases_are_zero(self):
        self.assertEqual(_prorate_flat_fee(0, "monthly", 90), 0.0)
        self.assertEqual(_prorate_flat_fee(3000, "monthly", 0), 0.0)
        self.assertEqual(_prorate_flat_fee(-100, "monthly", 90), 0.0)
