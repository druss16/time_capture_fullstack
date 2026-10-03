"""
tracker/views_onboarding_console.py

API for the Onboarding Console — /api/onboard/.

THE FIREWALL. Every operator endpoint requires membership of the
"Onboarding Operator" group (or superuser). is_staff alone is NOT enough, and
being an operator grants nothing in Mavops admin: the two consoles are
separate on purpose, so a future hire can onboard firms without being handed
View-as, cross-org Daily Review, or device kill switches. Auth is the web
login's bearer token only — never an agent key — and the prefix is exempt
from View-as swapping, so an operator is always acting as themselves.

Every write is recorded in OnboardingAuditEvent.

The one unauthenticated surface is the firm's intake form, reached by a
single-use hashed token, throttled, size-bounded, and able to touch nothing
but its own answers.
"""
import logging

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tracker.auth import BearerTokenAuthentication
from tracker.models_onboarding_console import (
    INSTALL_PATH_CHOICES, OPERATOR_GROUP, OnboardingAuditEvent, OnboardingIntake,
    OnboardingProject, OnboardingStepState,
)
from tracker.onboarding_playbook import AUTO_PAIR, STEPS_BY_KEY, evaluate
from tracker.services import onboarding_console as svc
from tracker.services.onboarding_console import ConsoleError

logger = logging.getLogger(__name__)


def is_operator(user):
    if not (user and user.is_authenticated and user.is_active):
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name=OPERATOR_GROUP).exists()


class IsOnboardingOperator(BasePermission):
    message = 'Onboarding Console access requires the Onboarding Operator role.'

    def has_permission(self, request, view):
        return is_operator(request.user)


def operator_view(methods):
    """@api_view + the console's auth, stacked in the one order that works."""
    def wrap(fn):
        fn = permission_classes([IsAuthenticated, IsOnboardingOperator])(fn)
        fn = authentication_classes([BearerTokenAuthentication])(fn)
        return api_view(methods)(fn)
    return wrap


def _err(e, status=400):
    return Response({'error': str(e)}, status=status)


def _project(pk):
    return get_object_or_404(
        OnboardingProject.objects.select_related('organization', 'owner'), pk=pk)


def _person(u):
    if not u:
        return None
    return {'id': u.id, 'name': u.get_full_name() or u.email, 'email': u.email}


def _project_summary(p, checklist):
    org = p.organization
    from tracker.industry_categories import INDUSTRY_TYPES
    last_event = p.audit_events.order_by('-created_at').first()
    return {
        'id': p.id,
        'status': p.status,
        'install_path': p.install_path,
        'install_path_label': dict(INSTALL_PATH_CHOICES).get(p.install_path),
        'vertical': org.industry_type,
        'vertical_label': dict(INDUSTRY_TYPES).get(org.industry_type, org.industry_type),
        'org': {'id': org.id, 'name': org.name, 'slug': org.slug, 'plan': org.plan,
                'seat_count': org.seat_count},
        'owner': _person(p.owner),
        'target_go_live': p.target_go_live.isoformat() if p.target_go_live else None,
        'created_at': p.created_at.isoformat(),
        'went_live_at': p.went_live_at.isoformat() if p.went_live_at else None,
        'last_activity_at': (last_event.created_at if last_event else p.updated_at).isoformat(),
        'progress': checklist['progress'],
        'current_phase': checklist['current_phase'],
        'phases': [{'key': ph['key'], 'title': ph['title'], 'done': ph['done'],
                    'open': ph['open']} for ph in checklist['phases']],
    }


# ── Who am I ─────────────────────────────────────────────────────────────

@api_view(['GET'])
@authentication_classes([BearerTokenAuthentication])
@permission_classes([AllowAny])
def console_me(request):
    """Lets the console page tell 'not signed in' from 'not an operator'."""
    u = request.user
    return Response({
        'authenticated': bool(u and u.is_authenticated),
        'is_operator': is_operator(u),
        'user': _person(u) if u and u.is_authenticated else None,
    })


# ── Board ────────────────────────────────────────────────────────────────

@operator_view(['GET', 'POST'])
def projects(request):
    if request.method == 'POST':
        d = request.data
        try:
            p = svc.create_project(
                actor=request.user, vertical=d.get('vertical'),
                install_path=d.get('install_path'), name=d.get('name'),
                seat_count=d.get('seat_count') or 1, org_id=d.get('org_id'),
                slug=d.get('slug'), target_go_live=d.get('target_go_live') or None,
            )
        except ConsoleError as e:
            return _err(e)
        return Response(_project_summary(p, evaluate(p, include_checks=False)), status=201)

    show = request.GET.get('status', 'open')
    qs = OnboardingProject.objects.select_related('organization', 'owner')
    if show == 'open':
        qs = qs.filter(status__in=('active', 'paused'))
    elif show != 'all':
        qs = qs.filter(status=show)
    out = []
    for p in qs:
        try:
            out.append(_project_summary(p, evaluate(p)))
        except Exception as e:                       # noqa: BLE001
            logger.exception('[ONBOARD] board evaluate failed for project %s', p.id)
            out.append({'id': p.id, 'org': {'name': p.organization.name},
                        'error': str(e)})
    return Response({'projects': out})


@operator_view(['GET'])
def adoptable_orgs(request):
    """Firms that exist but have no onboarding yet — e.g. ones started by hand."""
    from tracker.models import Organization
    qs = (Organization.objects.filter(onboarding_project__isnull=True)
          .order_by('-id').values('id', 'name', 'slug', 'industry_type', 'plan')[:200])
    return Response({'orgs': list(qs)})


# ── One firm ─────────────────────────────────────────────────────────────

_EDITABLE = {'install_path', 'status', 'contacts', 'billing_model', 'coupon_months',
             'target_go_live', 'notes'}


@operator_view(['GET', 'PATCH'])
def project_detail(request, pk):
    p = _project(pk)
    if request.method == 'PATCH':
        changed = {}
        for field, val in request.data.items():
            if field == 'seat_count':
                try:
                    n = max(1, int(val))
                except (TypeError, ValueError):
                    return _err('seat_count must be a number')
                p.organization.seat_count = n
                p.organization.save(update_fields=['seat_count'])
                changed[field] = n
                continue
            if field == 'owner_id':
                from django.contrib.auth import get_user_model
                u = get_user_model().objects.filter(id=val).first() if val else None
                if val and not is_operator(u):
                    return _err('Owner must be an onboarding operator.')
                p.owner = u
                changed[field] = val
                continue
            if field not in _EDITABLE:
                return _err(f'"{field}" cannot be edited here.')
            if field == 'install_path' and val not in dict(INSTALL_PATH_CHOICES):
                return _err('Unknown install path.')
            if field == 'status' and val not in dict(OnboardingProject.STATUS_CHOICES):
                return _err('Unknown status.')
            if field == 'target_go_live':
                try:
                    val = svc.parse_go_live(val)
                except ConsoleError as e:
                    return _err(e)
            setattr(p, field, val)
            changed[field] = val.isoformat() if hasattr(val, 'isoformat') else val
        p.save()
        svc.audit(p, request.user, 'project.update', **changed)

    checklist = evaluate(p)
    from tracker.industry_categories import get_terminology
    latest_intake = p.intakes.first()
    return Response({
        **_project_summary(p, checklist),
        'contacts': p.contacts,
        'billing_model': p.billing_model,
        'coupon_months': p.coupon_months,
        'notes': p.notes,
        'terms': get_terminology(p.organization.industry_type),
        'clio_push_trigger': getattr(p.organization, 'clio_push_trigger', None),
        'checklist': checklist,
        'intake': _intake_summary(latest_intake),
    })


@operator_view(['POST'])
def mark_step(request, pk, step_key):
    p = _project(pk)
    step = STEPS_BY_KEY.get(step_key)
    if not step:
        return _err('Unknown step.', 404)
    d = request.data
    st, _ = OnboardingStepState.objects.get_or_create(project=p, step_key=step_key)
    if 'done' in d:
        if step.check and d['done']:
            return _err('This step ticks itself from live data — it cannot be ticked by hand. '
                        'Mark it not applicable if it does not apply.')
        st.done = bool(d['done'])
        st.done_at = timezone.now() if st.done else None
    if 'not_applicable' in d:
        st.not_applicable = bool(d['not_applicable'])
    if 'note' in d:
        st.note = str(d['note'] or '')[:4000]
    st.updated_by = request.user
    st.save()
    svc.audit(p, request.user, 'step.mark', step=step_key, done=st.done,
              not_applicable=st.not_applicable, note=st.note[:200])
    return Response({'ok': True})


@operator_view(['GET'])
def verify(request, pk):
    from tracker.management.commands.verify_firm import run_checks
    p = _project(pk)
    report = run_checks(p.organization)
    if p.install_path not in AUTO_PAIR:
        # A hand install pairs with a code: no token, no hostname map, no
        # auto-pair. verify_firm can't know that, so it would show a firm that
        # is fine as blocked. Say what is true for this firm instead.
        for line in report['lines']:
            if line['label'] in _AUTO_PAIR_ONLY:
                line['state'] = 'ok'
                line['detail'] = f"{line['detail']} — not used (hand install)"
        report['issues'] = [i for i in report['issues'] if i['label'] not in _AUTO_PAIR_ONLY]
    return Response(report)


_AUTO_PAIR_ONLY = {'deployment token', 'device maps', 'pairing'}


@operator_view(['GET'])
def audit_log(request, pk):
    p = _project(pk)
    events = (OnboardingAuditEvent.objects.filter(project=p)
              .select_related('actor')[:200])
    return Response({'events': [
        {'action': e.action, 'detail': e.detail, 'actor': _person(e.actor),
         'at': e.created_at.isoformat()} for e in events
    ]})


# ── Actions ──────────────────────────────────────────────────────────────

@operator_view(['POST'])
def run_import(request, pk):
    p = _project(pk)
    d = request.data
    dry_run = bool(d.get('dry_run', True))
    try:
        result = svc.run_provision(p.organization, kind=d.get('kind'),
                                   csv_text=d.get('csv') or '', dry_run=dry_run,
                                   update=bool(d.get('update')))
    except ConsoleError as e:
        return _err(e)
    if not dry_run:
        svc.audit(p, request.user, f'import.{d.get("kind")}', ok=result['ok'],
                  update=bool(d.get('update')), rows=max(0, (d.get('csv') or '').count('\n') - 1))
    return Response(result)


@operator_view(['GET'])
def intake_csv(request, pk, kind):
    p = _project(pk)
    intake = p.intakes.filter(last_saved_at__isnull=False).first()
    if not intake:
        return _err('The firm has not filled in the intake form yet.', 404)
    try:
        return Response({'csv': svc.intake_csv(intake.payload, kind)})
    except ConsoleError as e:
        return _err(e)


@operator_view(['GET', 'PUT'])
def mappings(request, pk):
    p = _project(pk)
    if request.method == 'PUT':
        try:
            result = svc.save_mappings(p.organization, request.data.get('selections') or {})
        except ConsoleError as e:
            return _err(e)
        svc.audit(p, request.user, 'mappings.save', **result)
        return Response(result)
    return Response(svc.mapping_grid(p.organization))


@operator_view(['POST'])
def suggest_mappings(request, pk):
    p = _project(pk)
    result = svc.suggest_mappings(p.organization)
    svc.audit(p, request.user, 'mappings.suggest', source=result['source'])
    return Response(result)


@operator_view(['GET', 'POST'])
def invites(request, pk):
    p = _project(pk)
    if request.method == 'POST':
        rows = svc.send_invites(p.organization, request.user)
        svc.audit(p, request.user, 'invites.issue', count=len(rows),
                  emailed=sum(1 for r in rows if r['emailed'] == 'yes'))
        return Response({'issued': rows, 'roster': svc.invite_roster(p.organization)})
    return Response({'roster': svc.invite_roster(p.organization)})


@operator_view(['POST'])
def token(request, pk):
    p = _project(pk)
    tok, created = svc.ensure_token(p.organization, request.user)
    if created:
        svc.audit(p, request.user, 'token.issue', token=tok.token)
    return Response({'token': tok.token, 'created': created})


@operator_view(['GET'])
def pairing(request, pk):
    return Response(svc.pairing_readiness(_project(pk).organization))


@operator_view(['POST'])
def aliases(request, pk):
    p = _project(pk)
    result = svc.derive_aliases(p.organization)
    svc.audit(p, request.user, 'aliases.derive', ok=result['ok'])
    return Response(result)


@operator_view(['POST'])
def clio_trigger(request, pk):
    p = _project(pk)
    try:
        svc.set_clio_trigger(p.organization, request.data.get('trigger'))
    except ConsoleError as e:
        return _err(e)
    st, _ = OnboardingStepState.objects.get_or_create(project=p, step_key='clio_trigger')
    st.done, st.done_at, st.updated_by = True, timezone.now(), request.user
    st.save()
    svc.audit(p, request.user, 'clio.trigger', trigger=request.data.get('trigger'))
    return Response({'ok': True})


@operator_view(['GET', 'POST'])
def stripe_setup(request, pk):
    p = _project(pk)
    if request.method == 'GET':
        org = p.organization
        billing = (p.contacts or {}).get('billing') or {}
        return Response({**svc.stripe_config(),
                         'linked': bool(org.stripe_subscription_id),
                         'customer': org.stripe_customer_id or None,
                         'subscription': org.stripe_subscription_id or None,
                         'plan': org.plan, 'seat_count': org.seat_count,
                         'coupon_months': p.coupon_months,
                         'billing_email': billing.get('email', '')})
    d = request.data
    try:
        result = svc.setup_stripe(p.organization, plan=d.get('plan'),
                                  interval=d.get('interval'), seats=d.get('seats'),
                                  coupon_months=d.get('coupon_months'),
                                  billing_email=d.get('billing_email'))
    except ConsoleError as e:
        svc.audit(p, request.user, 'stripe.failed', error=str(e))
        return _err(e)
    if d.get('coupon_months') is not None:
        p.coupon_months = int(d.get('coupon_months') or 0)
        p.save(update_fields=['coupon_months'])
    svc.audit(p, request.user, 'stripe.setup', **result)
    return Response(result)


@operator_view(['POST'])
def deploy_kit(request, pk):
    p = _project(pk)
    kit = svc.deploy_kit(p, request.user)
    st, _ = OnboardingStepState.objects.get_or_create(project=p, step_key='deploy_kit')
    if not st.done:
        st.done, st.done_at, st.updated_by = True, timezone.now(), request.user
        st.save()
    svc.audit(p, request.user, 'deploy_kit.build', token=kit['token'])
    return Response(kit)


@operator_view(['GET', 'POST'])
def delete_project(request, pk):
    """GET: what a delete would do. POST {confirm_name, delete_firm}: do it."""
    p = _project(pk)
    if request.method == 'GET':
        return Response(svc.deletion_check(p))
    try:
        result = svc.delete_onboarding(
            p, request.user, confirm_name=request.data.get('confirm_name'),
            delete_firm=bool(request.data.get('delete_firm')))
    except ConsoleError as e:
        return _err(e)
    return Response(result)


@operator_view(['POST'])
def go_live(request, pk):
    p = _project(pk)
    p.status = 'live'
    p.went_live_at = p.went_live_at or timezone.now()
    p.save(update_fields=['status', 'went_live_at', 'updated_at'])
    svc.audit(p, request.user, 'project.live')
    return Response({'ok': True})


# ── Intake (operator side) ───────────────────────────────────────────────

def _intake_summary(i):
    if not i:
        return None
    return {
        'id': i.id, 'is_open': i.is_open,
        'created_at': i.created_at.isoformat(), 'expires_at': i.expires_at.isoformat(),
        'last_saved_at': i.last_saved_at.isoformat() if i.last_saved_at else None,
        'submitted_at': i.submitted_at.isoformat() if i.submitted_at else None,
        'revoked_at': i.revoked_at.isoformat() if i.revoked_at else None,
        'payload': i.payload,
        'sent': _sent_summary(i),
    }


def _sent_summary(i):
    ev = svc.intake_sent_event(i)
    if not ev:
        return None
    return {'to': ev.detail.get('to'), 'how': ev.detail.get('how'),
            'at': ev.created_at.isoformat(),
            'by': ev.actor.get_full_name() or ev.actor.email if ev.actor else None}


def _frontend_base():
    from django.conf import settings
    return getattr(settings, 'FRONTEND_URL', 'https://timetracker.mavops.ai').rstrip('/')


@operator_view(['POST'])
def intake_link(request, pk):
    """Issue the firm a fresh intake link. The raw token is returned once."""
    p = _project(pk)
    intake, raw = OnboardingIntake.mint(p)
    svc.audit(p, request.user, 'intake.issue', intake_id=intake.id)
    return Response({'url': f'{_frontend_base()}/intake/{raw}', **_intake_summary(intake)})


@operator_view(['POST'])
def intake_reopen(request, pk):
    """Let the firm edit a submitted form again — same answers, new link."""
    p = _project(pk)
    intake, raw = OnboardingIntake.mint(p)
    svc.audit(p, request.user, 'intake.reopen', intake_id=intake.id)
    return Response({'url': f'{_frontend_base()}/intake/{raw}', **_intake_summary(intake)})


@operator_view(['POST'])
def intake_send(request, pk):
    """Email the firm a fresh intake link. The link is returned either way."""
    p = _project(pk)
    try:
        r = svc.send_intake(p, request.user, to_email=request.data.get('email'),
                            contact_name=request.data.get('name') or '')
    except ConsoleError as e:
        return _err(e)
    return Response({'url': r['url'], 'emailed': r['emailed'], 'to': r['to'],
                     **_intake_summary(r['intake'])})


@operator_view(['POST'])
def intake_mark_sent(request, pk):
    """Record that the current link went out some other way."""
    p = _project(pk)
    try:
        intake = svc.mark_intake_sent_by_hand(p, request.user, to=request.data.get('to') or '')
    except ConsoleError as e:
        return _err(e)
    return Response(_intake_summary(intake))


# ── Intake (the firm's side — public, token only) ────────────────────────

class PublicIntake(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_scope = 'onboard_intake'

    def _get(self, raw):
        intake = (OnboardingIntake.objects
                  .select_related('project__organization')
                  .filter(token_hash=OnboardingIntake.hash_token(raw or '')).first())
        return intake

    def _payload(self, intake):
        from tracker.industry_categories import get_terminology
        p = intake.project
        org = p.organization
        return {
            'firm': org.name,
            'vertical': org.industry_type,
            'install_path': p.install_path,
            'terms': get_terminology(org.industry_type),
            'answers': intake.payload,
            'submitted_at': intake.submitted_at.isoformat() if intake.submitted_at else None,
            'editable': intake.is_open,
        }

    def get(self, request, raw):
        intake = self._get(raw)
        if not intake or intake.revoked_at:
            return Response({'error': 'This link is no longer valid. Ask Mavops for a new one.'},
                            status=404)
        if not intake.submitted_at and intake.expires_at <= timezone.now():
            return Response({'error': 'This link has expired. Ask Mavops for a new one.'},
                            status=410)
        return Response(self._payload(intake))

    def post(self, request, raw):
        intake = self._get(raw)
        if not intake or not intake.is_open:
            return Response({'error': 'This form can no longer be changed.'}, status=409)
        try:
            payload = svc.clean_intake_payload(request.data.get('answers') or {})
        except ConsoleError as e:
            return _err(e)
        submit = bool(request.data.get('submit'))
        intake.payload = payload
        intake.last_saved_at = timezone.now()
        if submit:
            intake.submitted_at = intake.last_saved_at
            _apply_intake_contacts(intake)
        intake.save()
        svc.audit(intake.project, None, 'intake.submit' if submit else 'intake.save',
                  intake_id=intake.id, team=len(payload.get('team') or []),
                  services=len(payload.get('services') or []))
        return Response(self._payload(intake))


def _apply_intake_contacts(intake):
    """Copy what the firm told us onto the project, without overwriting
    anything an operator already filled in by hand."""
    p = intake.project
    contacts = dict(p.contacts or {})
    for role, c in (intake.payload.get('contacts') or {}).items():
        if any((c or {}).values()) and not any((contacts.get(role) or {}).values()):
            contacts[role] = c
    p.contacts = contacts
    answers = intake.payload.get('answers') or {}
    if not p.billing_model and answers.get('billing_model') in ('hourly', 'retainer', 'mix'):
        p.billing_model = answers['billing_model']
    p.save(update_fields=['contacts', 'billing_model', 'updated_at'])
