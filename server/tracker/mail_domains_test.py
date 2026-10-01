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

    def _mail(self, domain, *, user=None, days_ago=1, client=None, subject='', org=None,
              direction='in', from_address=None):
        self.n += 1
        return MailSignal.objects.create(
            org=org or self.org, user=user or self.owner, provider='google',
            external_id=f'm{self.n}', occurred_at=timezone.now() - timedelta(days=days_ago),
            direction=direction, other_party_domain=domain, extracted_client=client,
            subject=subject, from_address=from_address)

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


# ─── Signal-first ordering, automated classification, initials tier ─────────

# Dan's real "Seen but not mapped" list: domain → (messages, meetings).
DAN_DOMAINS = {
    'clio.com': (27, 0), 'df-cpas.com': (10, 1), 'google.com': (11, 0),
    'kishmish.com': (10, 0), 'ccf-law.com': (7, 0), 'meliopayments.com': (6, 0),
    'mail.apollo.io': (5, 0), 'stripe.com': (5, 0), 'apollo.io': (4, 0), 'dnb.com': (4, 0),
    'fundinnovationventure.com': (4, 0), 'tlwallaccounting.com': (4, 0), 'vyde.io': (4, 0),
    'fustcharles.com': (3, 0), 'morethancars.com': (2, 1), 'raymondjames.com': (3, 0),
    'send.calendly.com': (3, 0), 'email.americanexpress.com': (2, 0),
    'email.neon.tech': (2, 0), 'followups.typeform.io': (2, 0), 'juno.tax': (1, 1),
    'microsoft.com': (2, 0), 'user.hostinger.com': (2, 0), 'ar.neon.tech': (1, 0),
    'dp.intuit.com': (1, 0), 'e.stripe.com': (1, 0), 'em1.cloudflare.com': (1, 0),
    'emails.hostinger.com': (1, 0), 'improvmx.com': (1, 0), 'lemoyne.edu': (1, 0),
    'mail.dnb.com': (1, 0), 'microsoftonline.com': (1, 0), 'neon.tech': (1, 0),
    'notify.cloudflare.com': (1, 0), 'send.xero.com': (1, 0), 'tryapollo.io': (1, 0),
    'updates.hostinger.com': (1, 0), 'updates.notion.com': (1, 0),
}
DAN_PEOPLE = {
    'df-cpas.com', 'morethancars.com', 'juno.tax', 'kishmish.com', 'ccf-law.com',
    'fundinnovationventure.com', 'tlwallaccounting.com', 'vyde.io', 'fustcharles.com',
    'raymondjames.com', 'lemoyne.edu',
}
DAN_CLIENTS = [
    'April Showers LLC', 'Aurelia', 'Beck CPA', 'Dauphin & Fantacone', 'Internal',
    'Internal - Tax', "Little Nero's Pizza", "Lola's Pet Shop", 'Lupkynis', 'MAVOPS',
    'Marta Vance', 'PureADK', 'Ridgeline Holdings LLC', "St. Mary's Church - Alaska",
    'Test Client A', 'Test Client B', 'Testing 2',
]


class DanFixtureTest(Base):
    """Dan's real list (all inbound; meetings as calendar attendees)."""

    def setUp(self):
        super().setUp()
        Client.objects.filter(org=self.org).delete()
        for i, name in enumerate(DAN_CLIENTS):
            Client.objects.create(org=self.org, name=name, code=f'D{i}')
        for d, (msgs, meetings) in DAN_DOMAINS.items():
            for _ in range(msgs):
                self._mail(d)
            for _ in range(meetings):
                self._event([d])

    def test_split_people_first_automated_after(self):
        rows = svc.observed_domains(self.org)
        self.assertEqual(len(rows), 38)
        top = [r['domain'] for r in rows if not r['automated']]
        auto = [r['domain'] for r in rows if r['automated']]
        self.assertEqual(set(top), DAN_PEOPLE)
        self.assertEqual(set(auto), set(DAN_DOMAINS) - DAN_PEOPLE)
        self.assertEqual([r['domain'] for r in rows[:len(top)]], top)
        # The three with a meeting lead, df-cpas (most mail) first.
        self.assertEqual(top[:3], ['df-cpas.com', 'morethancars.com', 'juno.tax'])
        self.assertTrue(all(r['automated_reason'] for r in rows if r['automated']))

    def test_exactly_one_suggestion(self):
        rows = svc.observed_domains(self.org)
        sugg = {r['domain']: r['suggestion'] for r in rows if r['suggestion']}
        self.assertEqual(list(sugg), ['df-cpas.com'])
        s = sugg['df-cpas.com']
        self.assertEqual(s['client_name'], 'Dauphin & Fantacone')
        self.assertEqual(s['tier'], 'initials')
        self.assertIn('initials', s['reason'])


class RankingAndAutomatedTest(Base):
    def test_meetings_and_outbound_outrank_inbound_bulk(self):
        for _ in range(30):
            self._mail('bulkletter.example')
        self._mail('wrote.example', direction='out')
        self._event(['met.example'])
        self._mail('quiet.example')
        rows = svc.observed_domains(self.org)
        self.assertEqual([r['domain'] for r in rows],
                         ['met.example', 'wrote.example', 'bulkletter.example', 'quiet.example'])
        w = next(r for r in rows if r['domain'] == 'wrote.example')
        self.assertEqual((w['outbound'], w['inbound']), (1, 0))

    def test_more_people_ranks_higher(self):
        self._mail('one.example')
        self._mail('one.example')
        self._mail('two.example')
        self._mail('two.example', user=self.member)
        self.assertEqual([r['domain'] for r in svc.observed_domains(self.org)],
                         ['two.example', 'one.example'])

    def test_vendor_not_automated_with_meeting_or_outbound(self):
        self._mail('clio.com')
        self._mail('stripe.com')
        self._mail('stripe.com', direction='out')
        self._mail('send.calendly.com')
        self._event(['send.calendly.com'])
        rows = {r['domain']: r for r in svc.observed_domains(self.org)}
        self.assertTrue(rows['clio.com']['automated'])
        self.assertFalse(rows['stripe.com']['automated'])
        self.assertFalse(rows['send.calendly.com']['automated'])
        self.assertEqual(rows['stripe.com']['automated_reason'], '')

    def test_classify(self):
        c = svc.classify_automated
        self.assertTrue(c('em2847.acme.com')[0])
        self.assertTrue(c('news.acme.com')[0])
        self.assertTrue(c('e.stripe.com')[0])
        self.assertTrue(c('billing.clio.com')[0])          # vendor via registrable domain
        self.assertFalse(c('acme.com')[0])
        self.assertFalse(c('email.com')[0])                 # no subdomain: not judged by name
        self.assertFalse(c('clio.com', events=1)[0])
        self.assertFalse(c('clio.com', outbound=2)[0])

    def test_sender_local_part(self):
        for _ in range(3):
            self._mail('saasy.example', from_address='no-reply@saasy.example')
        self._mail('saasy.example', from_address='jo@saasy.example')
        self._mail('person.example', from_address='jo@person.example')
        self._mail('person.example', from_address='billing@person.example')
        rows = {r['domain']: r for r in svc.observed_domains(self.org)}
        self.assertTrue(rows['saasy.example']['automated'])
        self.assertIn('no-reply', rows['saasy.example']['automated_reason'])
        self.assertFalse(rows['person.example']['automated'])  # half is not most


class BulkIgnoreTest(Base):
    def test_bulk_ignore(self):
        for d in ('a.example', 'b.example', 'keep.example'):
            self._mail(d)
        c = APIClient()
        c.force_authenticate(self.owner)
        r = c.post(URL + 'ignored/bulk/', {'domains': ['a.example', 'B.example', 'bad']},
                   format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(sorted(i['domain'] for i in r.data['ignored']), ['a.example', 'b.example'])
        self.assertEqual([f['domain'] for f in r.data['failed']], ['bad'])
        self.assertEqual([o['domain'] for o in c.get(URL + 'observed/').data['observed']],
                         ['keep.example'])
        # Idempotent, and managers can't.
        self.assertEqual(c.post(URL + 'ignored/bulk/', {'domains': ['a.example']},
                                format='json').status_code, 200)
        self.assertEqual(IgnoredEmailDomain.objects.filter(org=self.org).count(), 2)
        m = APIClient()
        m.force_authenticate(self.manager)
        self.assertEqual(m.post(URL + 'ignored/bulk/', {'domains': ['keep.example']},
                                format='json').status_code, 403)


class InitialsTierTest(Base):
    def ctx(self):
        return svc.SuggestionContext.for_org(self.org)

    def test_hyphen_and_joined(self):
        df = Client.objects.create(org=self.org, name='Dauphin & Fantacone')
        for d in ('df-cpas.com', 'dfcpas.com', 'df-law.com', 'cpa-df.com', 'df.com'):
            s = svc.suggest_client(d, self.ctx())
            self.assertEqual(s and s['client_id'], df.id, d)
            self.assertEqual(s['tier'], 'initials')
        self.assertIsNone(svc.suggest_client('dfx-cpas.com', self.ctx()))

    def test_entity_suffix_excluded_and_kept_variant(self):
        abc = Client.objects.create(org=self.org, name='Alpha Beta Corp')
        self.assertEqual(svc.suggest_client('abc.com', self.ctx())['client_id'], abc.id)
        self.assertEqual(svc.suggest_client('ab-llc.com', self.ctx())['client_id'], abc.id)
        xy = Client.objects.create(org=self.org, name='Xeno Yarrow LLC')
        self.assertEqual(svc.suggest_client('xy.com', self.ctx())['client_id'], xy.id)
        self.assertIsNone(svc.suggest_client('xyl.com', self.ctx()))

    def test_ambiguous_initials(self):
        Client.objects.create(org=self.org, name='Dauphin & Fantacone')
        Client.objects.create(org=self.org, name='Delta Foods')
        self.assertIsNone(svc.suggest_client('df-cpas.com', self.ctx()))

    def test_one_letter_rejected(self):
        Client.objects.create(org=self.org, name='Beck CPA')    # core initials: b
        Client.objects.create(org=self.org, name='Zorro')
        self.assertIsNone(svc.suggest_client('b-cpas.com', self.ctx()))
        self.assertIsNone(svc.suggest_client('z.com', self.ctx()))
        self.assertEqual(svc.client_initials('Zorro'), set())
        self.assertEqual(svc.client_initials('Testing 2'), set())

    def test_stronger_tier_wins(self):
        # "Delta Foods" (df) exists, but dfgroup.com is in another client's
        # aliases: tier 1 wins, the initials tier is never consulted.
        Client.objects.create(org=self.org, name='Delta Foods')
        other = Client.objects.create(org=self.org, name='Other Co', aliases=['dfgroup.com'])
        s = svc.suggest_client('dfgroup.com', self.ctx())
        self.assertEqual((s['client_id'], s['tier']), (other.id, 'domain'))
        # A name-tier hit beats an initials hit on a different client.
        ac = Client.objects.create(org=self.org, name='Acmed')
        Client.objects.create(org=self.org, name='Alpha Charlie Media Echo Delta')
        s = svc.suggest_client('acmed.com', self.ctx())
        self.assertEqual((s['client_id'], s['tier']), (ac.id, 'name'))

    def test_ambiguous_strong_tier_does_not_fall_to_initials(self):
        Client.objects.create(org=self.org, name='Smith Family Trust')
        Client.objects.create(org=self.org, name='Smith Plumbing')
        Client.objects.create(org=self.org, name='Sam Mint Ink Tea Holdings')  # initials smith
        self.assertIsNone(svc.suggest_client('smith.com', self.ctx()))
