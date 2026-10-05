"""
The learned-folder index kept between attribution ticks (folder_index_for_org).

Real database: run against a THROWAWAY Postgres only (never server/.env):

    python manage.py test tracker.folder_index_state_test --noinput < /dev/null

TransactionTestCase, not TestCase: the kept index opens its own REPEATABLE READ
transaction and falls back to a full build inside anyone else's, so under
TestCase the path being tested would never run.

What is being pinned:
  - the trigger logs every filing-relevant write, bulk .update() included, and
    tells additions ('a') from changes that may remove something ('o')
  - after any sequence of writes the kept index equals a full rebuild, exactly
  - a folder that gains a second project is dropped, and stays dropped
  - a commit that lands out of order is picked up, not skipped
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest import mock

import psycopg2
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import TransactionTestCase

from tracker.models import Block, Client, Organization, Project
from tracker.services import matter_attribution as ma

User = get_user_model()

NOW = datetime(2026, 10, 5, 15, 0, tzinfo=dt_timezone.utc)


class FolderIndexStateTests(TransactionTestCase):

    def setUp(self):
        ma._FOLDER_STATE.clear()
        self.org = Organization.objects.create(name='MTC', slug='mtc-fi', industry_type='marketing')
        self.user = User.objects.create_user('ae', email='ae@mtc.test', password='x')
        self.ford = Client.objects.create(org=self.org, name='Ford Dealers')
        self.chevy = Client.objects.create(org=self.org, name='Chevy')
        self.p_ford = Project.objects.create(org=self.org, client=self.ford, name='Spring Launch')
        self.p_ford2 = Project.objects.create(org=self.org, client=self.ford, name='Social')
        self.p_chevy = Project.objects.create(org=self.org, client=self.chevy, name='Fall')
        self.now = NOW

    def block(self, file_path, project=None, age=timedelta(days=1), **kw):
        start = self.now - age
        return Block.objects.create(
            org=self.org, user=self.user, hostname='mac', start=start,
            end=start + timedelta(minutes=10), file_path=file_path,
            client=project.client if project else self.ford, project=project, **kw)

    def log(self):
        with connection.cursor() as cur:
            cur.execute('SELECT block_id, kind FROM tracker_blockfilinglog'
                        ' WHERE org_id = %s ORDER BY id', [self.org.id])
            return cur.fetchall()

    def tick(self):
        """One sweep's view of the index; asserts it equals a full rebuild."""
        stats = {}
        with mock.patch.object(ma.timezone, 'now', return_value=self.now):
            got = ma.folder_index_for_org(self.org, stats=stats)
        want = ma.build_folder_index(self.org, self.now - timedelta(days=ma.FOLDER_LOOKBACK_DAYS))
        self.assertEqual(got, want)
        return got, stats.get('folder_index')

    # -- the trigger ---------------------------------------------------------

    def test_trigger_logs_bulk_update_and_classifies_it(self):
        b = self.block('/Users/ae/Dropbox/Ford/Spring/a.psd')
        self.assertEqual(self.log(), [], 'an unfiled insert contributes nothing')
        Block.objects.filter(id=b.id).update(project=self.p_ford)
        self.assertEqual(self.log(), [(b.id, 'a')])
        Block.objects.filter(id=b.id).update(title='renamed', notes='x')
        self.assertEqual(len(self.log()), 1, 'columns the index ignores are not logged')
        Block.objects.filter(id=b.id).update(project=self.p_ford2)
        self.assertEqual(self.log()[-1], (b.id, 'o'))

        c = self.block('/Users/ae/Dropbox/Ford/Spring/b.psd', project=self.p_ford)
        self.assertEqual(self.log()[-1], (c.id, 'a'), 'inserted already filed')
        Block.objects.filter(id=c.id).update(deleted_at=self.now)
        self.assertEqual(self.log()[-1], (c.id, 'o'), 'soft delete')
        d = self.block('/Users/ae/Dropbox/Ford/Spring/d.psd', project=self.p_ford)
        Block.all_objects.filter(id=d.id).delete()
        self.assertEqual(self.log()[-1], (d.id, 'o'), 'hard delete')

        e = self.block('', project=self.p_ford)
        Block.objects.filter(id=e.id).update(project=self.p_ford2)
        self.assertEqual(self.log()[-1], (e.id, 'a'),
                         'a block with no path never contributed, so this only adds')

    # -- equivalence with the full rebuild -----------------------------------

    def test_incremental_ticks_equal_full_rebuild(self):
        spring = '/Users/ae/Dropbox/Ford/Spring'
        self.block(f'{spring}/a.psd', project=self.p_ford)
        self.block('/Users/ae/Dropbox/Chevy/Fall/a.psd', project=self.p_chevy)
        idx, mode = self.tick()
        self.assertEqual(mode, 'rebuilt')
        self.assertEqual(idx[ma.folder_key(f'{spring}/a.psd')], self.p_ford.id)

        # The sweep files new work with bulk .update(): advanced, not rebuilt.
        b = self.block(f'{spring}/b.psd')
        new_folder = self.block('/Users/ae/Dropbox/Ford/Summer/a.psd')
        Block.objects.filter(id__in=[b.id, new_folder.id]).update(project=self.p_ford)
        idx, mode = self.tick()
        self.assertEqual(mode, 'advanced')
        self.assertIn(ma.folder_key(new_folder.file_path), idx)

        # Nothing changed: still advanced, still exact.
        self.assertEqual(self.tick()[1], 'advanced')

        # A re-file may remove a contribution: rebuilt, and exact.
        Block.objects.filter(id=new_folder.id).update(project=self.p_ford2)
        idx, mode = self.tick()
        self.assertEqual(mode, 'rebuilt')
        self.assertEqual(idx[ma.folder_key(new_folder.file_path)], self.p_ford2.id)

        Block.objects.filter(id=new_folder.id).update(project=None)
        idx, mode = self.tick()
        self.assertNotIn(ma.folder_key(new_folder.file_path), idx)

    def test_second_project_drops_folder_and_it_stays_dropped(self):
        shared = '/Users/ae/Dropbox/Ford/Admin'
        self.block(f'{shared}/a.docx', project=self.p_ford)
        idx, _ = self.tick()
        self.assertIn(ma.folder_key(f'{shared}/a.docx'), idx)

        # Gaining a second project is an ADDITION — the advance path handles it.
        other = self.block(f'{shared}/b.docx')
        Block.objects.filter(id=other.id).update(project=self.p_ford2)
        idx, mode = self.tick()
        self.assertEqual(mode, 'advanced')
        self.assertNotIn(ma.folder_key(f'{shared}/a.docx'), idx)

        # More filings for the first project do not bring it back.
        for name in ('c', 'd', 'e'):
            x = self.block(f'{shared}/{name}.docx')
            Block.objects.filter(id=x.id).update(project=self.p_ford)
            idx, _ = self.tick()
            self.assertNotIn(ma.folder_key(f'{shared}/a.docx'), idx)

    def test_trailing_edge_ages_out_without_rebuild(self):
        edge = timedelta(days=ma.FOLDER_LOOKBACK_DAYS)
        old = '/Users/ae/Dropbox/Ford/Old'
        # A conflict held up only by a block about to leave the window.
        self.block(f'{old}/a.docx', project=self.p_ford, age=edge - timedelta(hours=1))
        self.block(f'{old}/b.docx', project=self.p_ford2, age=timedelta(days=3))
        self.block('/Users/ae/Dropbox/Ford/Gone/a.docx', project=self.p_ford,
                   age=edge - timedelta(hours=2))
        idx, _ = self.tick()
        self.assertNotIn(ma.folder_key(f'{old}/a.docx'), idx)

        self.now = NOW + timedelta(hours=3)
        idx, mode = self.tick()
        self.assertEqual(mode, 'advanced')
        self.assertEqual(idx.get(ma.folder_key(f'{old}/a.docx')), self.p_ford2.id)
        self.assertNotIn(ma.folder_key('/Users/ae/Dropbox/Ford/Gone/a.docx'), idx)

    def test_state_older_than_max_age_rebuilds(self):
        self.block('/Users/ae/Dropbox/Ford/Spring/a.psd', project=self.p_ford)
        self.tick()
        self.now = NOW + ma.FOLDER_STATE_MAX_AGE + timedelta(minutes=1)
        self.assertEqual(self.tick()[1], 'rebuilt')

    def test_out_of_order_commit_is_not_skipped(self):
        """
        A transaction that started before a tick and commits after it must be
        seen by the next tick. A serial-id watermark would skip it.
        """
        self.block('/Users/ae/Dropbox/Ford/Spring/a.psd', project=self.p_ford)
        late = self.block('/Users/ae/Dropbox/Ford/Late/a.psd')
        self.tick()

        params = connection.get_connection_params()
        params.pop('cursor_factory', None)
        other = psycopg2.connect(**params)
        try:
            with other.cursor() as cur:   # opens a transaction, left uncommitted
                cur.execute('UPDATE tracker_block SET project_id = %s WHERE id = %s',
                            [self.p_ford.id, late.id])
            # A later write that commits first.
            early = self.block('/Users/ae/Dropbox/Ford/Early/a.psd', project=self.p_ford)
            idx, _ = self.tick()
            self.assertIn(ma.folder_key(early.file_path), idx)
            self.assertNotIn(ma.folder_key(late.file_path), idx)
            other.commit()
        finally:
            other.close()
        idx, mode = self.tick()
        self.assertEqual(mode, 'advanced')
        self.assertEqual(idx.get(ma.folder_key(late.file_path)), self.p_ford.id)

    # -- fallbacks and housekeeping ------------------------------------------

    def test_inside_a_callers_transaction_it_builds_in_full(self):
        self.block('/Users/ae/Dropbox/Ford/Spring/a.psd', project=self.p_ford)
        with transaction.atomic():
            idx = ma.folder_index_for_org(self.org)
        self.assertEqual(len(idx), 1)
        self.assertEqual(ma._FOLDER_STATE, {}, 'no state kept from inside a transaction')

    def test_sweep_files_a_sibling_through_the_kept_index(self):
        spring = '/Users/ae/Dropbox/Ford/Spring'
        self.block(f'{spring}/a.psd', project=self.p_ford, age=timedelta(days=20))
        ma.attribute_matters_for_org(self.org, days=2)          # builds the state
        sibling = self.block(f'{spring}/b.psd', age=timedelta(hours=1))
        stats = ma.attribute_matters_for_org(self.org, days=2)
        self.assertEqual(stats['folder_index'], 'advanced')
        sibling.refresh_from_db()
        self.assertEqual(sibling.project_id, self.p_ford.id)

    def test_prune_drops_only_old_entries(self):
        b = self.block('/Users/ae/Dropbox/Ford/Spring/a.psd', project=self.p_ford)
        c = self.block('/Users/ae/Dropbox/Ford/Spring/b.psd', project=self.p_ford)
        with connection.cursor() as cur:
            cur.execute("UPDATE tracker_blockfilinglog SET at = now() - interval '25 hours'"
                        " WHERE block_id = %s", [b.id])
        self.assertEqual(ma.prune_filing_log(), 1)
        self.assertEqual(self.log(), [(c.id, 'a')])
