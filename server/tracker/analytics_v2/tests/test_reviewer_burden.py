"""
Who counts as a reviewer, and what that does to the queue number.

The case this exists for: at TL Wall some owners never open Daily Review, so
their unreviewed blocks inflated the queue while they were also counted in the
denominator as though sharing the load. But some owners ARE in the trenches
doing bookkeeping, so excluding by ROLE would throw away real reviewers.

The rule is therefore behavioural — did this person's queue actually get worked
— and these tests pin the four cases that matter.

NEEDS POSTGRES. See test_lens_smoke.py.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from tracker.analytics_v2.metrics.attribution import (
    HUMAN_RESOLUTIONS, MIN_RESOLUTIONS, reviewers_in,
)
from tracker.models import Block, Client, Organization, OrganizationMembership

User = get_user_model()


class ReviewerDetectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organization.objects.create(
            name="TL Wall", slug="tl-wall-test", plan="executive")
        cls.client_a = Client.objects.create(org=cls.org, name="Acme", code="ACME")

        def member(username, role):
            u = User.objects.create(username=username, email=f"{username}@x.test")
            OrganizationMembership.objects.create(
                organization=cls.org, user=u, role=role)
            return u

        # An owner who never touches a queue, an owner who is in the trenches,
        # and an ordinary member who reviews.
        cls.absent_owner = member("absent_owner", "owner")
        cls.working_owner = member("working_owner", "owner")
        cls.staffer = member("staffer", "member")

        cls._resolve(cls.working_owner, MIN_RESOLUTIONS + 2, days_ago=3)
        cls._resolve(cls.staffer, MIN_RESOLUTIONS + 2, days_ago=3)
        # The absent owner has blocks, but only the software ever moved them.
        cls._resolve(cls.absent_owner, 30, days_ago=3, by="classifier")

    @classmethod
    def _resolve(cls, user, n, *, days_ago, by="user"):
        now = timezone.now()
        for i in range(n):
            Block.objects.create(
                org=cls.org, user=user, hostname="h",
                start=now - timedelta(days=days_ago, hours=1),
                end=now - timedelta(days=days_ago),
                day=date.today() - timedelta(days=days_ago), minutes=30,
                client=cls.client_a, is_billable=True,
                classification_state="committed", is_categorized=True,
                state_changed_by=by,
                state_changed_at=now - timedelta(days=days_ago),
            )

    def test_an_owner_in_the_trenches_counts_as_a_reviewer(self):
        """The whole reason role is the wrong lever."""
        self.assertIn(self.working_owner.id, reviewers_in(self.org.id, None))

    def test_an_owner_who_never_reviews_does_not(self):
        """Their blocks were only ever moved by the classifier."""
        self.assertNotIn(self.absent_owner.id, reviewers_in(self.org.id, None))

    def test_a_reviewing_member_counts(self):
        self.assertIn(self.staffer.id, reviewers_in(self.org.id, None))

    def test_one_stray_click_is_not_a_habit(self):
        """MIN_RESOLUTIONS exists so a single confirmation doesn't enrol
        somebody as a reviewer for the next sixty days."""
        occasional = User.objects.create(username="occasional", email="o@x.test")
        OrganizationMembership.objects.create(
            organization=self.org, user=occasional, role="member")
        self._resolve(occasional, MIN_RESOLUTIONS - 1, days_ago=2)
        self.assertNotIn(occasional.id, reviewers_in(self.org.id, None))

    def test_stale_activity_falls_out_of_the_window(self):
        """Someone who reviewed a year ago is not reviewing now."""
        lapsed = User.objects.create(username="lapsed", email="l@x.test")
        OrganizationMembership.objects.create(
            organization=self.org, user=lapsed, role="member")
        self._resolve(lapsed, MIN_RESOLUTIONS + 5, days_ago=400)
        self.assertNotIn(lapsed.id, reviewers_in(self.org.id, None))

    def test_only_human_markers_count(self):
        """`mismatch_agent` is the software re-filing, and is deliberately not
        in HUMAN_RESOLUTIONS — otherwise the agent would enrol people as
        reviewers who never looked at anything."""
        self.assertNotIn("mismatch_agent", HUMAN_RESOLUTIONS)
        self.assertNotIn("classifier", HUMAN_RESOLUTIONS)
        self.assertNotIn("auto_commit_eod", HUMAN_RESOLUTIONS)
        self.assertIn("user", HUMAN_RESOLUTIONS)
