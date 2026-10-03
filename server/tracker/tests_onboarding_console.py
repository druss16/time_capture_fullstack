"""
Onboarding Console — firewall, playbook, imports, mappings, intake, deploy kit.

    python manage.py test tracker.tests_onboarding_console --noinput
"""
import os
import plistlib
import secrets
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from tracker.models import (
    AuthToken, DeviceProvisioningMap, Invitation, Organization,
    OrganizationMembership, OrgDeploymentToken, TaskType,
)
from tracker.models_onboarding_console import (
    OPERATOR_GROUP, OnboardingAuditEvent, OnboardingIntake, OnboardingProject,
)
from tracker.onboarding_playbook import evaluate, steps_for
from tracker.services import onboarding_console as svc

User = get_user_model()

TEAM_CSV = (
    'email,display_name,role,billing_rate,cost_rate,machine_hostname,windows_username\n'
    'jane@agency.test,Jane Smith,manager,175,70,JANES-MBP,\n'
    'mark@agency.test,Mark Jones,member,125,55,MARKS-IMAC,\n'
)


def _client_for(user):
    tok = AuthToken.objects.create(user=user, token=secrets.token_hex(20),
                                   expires_at=timezone.now() + timedelta(days=1))
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {tok.token}')
    return c


class ConsoleBase(TestCase):
    def setUp(self):
        self.operator = User.objects.create_user('op', 'op@mavops.test', 'x')
        self.operator.groups.add(Group.objects.get_or_create(name=OPERATOR_GROUP)[0])
        self.api = _client_for(self.operator)

    def make_project(self, vertical='marketing', path='mac_hand', name='Acme Agency'):
        return svc.create_project(actor=self.operator, vertical=vertical,
                                  install_path=path, name=name, seat_count=5)


class FirewallTests(ConsoleBase):
    def test_staff_alone_is_not_enough(self):
        staff = User.objects.create_user('staff', 'staff@mavops.test', 'x', is_staff=True)
        r = _client_for(staff).get('/api/onboard/projects/')
        self.assertEqual(r.status_code, 403)

    def test_anonymous_is_refused(self):
        self.assertIn(APIClient().get('/api/onboard/projects/').status_code, (401, 403))

    def test_operator_and_superuser_get_in(self):
        self.assertEqual(self.api.get('/api/onboard/projects/').status_code, 200)
        su = User.objects.create_superuser('su', 'su@mavops.test', 'x')
        self.assertEqual(_client_for(su).get('/api/onboard/projects/').status_code, 200)

    def test_me_tells_operator_apart(self):
        r = self.api.get('/api/onboard/me/')
        self.assertTrue(r.json()['is_operator'])
        plain = User.objects.create_user('p', 'p@firm.test', 'x')
        self.assertFalse(_client_for(plain).get('/api/onboard/me/').json()['is_operator'])

    def test_operator_cannot_reach_mavops_admin(self):
        self.assertEqual(self.api.get('/api/mavops/orgs/').status_code, 403)


class ProjectTests(ConsoleBase):
    def test_create_sets_vertical_before_anything_else(self):
        r = self.api.post('/api/onboard/projects/', {
            'name': 'More Than Cars', 'vertical': 'marketing',
            'install_path': 'mac_hand', 'seat_count': 8}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        org = Organization.objects.get(name='More Than Cars')
        self.assertEqual(org.industry_type, 'marketing')
        self.assertEqual(org.plan, 'none')
        self.assertTrue(OnboardingAuditEvent.objects.filter(action='project.create').exists())

    def test_create_with_go_live_date_lands_on_the_firm(self):
        body = {'name': 'More Than Cars', 'vertical': 'marketing', 'install_path': 'mac_hand',
                'seat_count': 1, 'target_go_live': '2026-10-06'}
        r = self.api.post('/api/onboard/projects/', body, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['target_go_live'], '2026-10-06')
        p = OnboardingProject.objects.get(id=r.json()['id'])
        r = self.api.patch(f'/api/onboard/projects/{p.id}/', {'target_go_live': '2026-11-01'},
                           format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['target_go_live'], '2026-11-01')
        r = self.api.patch(f'/api/onboard/projects/{p.id}/', {'target_go_live': 'soon'},
                           format='json')
        self.assertEqual(r.status_code, 400)

    def test_soft_deleted_firm_does_not_block_its_slug(self):
        old = Organization.objects.create(name='More Than Cars', slug='more-than-cars')
        old.soft_delete()
        r = self.api.post('/api/onboard/projects/', {
            'name': 'More Than Cars', 'vertical': 'marketing', 'install_path': 'mac_hand'},
            format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['org']['slug'], 'more-than-cars-2')

    def test_create_delete_create(self):
        body = {'name': 'More Than Cars', 'vertical': 'marketing', 'install_path': 'mac_hand',
                'target_go_live': '2026-10-06'}
        a = self.api.post('/api/onboard/projects/', body, format='json')
        self.assertEqual(a.status_code, 201, a.content)
        OnboardingProject.objects.update(created_at=timezone.now() - timedelta(minutes=10))
        d = self.api.post(f"/api/onboard/projects/{a.json()['id']}/delete/",
                          {'confirm_name': 'More Than Cars', 'delete_firm': True}, format='json')
        self.assertEqual(d.status_code, 200, d.content)
        b = self.api.post('/api/onboard/projects/', body, format='json')
        self.assertEqual(b.status_code, 201, b.content)

    def test_double_submit_returns_the_same_firm(self):
        body = {'name': 'More Than Cars', 'vertical': 'marketing',
                'install_path': 'mac_hand', 'seat_count': 8}
        a = self.api.post('/api/onboard/projects/', body, format='json')
        b = self.api.post('/api/onboard/projects/', body, format='json')
        self.assertEqual(a.status_code, 201, a.content)
        self.assertEqual(b.status_code, 201, b.content)
        self.assertEqual(a.json()['id'], b.json()['id'])
        self.assertEqual(Organization.objects.filter(name='More Than Cars').count(), 1)
        self.assertEqual(OnboardingAuditEvent.objects.filter(action='project.create').count(), 1)

    def test_old_or_other_operator_duplicate_still_refused(self):
        body = {'name': 'More Than Cars', 'vertical': 'marketing', 'install_path': 'mac_hand'}
        self.api.post('/api/onboard/projects/', body, format='json')
        OnboardingProject.objects.update(created_at=timezone.now() - timedelta(minutes=10))
        r = self.api.post('/api/onboard/projects/', body, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('already exists', r.json()['error'])

    def test_duplicate_firm_refused(self):
        Organization.objects.create(name='Smith & Co., LLC', slug='smith-co')
        r = self.api.post('/api/onboard/projects/', {
            'name': 'smith and co', 'vertical': 'cpa', 'install_path': 'windows_gpo'},
            format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('already exists', r.json()['error'])
        self.assertEqual(Organization.objects.filter(slug__startswith='smith').count(), 1)

    def test_unknown_vertical_refused(self):
        r = self.api.post('/api/onboard/projects/', {
            'name': 'X', 'vertical': 'plumbing', 'install_path': 'mac_hand'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_adopt_existing_org_corrects_vertical(self):
        org = Organization.objects.create(name='Old Firm', slug='old-firm')
        p = svc.create_project(actor=self.operator, vertical='legal',
                               install_path='windows_gpo', org_id=org.id)
        org.refresh_from_db()
        self.assertEqual(org.industry_type, 'legal')
        ev = OnboardingAuditEvent.objects.get(project=p, action='project.create')
        self.assertEqual(ev.detail['changed_vertical'], ['general', 'legal'])
        # An immediate repeat is a replay of the same request…
        again = svc.create_project(actor=self.operator, vertical='legal',
                                   install_path='windows_gpo', org_id=org.id)
        self.assertEqual(again.id, p.id)
        # …but adopting it again later is refused.
        OnboardingProject.objects.filter(id=p.id).update(
            created_at=timezone.now() - timedelta(minutes=10))
        with self.assertRaises(svc.ConsoleError):
            svc.create_project(actor=self.operator, vertical='legal',
                               install_path='windows_gpo', org_id=org.id)


class PlaybookTests(ConsoleBase):
    def test_steps_filter_by_vertical_and_path(self):
        mac_agency = {s.key for s in steps_for(self.make_project())}
        self.assertIn('macs_checked', mac_agency)
        self.assertIn('qbo_connected', mac_agency)
        self.assertNotIn('it_gpo', mac_agency)
        self.assertNotIn('clio_connected', mac_agency)

        cpa = {s.key for s in steps_for(self.make_project('cpa', 'windows_gpo', 'CPA Co'))}
        self.assertIn('it_gpo', cpa)
        self.assertIn('token', cpa)
        self.assertNotIn('qbo_connected', cpa)
        self.assertNotIn('macs_checked', cpa)

    def test_auto_step_cannot_be_ticked_by_hand(self):
        p = self.make_project()
        r = self.api.post(f'/api/onboard/projects/{p.id}/steps/team/', {'done': True},
                          format='json')
        self.assertEqual(r.status_code, 400)
        r = self.api.post(f'/api/onboard/projects/{p.id}/steps/team/',
                          {'not_applicable': True, 'note': 'n/a'}, format='json')
        self.assertEqual(r.status_code, 200)

    def test_manual_step_tick_is_audited(self):
        p = self.make_project()
        r = self.api.post(f'/api/onboard/projects/{p.id}/steps/signed/', {'done': True},
                          format='json')
        self.assertEqual(r.status_code, 200)
        steps = {s['key']: s for ph in evaluate(p)['phases'] for s in ph['steps']}
        self.assertTrue(steps['signed']['done'])
        self.assertTrue(steps['vertical']['done'])
        self.assertIn('36 categories', steps['vertical']['detail'])
        self.assertTrue(OnboardingAuditEvent.objects.filter(action='step.mark').exists())

    def test_detail_endpoint_renders(self):
        p = self.make_project()
        r = self.api.get(f'/api/onboard/projects/{p.id}/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['vertical'], 'marketing')


class ImportTests(ConsoleBase):
    def test_dry_run_writes_nothing_then_commit_does(self):
        p = self.make_project()
        url = f'/api/onboard/projects/{p.id}/import/'
        r = self.api.post(url, {'kind': 'team', 'csv': TEAM_CSV, 'dry_run': True},
                          format='json')
        self.assertTrue(r.json()['ok'], r.json())
        self.assertIn('DRY RUN', r.json()['output'])
        self.assertFalse(User.objects.filter(email='jane@agency.test').exists())

        r = self.api.post(url, {'kind': 'team', 'csv': TEAM_CSV, 'dry_run': False},
                          format='json')
        self.assertTrue(r.json()['ok'], r.json())
        self.assertEqual(OrganizationMembership.objects.filter(
            organization=p.organization).count(), 2)
        self.assertEqual(DeviceProvisioningMap.objects.filter(
            organization=p.organization).count(), 2)
        self.assertTrue(OnboardingAuditEvent.objects.filter(action='import.team').exists())

    def test_bad_header_is_reported_not_raised(self):
        p = self.make_project()
        r = self.api.post(f'/api/onboard/projects/{p.id}/import/',
                          {'kind': 'team', 'csv': 'foo,bar\n1,2\n', 'dry_run': True},
                          format='json')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['ok'])
        self.assertIn('missing required columns', r.json()['errors'])


class MappingTests(ConsoleBase):
    def _types(self, org):
        a = TaskType.objects.create(org=org, name='Graphic Design', code='DESIGN',
                                    is_billable=True)
        b = TaskType.objects.create(org=org, name='Internal / Admin', code='ADMIN',
                                    is_billable=False)
        return a, b

    def test_partial_grid_refused_full_grid_resolves(self):
        p = self.make_project()
        a, b = self._types(p.organization)
        grid = svc.mapping_grid(p.organization)
        self.assertEqual(len(grid['rows']), 36)
        partial = {grid['rows'][0]['category']: a.id}
        r = self.api.put(f'/api/onboard/projects/{p.id}/mappings/',
                         {'selections': partial}, format='json')
        self.assertEqual(r.status_code, 400)

        full = {row['category']: (b.id if row['category'] in ('Idle', 'Personal/Non-Billable')
                                  else a.id) for row in grid['rows']}
        r = self.api.put(f'/api/onboard/projects/{p.id}/mappings/',
                         {'selections': full}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        steps = {s['key']: s for ph in evaluate(p)['phases'] for s in ph['steps']}
        self.assertTrue(steps['mappings']['done'])
        self.assertEqual(steps['mappings']['detail'], '36/36 resolve')

    def test_ai_unavailable_falls_back_to_name_match(self):
        p = self.make_project()
        self._types(p.organization)
        with self.settings(OPENAI_API_KEY=''):
            out = svc.suggest_mappings(p.organization)
        self.assertEqual(out['source'], 'name_match')
        by_cat = {r['category']: r for r in out['rows']}
        self.assertEqual(by_cat['Graphic Design']['task_type_code'], 'DESIGN')
        self.assertEqual(by_cat['Idle']['task_type_code'], 'ADMIN')


class IntakeTests(ConsoleBase):
    def test_link_save_submit_and_lock(self):
        p = self.make_project()
        r = self.api.post(f'/api/onboard/projects/{p.id}/intake/')
        raw = r.json()['url'].rsplit('/', 1)[1]
        self.assertFalse(OnboardingIntake.objects.filter(token_hash=raw).exists())

        anon = APIClient()
        self.assertEqual(anon.get('/api/onboard/intake/not-a-token/').status_code, 404)
        self.assertEqual(anon.get(f'/api/onboard/intake/{raw}/').json()['firm'], 'Acme Agency')

        answers = {
            'team': [{'email': 'Jane@Agency.test', 'display_name': 'Jane',
                      'role': 'Owner', 'machine_hostname': 'Janes-MacBook-Pro.local'}],
            'contacts': {'billing': {'name': 'Bo', 'email': 'bo@agency.test'}},
            'answers': {'billing_model': 'retainer'},
        }
        r = anon.post(f'/api/onboard/intake/{raw}/', {'answers': answers}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        r = anon.post(f'/api/onboard/intake/{raw}/', {'answers': answers, 'submit': True},
                      format='json')
        self.assertEqual(r.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.contacts['billing']['email'], 'bo@agency.test')
        self.assertEqual(p.billing_model, 'retainer')

        r = anon.post(f'/api/onboard/intake/{raw}/', {'answers': answers}, format='json')
        self.assertEqual(r.status_code, 409)

        csv_text = self.api.get(f'/api/onboard/projects/{p.id}/intake-csv/team/').json()['csv']
        self.assertIn('jane@agency.test,Jane,owner', csv_text)
        self.assertIn('JANES-MACBOOK-PRO', csv_text)
        self.assertNotIn('.LOCAL', csv_text)

    def test_reissue_revokes_old_link_and_keeps_answers(self):
        p = self.make_project()
        old, raw_old = OnboardingIntake.mint(p)
        old.payload = {'team': [{'email': 'a@b.test'}]}
        old.save()
        new, _ = OnboardingIntake.mint(p)
        self.assertEqual(new.payload, old.payload)
        self.assertEqual(APIClient().get(f'/api/onboard/intake/{raw_old}/').status_code, 404)

    def test_payload_is_bounded(self):
        with self.assertRaises(svc.ConsoleError):
            svc.clean_intake_payload({'team': [{'email': 'x'}] * 2000})


class InstallTests(ConsoleBase):
    def test_pairing_readiness_without_pairing(self):
        p = self.make_project('cpa', 'windows_gpo', 'CPA Co')
        org = p.organization
        DeviceProvisioningMap.objects.create(organization=org, machine_hostname='PC-1',
                                             email='a@cpa.test', status='pending')
        self.assertFalse(svc.pairing_readiness(org)['ok'])          # no token yet
        svc.ensure_token(org, self.operator)
        self.assertTrue(svc.pairing_readiness(org)['ok'])
        DeviceProvisioningMap.objects.create(organization=org, machine_hostname='MAC.LOCAL',
                                             email='b@cpa.test', status='pending')
        r = svc.pairing_readiness(org)
        self.assertFalse(r['ok'])
        self.assertEqual(DeviceProvisioningMap.objects.filter(status='paired').count(), 0)

    def test_windows_kit_carries_token(self):
        p = self.make_project('cpa', 'windows_gpo', 'CPA Co')
        r = self.api.post(f'/api/onboard/projects/{p.id}/deploy-kit/')
        kit = r.json()
        script = next(f for f in kit['files'] if f['name'].endswith('.ps1'))
        self.assertIn(kit['token'], script['content'])
        self.assertNotIn('REPLACE_WITH_ORG_TOKEN', script['content'])
        steps = {s['key']: s for ph in evaluate(p)['phases'] for s in ph['steps']}
        self.assertTrue(steps['deploy_kit']['done'])

    def test_mac_kit_plist_is_what_the_agent_reads(self):
        p = self.make_project('marketing', 'mac_mdm')
        kit = svc.deploy_kit(p, self.operator)
        plist = next(f for f in kit['files'] if f['name'] == 'config.plist')
        data = plistlib.loads(plist['content'].encode())
        self.assertEqual(data['OrgToken'], kit['token'])
        self.assertTrue(data['ApiEndpoint'].endswith('/api'))

    def test_server_template_matches_deployment_template(self):
        repo = os.path.dirname(settings.BASE_DIR)
        canonical = os.path.join(repo, 'deployment', 'install_timetracker_template.ps1')
        if not os.path.exists(canonical):
            self.skipTest('deployment/ not present (container build)')
        served = os.path.join(settings.BASE_DIR, 'onboarding_templates',
                              'install_timetracker_FIRMSLUG.ps1')
        with open(canonical, encoding='utf-8') as a, open(served, encoding='utf-8') as b:
            self.assertEqual(a.read(), b.read(),
                             'Copy deployment/install_timetracker_template.ps1 over '
                             'server/onboarding_templates/install_timetracker_FIRMSLUG.ps1')


class InviteAndStripeTests(ConsoleBase):
    def test_invites_reach_never_signed_in_members(self):
        p = self.make_project()
        svc.run_provision(p.organization, kind='team', csv_text=TEAM_CSV, dry_run=False)
        with mock.patch('tracker.email_service.send_onboarding_invitation', return_value=False):
            r = self.api.post(f'/api/onboard/projects/{p.id}/invites/')
        self.assertEqual(len(r.json()['issued']), 2)
        self.assertEqual(Invitation.objects.filter(organization=p.organization).count(), 2)
        steps = {s['key']: s for ph in evaluate(p)['phases'] for s in ph['steps']}
        self.assertTrue(steps['invites']['done'])

    def test_stripe_links_the_org(self):
        p = self.make_project()
        fake = mock.MagicMock()
        fake.Coupon.create.return_value = {'id': 'co_1'}
        fake.Customer.create.return_value = {'id': 'cus_1'}
        fake.Subscription.create.return_value = {'id': 'sub_1'}
        fake.error.StripeError = Exception
        with mock.patch.dict('sys.modules', {'stripe': fake}), \
             self.settings(STRIPE_SECRET_KEY='sk_test', STRIPE_PRICE_PROFESSIONAL_MONTHLY='price_1'):
            out = svc.setup_stripe(p.organization, plan='professional', interval='monthly',
                                   seats=5, coupon_months=3, billing_email='bo@agency.test')
            self.assertEqual(out['subscription'], 'sub_1')
            kwargs = fake.Subscription.create.call_args.kwargs
            self.assertEqual(kwargs['discounts'], [{'coupon': 'co_1'}])
            self.assertEqual(kwargs['collection_method'], 'send_invoice')
            p.organization.refresh_from_db()
            self.assertEqual(p.organization.plan, 'professional')
            with self.assertRaises(svc.ConsoleError):
                svc.setup_stripe(p.organization, plan='professional', interval='monthly',
                                 seats=5, coupon_months=0, billing_email='bo@agency.test')


class VerifyTests(ConsoleBase):
    def test_run_checks_returns_data_and_command_still_prints(self):
        from io import StringIO
        from django.core.management import call_command
        from tracker.management.commands.verify_firm import run_checks
        p = self.make_project()
        out = run_checks(p.organization)
        labels = {l['label'] for l in out['lines']}
        self.assertIn('industry_type', labels)
        self.assertTrue(any(i['label'] == 'deployment token' for i in out['issues']))
        buf = StringIO()
        with self.assertRaises(SystemExit):             # blockers → exit 1, as before
            call_command('verify_firm', org=p.organization.slug, stdout=buf)
        self.assertIn('marketing (36 categories)', buf.getvalue())


class RoleGroupOrgTests(TestCase):
    def test_granting_operator_role_creates_no_organization(self):
        from django.core.management import call_command
        u = User.objects.create_user('dan', 'dan@mavops.test', 'x')
        before = Organization.objects.count()
        call_command('grant_onboarding_operator', 'dan@mavops.test', stdout=open(os.devnull, 'w'))
        self.assertEqual(Organization.objects.count(), before)
        self.assertFalse(OrganizationMembership.objects.filter(user=u).exists())

    def test_other_groups_still_map_to_orgs(self):
        u = User.objects.create_user('amy', 'amy@firm.test', 'x')
        u.groups.add(Group.objects.create(name='Acme Firm'))
        self.assertTrue(OrganizationMembership.objects.filter(
            user=u, organization__name='Acme Firm').exists())

    def test_cleanup_removes_empty_role_org_only(self):
        from io import StringIO
        from django.core.management import call_command
        u = User.objects.create_user('dan', 'dan@mavops.test', 'x')
        phantom = Organization.objects.create(name=OPERATOR_GROUP, slug='onboarding-operator')
        OrganizationMembership.objects.create(user=u, organization=phantom, role='member')
        call_command('remove_role_group_orgs', stdout=StringIO())          # dry run
        self.assertTrue(Organization.objects.filter(id=phantom.id).exists())
        call_command('remove_role_group_orgs', apply=True, stdout=StringIO())
        self.assertFalse(Organization.objects.filter(id=phantom.id).exists())
        self.assertTrue(User.objects.filter(id=u.id).exists())

    def test_cleanup_refuses_org_with_real_clients(self):
        from io import StringIO
        from django.core.management import call_command
        from tracker.models import Client
        phantom = Organization.objects.create(name=OPERATOR_GROUP, slug='onboarding-operator')
        Client.objects.create(org=phantom, name='Real Client', code='REAL')
        out = StringIO()
        call_command('remove_role_group_orgs', apply=True, stdout=out)
        self.assertTrue(Organization.objects.filter(id=phantom.id).exists())
        self.assertIn('NOT deleting', out.getvalue())

    def test_whoami_flags_operator(self):
        u = User.objects.create_user('dan', 'dan@mavops.test', 'x')
        u.groups.add(Group.objects.get_or_create(name=OPERATOR_GROUP)[0])
        self.assertTrue(_client_for(u).get('/api/whoami/').json().get('is_onboarding_operator'))
        other = User.objects.create_user('x', 'x@firm.test', 'x')
        self.assertFalse(_client_for(other).get('/api/whoami/').json().get('is_onboarding_operator'))


class DeleteOnboardingTests(ConsoleBase):
    def test_delete_console_created_firm_with_unused_staff(self):
        p = self.make_project()
        org_id = p.organization_id
        svc.run_provision(p.organization, kind='team', csv_text=TEAM_CSV, dry_run=False)
        url = f'/api/onboard/projects/{p.id}/delete/'
        check = self.api.get(url).json()
        self.assertTrue(check['firm_created_here'])
        self.assertEqual(check['blockers'], [])
        bad = self.api.post(url, {'confirm_name': 'wrong', 'delete_firm': True}, format='json')
        self.assertEqual(bad.status_code, 400)
        r = self.api.post(url, {'confirm_name': 'Acme Agency', 'delete_firm': True}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(Organization.objects.filter(id=org_id).exists())
        self.assertFalse(User.objects.filter(email='jane@agency.test').exists())
        self.assertTrue(OnboardingAuditEvent.objects.filter(
            action='project.delete', project__isnull=True).exists())

    def test_adopted_firm_is_never_deleted(self):
        org = Organization.objects.create(name='Old Firm', slug='old-firm')
        p = svc.create_project(actor=self.operator, vertical='cpa',
                               install_path='windows_gpo', org_id=org.id)
        url = f'/api/onboard/projects/{p.id}/delete/'
        self.assertFalse(self.api.get(url).json()['firm_created_here'])
        r = self.api.post(url, {'confirm_name': 'Old Firm', 'delete_firm': True}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.api.post(url, {'confirm_name': 'Old Firm', 'delete_firm': False}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Organization.objects.filter(id=org.id).exists())
        self.assertFalse(OnboardingProject.objects.filter(id=p.id).exists())

    def test_blocked_when_someone_signed_in_and_other_firm_member_kept(self):
        p = self.make_project()
        svc.run_provision(p.organization, kind='team', csv_text=TEAM_CSV, dry_run=False)
        jane = User.objects.get(email='jane@agency.test')
        jane.last_login = timezone.now(); jane.save()
        url = f'/api/onboard/projects/{p.id}/delete/'
        self.assertIn('1 member(s) have signed in', self.api.get(url).json()['blockers'])
        r = self.api.post(url, {'confirm_name': 'Acme Agency', 'delete_firm': True}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertTrue(Organization.objects.filter(id=p.organization_id).exists())
