"""Paused-hours arithmetic behind the Reports "Paused" column.

    python manage.py test tracker.tests_tracking_pause

SimpleTestCase: paused_minutes_from_rows is pure, no database.
"""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import SimpleTestCase

from tracker.views_tracking_pause import OPEN_PAUSE_CAP, paused_minutes_from_rows

UTC = dt_timezone.utc
DAY_START = datetime(2026, 10, 7, 4, 0, tzinfo=UTC)     # midnight New York
DAY_END = DAY_START + timedelta(days=1)
NOW = DAY_START + timedelta(hours=20)


def at(h, m=0):
    return DAY_START + timedelta(hours=h, minutes=m)


def minutes(rows, start=DAY_START, end=DAY_END, now=NOW):
    return paused_minutes_from_rows(rows, start, end, now)


class PausedMinutesTests(SimpleTestCase):
    def test_closed_pause_inside_the_window(self):
        self.assertEqual(minutes([(1, at(10), at(10, 30), None)]), {1: 30.0})

    def test_only_the_part_inside_the_window_counts(self):
        rows = [(1, DAY_START - timedelta(minutes=20), DAY_START + timedelta(minutes=10), None),
                (1, DAY_END - timedelta(minutes=5), DAY_END + timedelta(hours=1), None)]
        self.assertEqual(minutes(rows), {1: 15.0})

    def test_open_timed_pause_runs_to_its_planned_end(self):
        self.assertEqual(minutes([(1, at(9), None, at(10))]), {1: 60.0})

    def test_open_timed_pause_never_counts_past_now(self):
        now = at(9, 10)
        self.assertEqual(minutes([(1, at(9), None, at(10))], now=now), {1: 10.0})

    def test_open_until_resumed_runs_to_now(self):
        self.assertEqual(minutes([(1, at(19), None, None)]), {1: 60.0})

    def test_abandoned_open_pause_is_capped(self):
        started = DAY_START - timedelta(days=3)
        rows = [(1, started, None, None)]
        # The cap ended it long before this day: nothing today.
        self.assertEqual(minutes(rows), {})
        # And on its own day it stops at the cap.
        self.assertEqual(
            minutes(rows, start=started, end=started + timedelta(days=2),
                    now=started + timedelta(days=5)),
            {1: OPEN_PAUSE_CAP.total_seconds() / 60},
        )

    def test_overlapping_pauses_on_two_devices_count_once(self):
        rows = [(1, at(10), at(11), None), (1, at(10, 30), at(11, 30), None)]
        self.assertEqual(minutes(rows), {1: 90.0})

    def test_separate_pauses_add_up(self):
        rows = [(1, at(10), at(10, 15), None), (1, at(14), at(14, 45), None)]
        self.assertEqual(minutes(rows), {1: 60.0})

    def test_people_are_kept_apart(self):
        rows = [(1, at(10), at(11), None), (2, at(10), at(10, 6), None)]
        self.assertEqual(minutes(rows), {1: 60.0, 2: 6.0})

    def test_pause_entirely_outside_is_dropped(self):
        rows = [(1, DAY_END + timedelta(hours=1), DAY_END + timedelta(hours=2), None)]
        self.assertEqual(minutes(rows), {})
