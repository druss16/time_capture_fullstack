"""
Folding imported "project clients" into their real client.

Real database: THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.client_conversion_test --noinput < /dev/null

What is pinned:
  - project mode: the folded client becomes a project of the parent; its
    unprojected blocks get that project, projected ones keep theirs (which
    moves under the parent), and the client is deactivated, never deleted
  - merge mode moves everything and makes no project
  - a dry run writes nothing
  - history keeps the old client; an outside-system link stays in project mode;
    a row the parent already has stays and is reported
  - a block is moved without re-running the classifier on it
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from tracker.models import (
    Block, ClassificationAudit, Client, ClientAssignment, ClientBillingProfile,
    ClientGroup, Organization, Project,
)
from tracker.services.client_conversion import (
    MODE_MERGE, ConversionError, fold_clients,
)

User = get_user_model()
T0 = datetime(2026, 10, 6, 14, 0, tzinfo=dt_timezone.utc)


class FoldClientsTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='MTC', slug='mtc-fold', industry_type='marketing')
        self.user = User.objects.create_user('pat', email='a@mtc.test', password='x')
        self.acme = Client.objects.create(org=self.org, name='Acme Motors')
        self.spring = Client.objects.create(org=self.org, name='Acme Spring Campaign',
                                            aliases=['Spring Launch'])
        self.refresh = Client.objects.create(org=self.org, name='Acme Brand Refresh')
        self._n = 0

    def block(self, client, project=None, minutes=20):
        self._n += 1
        s = T0 + timedelta(minutes=30 * self._n)
        return Block.objects.create(
            org=self.org, user=self.user, hostname='mac', device_id='d1', start=s,
            end=s + timedelta(minutes=minutes), day=s.date(), minutes=minutes,
            app_name='Adobe Photoshop', title='x.psd', window_title='x.psd',
            classification_state='committed', is_categorized=True, is_billable=True,
            client=client, project=project, categorized_by='ai')

    def fold(self, *olds, parent=None, **kw):
        return fold_clients(self.org.id, (parent or self.acme).id, [c.id for c in olds], **kw)

    def test_project_mode_files_time_under_the_parent(self):
        loose = self.block(self.spring)
        own = Project.objects.create(org=self.org, client=self.spring, name='Radio Cut')
        projected = self.block(self.spring, project=own)

        [r] = self.fold(self.spring, apply=True)

        proj = Project.objects.get(client=self.acme, name='Acme Spring Campaign')
        loose.refresh_from_db(); projected.refresh_from_db(); own.refresh_from_db(); self.spring.refresh_from_db()
        self.assertEqual((loose.client_id, loose.project_id), (self.acme.id, proj.id))
        self.assertEqual((projected.client_id, projected.project_id), (self.acme.id, own.id))
        self.assertEqual(own.client_id, self.acme.id)
        self.assertFalse(self.spring.is_active)
        self.assertEqual((r.block_count, r.block_minutes, r.blocks_given_project), (2, 40, 1))
        self.assertEqual(r.project_source, 'created')
        self.assertEqual(r.aliases_left, ['Spring Launch'])

    def test_dry_run_writes_nothing(self):
        b = self.block(self.spring)
        [r] = self.fold(self.spring)
        b.refresh_from_db(); self.spring.refresh_from_db()
        self.assertEqual(b.client_id, self.spring.id)
        self.assertTrue(self.spring.is_active)
        self.assertFalse(Project.objects.filter(client=self.acme).exists())
        self.assertEqual(r.block_count, 1)   # but the report still says what would move

    def test_merge_mode_makes_no_project(self):
        dup = Client.objects.create(org=self.org, name='AM')
        b = self.block(dup)
        self.fold(dup, mode=MODE_MERGE, apply=True)
        b.refresh_from_db()
        self.assertEqual((b.client_id, b.project_id), (self.acme.id, None))
        self.assertFalse(Project.objects.filter(client=self.acme).exists())

    def test_reuses_the_parents_project_of_that_name(self):
        existing = Project.objects.create(org=self.org, client=self.acme, name=self.spring.name)
        b = self.block(self.spring)
        [r] = self.fold(self.spring, apply=True)
        b.refresh_from_db()
        self.assertEqual(b.project_id, existing.id)
        self.assertEqual(r.project_source, 'existing on parent')

    def test_own_project_with_a_name_the_parent_uses_is_renamed(self):
        Project.objects.create(org=self.org, client=self.acme, name='Social Ads')
        clash = Project.objects.create(org=self.org, client=self.refresh, name='Social Ads')
        self.fold(self.refresh, apply=True)
        clash.refresh_from_db()
        self.assertEqual((clash.client_id, clash.name),
                         (self.acme.id, 'Social Ads (Acme Brand Refresh)'))

    def test_history_stays_and_conflicts_are_left(self):
        b = self.block(self.spring)
        audit = ClassificationAudit.objects.create(block=b, source='ai', client_after=self.spring)
        ClientAssignment.objects.create(organization=self.org, client=self.acme, user=self.user)
        dup_assign = ClientAssignment.objects.create(organization=self.org, client=self.spring, user=self.user)
        profile = ClientBillingProfile.objects.create(client=self.spring, org=self.org)
        group = ClientGroup.objects.create(org=self.org, name='Dealers')
        group.clients.add(self.spring)

        [r] = self.fold(self.spring, apply=True)

        audit.refresh_from_db(); dup_assign.refresh_from_db(); profile.refresh_from_db()
        self.assertEqual(audit.client_after_id, self.spring.id)          # history
        self.assertEqual(dup_assign.client_id, self.spring.id)           # parent already had one
        self.assertEqual(r.left_conflict['ClientAssignment.client'], 1)
        self.assertEqual(profile.client_id, self.spring.id)              # outside-system link
        self.assertEqual(r.left_identity['ClientBillingProfile.client'], 1)
        self.assertEqual(set(group.clients.values_list('id', flat=True)), {self.acme.id})

    def test_billing_profile_moves_in_merge_mode(self):
        dup = Client.objects.create(org=self.org, name='AM')
        profile = ClientBillingProfile.objects.create(client=dup, org=self.org)
        self.fold(dup, mode=MODE_MERGE, apply=True)
        profile.refresh_from_db()
        self.assertEqual(profile.client_id, self.acme.id)

    def test_moving_a_block_does_not_reclassify_it(self):
        self.block(self.spring)
        with mock.patch('django.db.models.signals.post_save.send') as send:
            self.fold(self.spring, apply=True)
        senders = [c.kwargs.get('sender') or (c.args[0] if c.args else None) for c in send.call_args_list]
        self.assertNotIn(Block, senders)

    def test_rollups_rebuilt_for_moved_days(self):
        self.block(self.spring)
        with mock.patch('tracker.services.client_conversion.rebuild_rollups') as rebuild:
            self.fold(self.spring, apply=True)
        rebuild.assert_called_once_with(self.org.id, {date(2026, 10, 6)})

    def test_refusals(self):
        other = Organization.objects.create(name='Other', slug='other-fold')
        stranger = Client.objects.create(org=other, name='Stranger')
        with self.assertRaises(ConversionError):
            self.fold(self.acme)                                     # into itself
        with self.assertRaises(ConversionError):
            fold_clients(self.org.id, self.acme.id, [stranger.id])   # other org
        internal = Client.objects.create(org=self.org, name='Internal')
        with self.assertRaises(ConversionError):
            self.fold(internal)

    def test_command_dry_run_output(self):
        self.block(self.spring)
        from io import StringIO
        out = StringIO()
        call_command('fold_clients', org_id=self.org.id, parent=self.acme.id,
                     clients=f'{self.spring.id},{self.refresh.id}', stdout=out)
        text = out.getvalue()
        self.assertIn('DRY RUN', text)
        self.assertIn('Acme Spring Campaign', text)
        self.assertIn('2 clients, 1 blocks', text)
        self.spring.refresh_from_db()
        self.assertTrue(self.spring.is_active)
