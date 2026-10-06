"""
QuickBooks connect link — see services/connect_link.py.
"""
from datetime import timedelta
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from tracker.models import Client, Integration, OrganizationMembership
from tracker.models_onboarding_console import ConnectLink
from tracker.models_task_type_sets import ExternalStaffMapping
from tracker.services import connect_link
from tracker.tests_onboarding_console import ConsoleBase

User = get_user_model()

QB = dict(QUICKBOOKS_CLIENT_ID='qbo-id', QUICKBOOKS_CLIENT_SECRET='qbo-secret',
          QUICKBOOKS_REDIRECT_URI='https://api.test/api/integrations/quickbooks/callback/',
          FRONTEND_URL='https://app.test')


def _ok_token(payload):
    resp = mock.Mock(status_code=200)
    resp.json.return_value = payload
    return resp


@override_settings(**QB)
class ConnectLinkTests(ConsoleBase):
    def setUp(self):
        super().setUp()
        self.p = self.make_project()
        self.org = self.p.organization
        self.public = APIClient()

    def issue(self, providers=('quickbooks',), email=''):
        r = self.api.post(f'/api/onboard/projects/{self.p.id}/connect-link/',
                          {'providers': list(providers), 'email': email}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()['url'].rsplit('/', 1)[1]

    def start(self, raw, provider='quickbooks'):
        return self.public.post(f'/api/onboard/connect/{raw}/{provider}/start/')

    # ── operator side ──
    def test_only_operators_can_issue(self):
        r = APIClient().post(f'/api/onboard/projects/{self.p.id}/connect-link/',
                             {'providers': ['quickbooks']}, format='json')
        self.assertIn(r.status_code, (401, 403))

    def test_issue_filters_providers_and_retires_old_link(self):
        first = self.issue()
        self.issue(providers=('quickbooks', 'qb_time', 'xero'))
        link = ConnectLink.objects.filter(revoked_at__isnull=True).get()
        self.assertEqual(link.providers, ['quickbooks', 'qb_time'])
        self.assertEqual(self.public.get(f'/api/onboard/connect/{first}/').status_code, 404)

    def test_issue_needs_a_provider(self):
        r = self.api.post(f'/api/onboard/projects/{self.p.id}/connect-link/',
                          {'providers': []}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_email_is_sent_when_given(self):
        with mock.patch('tracker.email_service.send_connect_link', return_value=True) as send:
            r = self.api.post(f'/api/onboard/projects/{self.p.id}/connect-link/',
                              {'providers': ['quickbooks'], 'email': 'books@agency.test'}, format='json')
        self.assertTrue(r.json()['emailed'])
        self.assertEqual(send.call_args.kwargs['to_email'], 'books@agency.test')
        self.assertIn('/connect/', send.call_args.kwargs['connect_url'])

    # ── public side ──
    def test_status_needs_a_valid_token(self):
        self.assertEqual(self.public.get('/api/onboard/connect/nope/').status_code, 404)
        raw = self.issue()
        body = self.public.get(f'/api/onboard/connect/{raw}/').json()
        self.assertEqual(body['firm'], self.org.name)
        self.assertEqual([p['key'] for p in body['providers']], ['quickbooks'])
        self.assertFalse(body['providers'][0]['connected'])

    def test_start_mints_state_on_link_and_integration(self):
        raw = self.issue()
        r = self.start(raw)
        self.assertEqual(r.status_code, 200, r.content)
        state = parse_qs(urlparse(r.json()['auth_url']).query)['state'][0]
        self.assertEqual(ConnectLink.objects.get().qbo_state, state)
        self.assertEqual(Integration.objects.get(organization=self.org, provider='quickbooks').oauth_state, state)

    def test_start_refuses_a_provider_not_on_the_link(self):
        raw = self.issue(providers=('quickbooks',))
        self.assertEqual(self.start(raw, 'qb_time').status_code, 400)

    def test_expired_link_cannot_start(self):
        raw = self.issue()
        ConnectLink.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.start(raw).status_code, 400)

    # ── callbacks ──
    def qbo_callback(self, state, **extra):
        with mock.patch('tracker.views_integrations.requests.post',
                        return_value=_ok_token({'access_token': 'a', 'refresh_token': 'r', 'expires_in': 3600})), \
             mock.patch('tracker.tasks.backfill_qb_invoices'), \
             mock.patch('tracker.views_integrations.import_qb_customers',
                        return_value=({'summary': {'imported_count': 3}}, None)) as imp:
            r = self.public.get('/api/integrations/quickbooks/callback/',
                                {'code': 'c', 'state': state, 'realmId': '999', **extra})
        return r, imp

    def test_link_started_qbo_grant_returns_to_the_link_and_imports(self):
        raw = self.issue()
        state = parse_qs(urlparse(self.start(raw).json()['auth_url']).query)['state'][0]
        r, imp = self.qbo_callback(state)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], 'https://app.test/connect/return?provider=quickbooks&status=connected')
        link = ConnectLink.objects.get()
        self.assertIsNotNone(link.qbo_connected_at)
        self.assertEqual(link.qbo_state, '')
        self.assertTrue(Integration.objects.get(organization=self.org, provider='quickbooks').is_connected)
        imp.assert_called_once()  # every active customer: no customer_ids passed
        self.assertEqual(len(imp.call_args.args), 2)

    def test_link_started_qbo_cancel_returns_to_the_link(self):
        raw = self.issue()
        state = parse_qs(urlparse(self.start(raw).json()['auth_url']).query)['state'][0]
        r = self.public.get('/api/integrations/quickbooks/callback/',
                            {'error': 'access_denied', 'state': state})
        self.assertEqual(r['Location'],
                         'https://app.test/connect/return?provider=quickbooks&status=error&reason=access_denied')

    def test_settings_started_grant_is_unchanged(self):
        Integration.objects.create(organization=self.org, provider='quickbooks', oauth_state='settings-state')
        r, imp = self.qbo_callback('settings-state')
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'oauth_callback', r.content)
        imp.assert_not_called()

    @override_settings(QBTIME_CLIENT_ID='qbt-id', QBTIME_CLIENT_SECRET='qbt-secret',
                       QBTIME_REDIRECT_URI='https://api.test/api/integrations/qb-time/callback/')
    def test_link_started_qb_time_grant_returns_to_the_link(self):
        raw = self.issue(providers=('qb_time',))
        r = self.start(raw, 'qb_time')
        self.assertEqual(r.status_code, 200, r.content)
        state = ConnectLink.objects.get().qbt_state
        with mock.patch('tracker.integrations.qb_time.views.requests.post',
                        return_value=_ok_token({'access_token': 'a', 'refresh_token': 'r',
                                                'expires_in': 3600, 'company_id': 77})), \
             mock.patch('tracker.integrations.qb_time.sync.sync_qb_time_full'):
            r = self.public.get(reverse('qb-time-callback'), {'code': 'c', 'state': state})
        self.assertEqual(r['Location'], 'https://app.test/connect/return?provider=qb_time&status=connected')
        self.assertIsNotNone(ConnectLink.objects.get().qbt_connected_at)

    # ── status details ──
    def test_qb_time_status_lists_members_without_a_matching_email(self):
        jane = User.objects.create_user('jane@agency.test', 'jane@agency.test', first_name='Jane')
        mark = User.objects.create_user('mark@agency.test', 'mark@agency.test', first_name='Mark')
        for u in (jane, mark):
            OrganizationMembership.objects.get_or_create(user=u, organization=self.org,
                                                         defaults={'role': 'member'})
        integ = Integration.objects.create(organization=self.org, provider='qb_time', is_connected=True)
        ExternalStaffMapping.objects.create(integration=integ, user=jane, external_id='1')
        link, _ = ConnectLink.mint(self.org, ['qb_time'], project=self.p)
        row = connect_link.status(link)['providers'][0]
        emails = [u['email'] for u in row['unmatched']]
        self.assertIn('mark@agency.test', emails)
        self.assertNotIn('jane@agency.test', emails)

    def test_state_lookup_never_raises(self):
        self.assertIsNone(connect_link.link_for_state('quickbooks', ''))
        self.assertIsNone(connect_link.link_for_state('xero', 'abc'))


@override_settings(**QB)
class ImportAllCustomersTests(ConsoleBase):
    def test_none_imports_every_active_customer(self):
        p = self.make_project()
        integ = Integration.objects.create(organization=p.organization, provider='quickbooks',
                                           is_connected=True, realm_id='R1')
        data = {'QueryResponse': {'Customer': [
            {'Id': '1', 'DisplayName': 'Acme Dealers'}, {'Id': '2', 'DisplayName': 'Bolt Motors'}]}}
        from tracker import views_integrations
        with mock.patch.object(views_integrations, 'qb_api_call', return_value=(data, None)) as call, \
             mock.patch.object(views_integrations, 'run_post_import_alias_derivation'):
            result, err = views_integrations.import_qb_customers(p.organization, integ)
        self.assertIsNone(err)
        self.assertIn('Active = true', call.call_args.kwargs['params']['query'])
        self.assertEqual(result['summary']['imported_count'], 2)
        self.assertEqual(Client.objects.filter(org=p.organization, imported_from='quickbooks').count(), 2)


class ConnectLinkEmailTypeTests(ConsoleBase):
    def test_outbox_files_it_as_its_own_type_not_an_invitation(self):
        # categories=["onboarding", "connect_link"]: "onboarding" alone would
        # file it under "Invitation to join" and release it with invitations.
        from tracker.services.email_outbox import email_type_for
        self.assertEqual(email_type_for(['onboarding', 'connect_link']), 'connect_link')


class ConnectLinkEmailCopyTests(ConsoleBase):
    def _render(self, providers):
        from tracker import email_service
        cap = {}
        with mock.patch.object(email_service, 'send_email', side_effect=lambda **k: cap.update(k) or True):
            email_service.send_connect_link(to_email='kyle@agency.test', firm_name='Acme',
                                            connect_url='https://app.test/connect/X',
                                            providers=providers, contact_name='Kyle')
        return cap

    def test_one_service_reads_as_one_click(self):
        cap = self._render(['QuickBooks Online'])
        self.assertIn('about two minutes', cap['plain_content'])
        self.assertIn('Copy and paste this link', cap['html_content'])

    def test_two_services_say_connect_each(self):
        cap = self._render(['QuickBooks Online', 'QuickBooks Time'])
        self.assertIn('click Connect next to each one', cap['html_content'])
        self.assertIn('Connect QuickBooks Online and QuickBooks Time', cap['html_content'])
