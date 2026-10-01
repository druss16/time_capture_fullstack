"""
Settings → Email domains (tracker/services/mail_domains.py + views_mail_domains.py).

Real database, so run against a THROWAWAY Postgres, never the default settings
(the local docker DB is production):

    python manage.py test tracker.mail_domains_test --noinput < /dev/null
"""
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from tracker.models import (
    CalendarEvent, Client, IgnoredEmailDomain, MailSignal, Organization,
    OrganizationMembership, OrgCalendarRule, UserIntegration,
)
from tracker.services import mail_domains as svc

User = get_user_model()
URL = '/api/settings/email-domains/'


class Base(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Firm', slug='firm')
        self.owner = self._user('owner', 'owner')
        self.admin = self._user('admin', 'admin')
        self.manager = self._user('manager', 'manager')
        self.member = self._user('member', 'member')
        UserIntegration.objects.create(
            user=self.owner, org=self.org, provider='gmail', is_connected=True,
            provider_email='owner@firmcpa.com')
        self.acme = Client.objects.create(org=self.org, name='Acme Widgets, Inc.')
        self.pure = Client.objects.create(org=self.org, name='PureADK Holdings')
        self.n = 0

    def _user(self, name, role, org=None, domain='firmcpa.com'):
        u = User.objects.create_user(name + str(id(self)), email=f'{name}@{domain}', password='x')
        OrganizationMembership.objects.create(user=u, organization=org or self.org, role=role)
        return u

    def _mail(self, domain, *, user=None, days_ago=1, client=None, subject='', org=None):
        self.n += 1
        return MailSignal.objects.create(
            org=org or self.org, user=user or self.owner, provider='google',
            external_id=f'm{self.n}', occurred_at=timezone.now() - timedelta(days=days_ago),
            direction='in', other_party_domain=domain, extracted_client=client,
            subject=subject)

    def _event(self, domains, *, user=None, days_ago=1, title='Catch up', client=None):
        self.n += 1
        start = timezone.now() - timedelta(days=days_ago)
        return CalendarEvent.objects.create(
            org=self.org, user=user or self.owner, provider='google', external_id=f'e{self.n}',
            title=title, start=start, end=start + timedelta(hours=1), extracted_client=client,
            attendees=[{'email': f'x@{d}', 'domain': d, 'response': 'accepted'} for d in domains])


class NormalizeValidateTest(Base):
    def test_normalize(self):
        for raw in ('acme.com', 'ACME.com', '@acme.com', 'jo@acme.com', 'https://www.acme.com/about',
                    'http://acme.com:8080/x?y=1', ' www.acme.com. '):
            self.assertEqual(svc.normalize_domain(raw), 'acme.com', raw)
        for raw in ('', 'acme', 'not a domain', 'http://', '@'):
            self.assertEqual(svc.normalize_domain(raw), '', raw)

    def test_rejects_public_own_duplicate_and_bad(self):
        with self.assertRaises(svc.DomainError) as e:
            svc.validate_new_domain(self.org, 'Gmail.com')
        self.assertEqual(e.exception.code, 'public')
        with self.assertRaises(svc.DomainError) as e:
            svc.validate_new_domain(self.org, 'comcast.net')  # wider free-mail list
        self.assertEqual(e.exception.code, 'public')
        with self.assertRaises(svc.DomainError) as e:
            svc.validate_new_domain(self.org, 'firmcpa.com')
        self.assertEqual(e.exception.code, 'own_domain')
        with self.assertRaises(svc.DomainError):
            svc.validate_new_domain(self.org, 'nope')
        svc.create_mapping(self.org, 'acme.com', self.acme.id)
        with self.assertRaises(svc.DomainError) as e:
            svc.create_mapping(self.org, 'https://www.ACME.com', self.pure.id)
        self.assertEqual(e.exception.code, 'duplicate')

    def test_client_must_belong_to_org(self):
        other = Organization.objects.create(name='Other', slug='other')
        foreign = Client.objects.create(org=other, name='Foreign Co')
        with self.assertRaises(svc.DomainError):
            svc.create_mapping(self.org, 'foreign.com', foreign.id)

    def test_subdomains_not_covered(self):
        """Documented decision: a mapping is exact; the matcher does equality."""
        from tracker.mail_matching import match_by_domain_rule
        svc.create_mapping(self.org, 'acme.com', self.acme.id)
        self.assertIsNotNone(match_by_domain_rule('acme.com', self.org))
        self.assertIsNone(match_by_domain_rule('mail.acme.com', self.org))


class ObservedTest(Base):
    def test_aggregation_and_exclusions(self):
        self._mail('newclient.com')
        self._mail('newclient.com', user=self.member, days_ago=3)
        self._event(['newclient.com', 'firmcpa.com'])
        self._mail('gmail.com')                       # public
        self._mail('firmcpa.com')                     # own
        self._mail('acme.com')                        # will be mapped
        self._mail('bank.example')                    # will be ignored
        self._mail('ancient.com', days_ago=200)       # outside window
        svc.create_mapping(self.org, 'acme.com', self.acme.id)
        IgnoredEmailDomain.objects.create(org=self.org, domain='bank.example')

        rows = {r['domain']: r for r in svc.observed_domains(self.org, 90)}
        self.assertEqual(set(rows), {'newclient.com'})
        r = rows['newclient.com']
        self.assertEqual((r['messages'], r['events'], r['users']), (2, 1, 2))
        self.assertIsNotNone(r['last_seen'])

    def test_other_org_isolated(self):
        other = Organization.objects.create(name='Other', slug='other')
        ou = self._user('ou', 'owner', org=other, domain='otherfirm.com')
        self._mail('secretclient.com', user=ou, org=other)
        self.assertEqual(svc.observed_domains(self.org), [])


class SuggestionTest(Base):
    def ctx(self):
        return svc.SuggestionContext.for_org(self.org)

    def test_confident_name_hit(self):
        s = svc.suggest_client('acmewidgets.com', self.ctx())
        self.assertEqual(s['client_id'], self.acme.id)
        s = svc.suggest_client('mail.acme-widgets.co.uk', self.ctx())
        self.assertEqual(s['client_id'], self.acme.id)

    def test_single_distinctive_token(self):
        self.assertEqual(svc.suggest_client('pureadk.com', self.ctx())['client_id'], self.pure.id)

    def test_client_email_and_alias_domain(self):
        c = Client.objects.create(org=self.org, name='Zeta Partners', email='ap@zp-group.net')
        self.assertEqual(svc.suggest_client('zp-group.net', self.ctx())['client_id'], c.id)
        d = Client.objects.create(org=self.org, name='Omega LLC', aliases=['omegahq.io'])
        self.assertEqual(svc.suggest_client('omegahq.io', self.ctx())['client_id'], d.id)

    def test_ambiguous_returns_none(self):
        Client.objects.create(org=self.org, name='Smith Family Trust')
        Client.objects.create(org=self.org, name='Smith Plumbing')
        self.assertIsNone(svc.suggest_client('smith.com', self.ctx()))
        # Exact name match, but a sibling shares the prefix: still none.
        Client.objects.create(org=self.org, name='Delta Corp')
        Client.objects.create(org=self.org, name='Delta Payroll LLC')
        self.assertIsNone(svc.suggest_client('delta.com', self.ctx()))

    def test_generic_word_returns_none(self):
        Client.objects.create(org=self.org, name='Services')
        Client.objects.create(org=self.org, name='St Mary Church')
        self.assertIsNone(svc.suggest_client('services.com', self.ctx()))
        self.assertIsNone(svc.suggest_client('church.org', self.ctx()))
        self.assertIsNone(svc.suggest_client('unrelated.com', self.ctx()))

    def test_observed_rows_carry_suggestion(self):
        self._mail('pureadk.com')
        rows = svc.observed_domains(self.org)
        self.assertEqual(rows[0]['suggestion']['client_id'], self.pure.id)


class RematchTest(Base):
    def test_map_then_unmap_rematches_mail_and_calendar(self):
        sig = self._mail('newco.io')
        other = self._mail('elsewhere.io')
        ev = self._event(['newco.io'])
        change = svc.create_mapping(self.org, 'newco.io', self.acme.id)
        svc.rematch_mail_domain(self.org.id, change.domain, change.previous_client_id)
        sig.refresh_from_db(); other.refresh_from_db(); ev.refresh_from_db()
        self.assertEqual(sig.extracted_client_id, self.acme.id)
        self.assertIsNone(other.extracted_client_id)
        self.assertEqual(ev.extracted_client_id, self.acme.id)

        rule = OrgCalendarRule.objects.get(org=self.org, match_value='newco.io')
        change = svc.delete_mapping(self.org, rule.id)
        svc.rematch_mail_domain(self.org.id, change.domain, change.previous_client_id)
        sig.refresh_from_db(); ev.refresh_from_db()
        self.assertIsNone(sig.extracted_client_id)
        self.assertIsNone(ev.extracted_client_id)

    def test_unmap_keeps_subject_match(self):
        sig = self._mail('newco.io', subject='Re: PureADK Holdings year end')
        change = svc.create_mapping(self.org, 'newco.io', self.acme.id)
        svc.rematch_mail_domain(self.org.id, 'newco.io')
        sig.refresh_from_db()
        self.assertEqual(sig.extracted_client_id, self.acme.id)  # domain rule wins
        svc.delete_mapping(self.org, change.rule.id)
        svc.rematch_mail_domain(self.org.id, 'newco.io', self.acme.id)
        sig.refresh_from_db()
        self.assertEqual(sig.extracted_client_id, self.pure.id)  # subject still names a client

    def test_unmap_leaves_calendar_client_set_by_other_rule(self):
        ev = self._event(['newco.io'], client=self.pure)
        svc.rematch_calendar(self.org, 'newco.io', previous_client_id=self.acme.id)
        ev.refresh_from_db()
        self.assertEqual(ev.extracted_client_id, self.pure.id)


class ApiTest(Base):
    def api(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def test_admin_can_map_list_and_delete(self):
        self._mail('newco.io')
        with mock.patch.object(svc.rematch_mail_domain, 'delay') as delay, \
                self.captureOnCommitCallbacks(execute=True):
            r = self.api(self.admin).post(URL, {'domain': 'https://www.NewCo.io/', 'client_id': self.acme.id},
                                          format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['mapping']['domain'], 'newco.io')
        self.assertTrue(r.data['rematch_queued'])
        delay.assert_called_once_with(self.org.id, 'newco.io', None)

        r = self.api(self.owner).get(URL)
        self.assertEqual([m['domain'] for m in r.data['mappings']], ['newco.io'])
        self.assertFalse(r.data['covers_subdomains'])

        rid = r.data['mappings'][0]['id']
        with mock.patch.object(svc.rematch_mail_domain, 'delay') as delay, \
                self.captureOnCommitCallbacks(execute=True):
            r = self.api(self.admin).patch(f'{URL}{rid}/', {'client_id': self.pure.id}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['mapping']['client_id'], self.pure.id)
        delay.assert_called_once_with(self.org.id, 'newco.io', self.acme.id)

        with mock.patch.object(svc.rematch_mail_domain, 'delay') as delay, \
                self.captureOnCommitCallbacks(execute=True):
            r = self.api(self.admin).delete(f'{URL}{rid}/')
        self.assertEqual(r.status_code, 200)
        delay.assert_called_once_with(self.org.id, 'newco.io', self.pure.id)
        self.assertFalse(OrgCalendarRule.objects.filter(org=self.org).exists())

    def test_validation_errors_are_400_and_409(self):
        c = self.api(self.owner)
        with mock.patch.object(svc.rematch_mail_domain, 'delay'):
            self.assertEqual(c.post(URL, {'domain': 'gmail.com', 'client_id': self.acme.id},
                                    format='json').status_code, 400)
            self.assertEqual(c.post(URL, {'domain': 'firmcpa.com', 'client_id': self.acme.id},
                                    format='json').status_code, 400)
            self.assertEqual(c.post(URL, {'domain': 'acme.com', 'client_id': self.acme.id},
                                    format='json').status_code, 201)
            r = c.post(URL, {'domain': 'acme.com', 'client_id': self.pure.id}, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertIn('already mapped', r.data['error'])

    def test_manager_and_member_cannot_read_or_write(self):
        for u in (self.manager, self.member):
            c = self.api(u)
            self.assertEqual(c.get(URL).status_code, 403)
            self.assertEqual(c.get(URL + 'observed/').status_code, 403)
            self.assertEqual(c.post(URL, {'domain': 'x.com', 'client_id': self.acme.id},
                                    format='json').status_code, 403)
        self.assertFalse(OrgCalendarRule.objects.exists())

    def test_other_org_isolated(self):
        other = Organization.objects.create(name='Other', slug='other')
        oowner = self._user('oo', 'owner', org=other, domain='otherfirm.com')
        rule = OrgCalendarRule.objects.create(org=self.org, match_type='attendee_domain',
                                              match_value='acme.com', target_client=self.acme)
        c = self.api(oowner)
        self.assertEqual(c.get(URL).data['mappings'], [])
        self.assertEqual(c.delete(f'{URL}{rule.id}/').status_code, 404)
        # Can't map to another org's client either.
        r = c.post(URL, {'domain': 'acme.com', 'client_id': self.acme.id}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertTrue(OrgCalendarRule.objects.filter(id=rule.id).exists())

    def test_observed_bulk_and_ignore(self):
        self._mail('pureadk.com')
        self._mail('acmewidgets.com')
        self._mail('vendor.example')
        c = self.api(self.owner)
        obs = c.get(URL + 'observed/').data['observed']
        sugg = [{'domain': o['domain'], 'client_id': o['suggestion']['client_id']}
                for o in obs if o['suggestion']]
        self.assertEqual(len(sugg), 2)
        with mock.patch.object(svc.rematch_mail_domain, 'delay'):
            r = c.post(URL + 'bulk/', {'mappings': sugg + [{'domain': 'gmail.com',
                                                             'client_id': self.acme.id}]},
                       format='json')
        self.assertEqual(len(r.data['created']), 2)
        self.assertEqual(r.data['failed'][0]['code'], 'public')

        r = c.post(URL + 'ignored/', {'domain': 'vendor.example'}, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(c.get(URL + 'observed/').data['observed'], [])
        self.assertEqual(c.delete(f"{URL}ignored/{r.data['id']}/").status_code, 204)
        self.assertEqual([o['domain'] for o in c.get(URL + 'observed/').data['observed']],
                         ['vendor.example'])


class CommandTest(Base):
    def run_cmd(self, *args):
        out = StringIO()
        call_command('mail_domains', '--org', str(self.org.id), *args, stdout=out)
        return out.getvalue()

    def test_command_round_trip(self):
        sig = self._mail('newco.io')
        out = self.run_cmd('--observed')
        self.assertIn('newco.io', out)
        self.assertIn('unmapped', out)
        self.assertIn('Created: newco.io', self.run_cmd('--map', 'newco.io', str(self.acme.id)))
        self.assertIn('Updated: newco.io', self.run_cmd('--map', 'newco.io', str(self.pure.id)))
        self.assertIn('newco.io', self.run_cmd('--list'))
        self.assertIn('DRY RUN', self.run_cmd('--rematch'))
        sig.refresh_from_db()
        self.assertIsNone(sig.extracted_client_id)
        self.assertIn('APPLIED: 1', self.run_cmd('--rematch', '--apply'))
        sig.refresh_from_db()
        self.assertEqual(sig.extracted_client_id, self.pure.id)
        self.assertIn('Removed rule', self.run_cmd('--unmap', 'newco.io'))
        with self.assertRaises(CommandError):
            self.run_cmd('--map', 'gmail.com', str(self.acme.id))
