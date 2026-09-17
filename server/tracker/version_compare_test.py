"""Ordering for agent version strings.

Pure functions, no database — runs under SimpleTestCase.

The case that matters is the one that cost an afternoon: an agent running a
release candidate asked the server whether to update, and the server said yes,
pointing at the older published release. The downgrade installed itself and
reported nothing, so the build under test was replaced by the build it was
meant to replace.
"""
from django.test import SimpleTestCase

from tracker.views import _is_newer, _parse_version


class ParseVersionTests(SimpleTestCase):
    def test_release_outranks_its_own_prerelease(self):
        self.assertGreater(_parse_version('1.8.7'), _parse_version('1.8.7-rc1'))

    def test_prerelease_outranks_the_previous_release(self):
        self.assertGreater(_parse_version('1.8.7-rc1'), _parse_version('1.8.6'))

    def test_unorderable_strings_are_rejected(self):
        for value in ('', 'dev', 'garbage', '1.8.x', None):
            self.assertIsNone(_parse_version(value), value)


class IsNewerTests(SimpleTestCase):
    def test_ordinary_upgrade(self):
        self.assertTrue(_is_newer('1.8.7', '1.8.6'))

    def test_release_candidate_is_never_downgraded(self):
        # The bug: int('7-rc1') raised, the fallback was `latest != current`,
        # and an rc was told to "update" to the release below it.
        self.assertFalse(_is_newer('1.8.6', '1.8.7-rc1'))

    def test_release_supersedes_its_candidate(self):
        self.assertTrue(_is_newer('1.8.7', '1.8.7-rc1'))

    def test_later_candidate_supersedes_earlier(self):
        self.assertTrue(_is_newer('1.8.7-rc2', '1.8.7-rc1'))

    def test_same_version_is_not_an_update(self):
        self.assertFalse(_is_newer('1.8.6', '1.8.6'))

    def test_never_goes_backwards(self):
        self.assertFalse(_is_newer('1.8.6', '1.9.0'))

    def test_double_digit_components_compare_numerically(self):
        self.assertTrue(_is_newer('1.10.0', '1.9.0'))

    def test_unparseable_means_no_update(self):
        # A missed update costs a delayed upgrade; a wrong one replaces the
        # build someone is testing.
        self.assertFalse(_is_newer('1.8.6', 'garbage'))
        self.assertFalse(_is_newer('garbage', '1.8.6'))
