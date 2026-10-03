"""
The Onboarding Console's actions — every button that changes a firm.

Rule for this module: never re-implement provisioning. Imports go through the
provision_firm command itself (call_command, output captured), invites and the
AI mapping draft through the functions that command now exposes, and the
health report through verify_firm.run_checks. The console and the terminal
therefore cannot drift: there is one importer, it just has two front doors.
"""
import csv
import io
import os
import plistlib
import re
import tempfile

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

API_ENDPOINT = 'https://timetracker-api-k375.onrender.com/api'
RELEASES = 'https://github.com/druss16/timetracker-releases/releases/latest/download'
MAC_PKG_URL = f'{RELEASES}/TimeTracker.pkg'
WINDOWS_SETUP_URL = f'{RELEASES}/TimeTracker-Windows-Setup.exe'

MAX_CSV_BYTES = 2 * 1024 * 1024

TEAM_COLUMNS = ['email', 'display_name', 'role', 'billing_rate', 'cost_rate',
                'machine_hostname', 'windows_username']
CLIENT_COLUMNS = ['client_name', 'billing_rate', 'assigned_team']
TASK_TYPE_COLUMNS = ['name', 'code', 'is_billable', 'default_rate']

ROLES = {'owner', 'admin', 'manager', 'member'}


class ConsoleError(Exception):
    """An action the console refuses, with the reason to show the operator."""


# ── Audit ────────────────────────────────────────────────────────────────

def audit(project, actor, action, **detail):
    from tracker.models_onboarding_console import OnboardingAuditEvent
    OnboardingAuditEvent.objects.create(
        project=project, actor=actor if getattr(actor, 'pk', None) else None,
        action=action, detail=detail,
    )


# ── Projects ─────────────────────────────────────────────────────────────

def _unique_slug(name):
    from tracker.models import Organization
    base = slugify(name)[:40] or 'firm'
    slug, n = base, 2
    while Organization.objects.filter(slug=slug).exists():
        slug = f'{base[:37]}-{n}'
        n += 1
    return slug


_ENTITY_SUFFIXES = {'inc', 'incorporated', 'llc', 'llp', 'pllc', 'pc', 'pa', 'ltd',
                    'limited', 'co', 'company', 'corp', 'corporation', 'the'}


def _firm_key(name):
    """'The Smith & Co., LLC' and 'smith and co' compare equal."""
    words = re.findall(r'[a-z0-9]+', (name or '').lower().replace('&', ' and '))
    return ' '.join(w for w in words if w not in _ENTITY_SUFFIXES)


def find_existing_firm(name):
    """An organization that is already this firm, by name, or None.

    Creating a second org for a firm that exists splits its people, clients
    and time across two tenants — and nothing errors when it happens.
    """
    from tracker.models import Organization
    key = _firm_key(name)
    if not key:
        return None
    for org in Organization.objects.only('id', 'name', 'slug'):
        if _firm_key(org.name) == key:
            return org
    return None


REPLAY_WINDOW_SECONDS = 120


def _just_created_by(org, actor, vertical):
    """The project this operator created for this org moments ago, if any.

    A double-clicked Start (or a retried request) would otherwise create the
    firm on the first submit and fail the second on the duplicate check —
    which shows an error for something that worked. A repeat of the same
    request returns what the first one made instead.
    """
    from datetime import timedelta
    from tracker.models_onboarding_console import OnboardingProject
    if not getattr(actor, 'pk', None) or org.industry_type != vertical:
        return None
    return (OnboardingProject.objects
            .filter(organization=org, created_by=actor,
                    created_at__gte=timezone.now() - timedelta(seconds=REPLAY_WINDOW_SECONDS))
            .first())


@transaction.atomic
def create_project(*, actor, vertical, install_path, name=None, seat_count=1,
                   org_id=None, slug=None, target_go_live=None):
    """Start an onboarding: a new org with its vertical set, or an existing one.

    The vertical is required and set on the org here, before anything can be
    imported. That is the whole fix for the playbooks' worst silent failure:
    `industry_type` defaulting to 'general' and the firm provisioning cleanly
    with the wrong categories, words and social-media rules.
    """
    from tracker.industry_categories import INDUSTRY_TYPES
    from tracker.models import Organization
    from tracker.models_onboarding_console import INSTALL_PATH_CHOICES, OnboardingProject

    if vertical not in dict(INDUSTRY_TYPES):
        raise ConsoleError(f'Unknown vertical "{vertical}".')
    if install_path not in dict(INSTALL_PATH_CHOICES):
        raise ConsoleError(f'Unknown install path "{install_path}".')

    if org_id:
        org = Organization.objects.filter(id=org_id).first()
        if not org:
            raise ConsoleError('Organization not found.')
        if OnboardingProject.objects.filter(organization=org).exists():
            replay = _just_created_by(org, actor, vertical)
            if replay:
                return replay
            raise ConsoleError(f'{org.name} already has an onboarding.')
        if org.industry_type != vertical:
            # Adopting an existing firm is also the moment to correct it —
            # but say so in the audit trail, since it changes their categories.
            old = org.industry_type
            org.industry_type = vertical
            org.save(update_fields=['industry_type'])
            changed_vertical = (old, vertical)
        else:
            changed_vertical = None
    else:
        name = (name or '').strip()
        if not name:
            raise ConsoleError('Firm name is required.')
        existing = find_existing_firm(name)
        if existing:
            replay = _just_created_by(existing, actor, vertical)
            if replay:
                return replay
            raise ConsoleError(
                f'"{existing.name}" already exists in TimeTracker (org #{existing.id}, '
                f'{existing.slug}). Choose "Firm already in TimeTracker" instead of '
                f'creating a second one.')
        slug = slugify(slug)[:50] if slug else _unique_slug(name)
        if Organization.objects.filter(slug=slug).exists():
            raise ConsoleError(f'Slug "{slug}" is taken.')
        org = Organization.objects.create(
            name=name, slug=slug, plan='none',
            seat_count=max(1, int(seat_count or 1)),
            industry_type=vertical,
        )
        changed_vertical = None

    project = OnboardingProject.objects.create(
        organization=org, install_path=install_path, owner=actor, created_by=actor,
        target_go_live=target_go_live or None,
    )
    audit(project, actor, 'project.create', org_id=org.id, org=org.name,
          vertical=vertical, install_path=install_path, adopted=bool(org_id),
          changed_vertical=changed_vertical)
    return project


# ── Imports (through provision_firm itself) ──────────────────────────────

def run_provision(org, *, kind, csv_text, dry_run, update=False):
    """Run provision_firm on uploaded CSV text and return its own report.

    A real run is wrapped in a transaction: the command imports row by row, so
    a failure halfway would otherwise leave half a roster behind. The dry run
    is the same command with --dry-run — the preview IS the importer.
    """
    flag = {'team': 'team', 'clients': 'clients', 'task_types': 'task_types'}.get(kind)
    if not flag:
        raise ConsoleError(f'Unknown import "{kind}".')
    if not (csv_text or '').strip():
        raise ConsoleError('The file is empty.')
    if len(csv_text.encode('utf-8')) > MAX_CSV_BYTES:
        raise ConsoleError('File is over 2 MB.')

    fd, path = tempfile.mkstemp(suffix='.csv')
    out, err = io.StringIO(), io.StringIO()
    ok = True
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as fh:
            fh.write(csv_text)
        kwargs = {flag: path, 'dry_run': dry_run, 'update': update,
                  'stdout': out, 'stderr': err, 'no_color': True}
        try:
            if dry_run:
                call_command('provision_firm', org=org.slug, **kwargs)
            else:
                with transaction.atomic():
                    call_command('provision_firm', org=org.slug, **kwargs)
        except CommandError as e:
            ok = False
            err.write(str(e))
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    return {'ok': ok, 'output': out.getvalue(), 'errors': err.getvalue()}


def _csv(columns, rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction='ignore')
    w.writeheader()
    for r in rows:
        w.writerow({c: ('' if r.get(c) is None else str(r.get(c)).strip()) for c in columns})
    return buf.getvalue()


def _role(raw):
    r = (raw or 'member').strip().lower()
    return r if r in ROLES else ('member' if r in ('staff', '') else 'member')


def intake_csv(payload, kind):
    """Turn the firm's intake answers into the CSV provision_firm reads."""
    payload = payload or {}
    if kind == 'team':
        rows = []
        for p in payload.get('team') or []:
            if not (p.get('email') or '').strip():
                continue
            host = (p.get('machine_hostname') or '').strip().upper()
            if host.endswith('.LOCAL'):
                host = host[:-len('.LOCAL')]
            rows.append({**p, 'email': p['email'].strip().lower(),
                         'role': _role(p.get('role')), 'machine_hostname': host})
        return _csv(TEAM_COLUMNS, rows)
    if kind == 'task_types':
        rows = []
        for s in payload.get('services') or []:
            if not (s.get('name') or '').strip():
                continue
            billable = s.get('is_billable')
            rows.append({**s, 'is_billable': 'false' if billable in (False, 'false', 'no')
                         else 'true'})
        return _csv(TASK_TYPE_COLUMNS, rows)
    if kind == 'clients':
        rows = [c for c in payload.get('clients') or [] if (c.get('client_name') or '').strip()]
        return _csv(CLIENT_COLUMNS, rows)
    raise ConsoleError(f'Unknown import "{kind}".')


# ── Category mappings ────────────────────────────────────────────────────

def mapping_grid(org):
    """Every canonical category, the firm's codes, and what each maps to now."""
    from tracker.industry_categories import get_categories_for_industry
    from tracker.models import TaskType
    from tracker.models_task_type_sets import CategoryTaskTypeMapping

    current = {m.category.lower(): m for m in
               CategoryTaskTypeMapping.objects.filter(org=org).select_related('task_type')}
    rows = []
    for cat in get_categories_for_industry(org.industry_type) or []:
        m = current.get(cat.lower())
        rows.append({
            'category': cat,
            'task_type_id': m.task_type_id if m else None,
            'source': m.source if m else None,
        })
    task_types = [
        {'id': t.id, 'code': t.code, 'name': t.name, 'is_billable': t.is_billable}
        for t in TaskType.objects.filter(org=org, is_active=True).order_by('name')
    ]
    return {'rows': rows, 'task_types': task_types}


_WORD = re.compile(r'[a-z0-9]+')


def name_match_draft(org):
    """A no-AI draft: exact name or code, then shared words, then billability.

    The fallback for when the AI draft is unavailable (the OpenAI account has
    run dry before). Weak on purpose — it only saves typing on obvious rows.
    """
    grid = mapping_grid(org)
    tts = grid['task_types']
    out = []
    for row in grid['rows']:
        cat = row['category']
        cat_l = cat.lower()
        pick, conf = None, 'LOW'
        for t in tts:
            if t['name'].lower() == cat_l or (t['code'] or '').lower() == cat_l:
                pick, conf = t, 'HIGH'
                break
        if not pick:
            words = set(_WORD.findall(cat_l)) - {'and', 'the', 'of'}
            best = 0
            for t in tts:
                n = len(words & set(_WORD.findall(t['name'].lower())))
                if n > best:
                    best, pick, conf = n, t, 'MEDIUM'
        if not pick and cat in ('Idle', 'Personal/Non-Billable'):
            pick = next((t for t in tts if not t['is_billable']), None)
        out.append({
            'category': cat,
            'task_type_code': pick['code'] if pick else None,
            'confidence': conf if pick else 'LOW',
            'reasoning': 'name match' if pick else 'no obvious match',
        })
    return out


def suggest_mappings(org):
    """AI draft, or the name-match draft with the reason the AI was unavailable."""
    from tracker.management.commands.provision_firm import (
        MappingSuggestionError, ai_mapping_suggestions,
    )
    try:
        return {'source': 'ai', 'rows': ai_mapping_suggestions(org), 'warning': None}
    except MappingSuggestionError as e:
        return {'source': 'name_match', 'rows': name_match_draft(org),
                'warning': f'AI draft unavailable ({e}). Showing a name-match draft instead.'}


@transaction.atomic
def save_mappings(org, selections):
    """Write the whole grid. Refuses a partial grid — that is the point of it.

    `selections` is {category: task_type_id}. Every row is saved source=
    'manual', so a later --update seed run never overwrites a human's choice.
    """
    from tracker.industry_categories import get_categories_for_industry
    from tracker.models import TaskType
    from tracker.models_task_type_sets import CategoryTaskTypeMapping

    canonical = get_categories_for_industry(org.industry_type) or []
    if not canonical:
        raise ConsoleError(f'industry_type "{org.industry_type}" has no categories.')
    tts = {t.id: t for t in TaskType.objects.filter(org=org, is_active=True)}
    missing = [c for c in canonical if not selections.get(c)]
    if missing:
        raise ConsoleError(f'{len(missing)} categor{"y" if len(missing) == 1 else "ies"} '
                           f'still unmapped: {", ".join(missing[:5])}'
                           + (' …' if len(missing) > 5 else ''))
    changed = 0
    for cat in canonical:
        tt = tts.get(int(selections[cat]))
        if not tt:
            raise ConsoleError(f'"{cat}" points at a service code this firm does not have.')
        existing = CategoryTaskTypeMapping.objects.filter(org=org, category__iexact=cat).first()
        if existing is None:
            CategoryTaskTypeMapping.objects.create(org=org, category=cat, task_type=tt,
                                                   source='manual')
            changed += 1
        elif existing.task_type_id != tt.id or existing.source != 'manual':
            existing.task_type = tt
            existing.source = 'manual'
            existing.save(update_fields=['task_type', 'source', 'updated_at'])
            changed += 1
    return {'saved': len(canonical), 'changed': changed}


# ── Invites, token, aliases, Clio trigger ────────────────────────────────

def invite_roster(org):
    from tracker.models import Invitation, OrganizationMembership
    now = timezone.now()
    open_inv = {}
    for inv in (Invitation.objects.filter(organization=org, accepted_at__isnull=True,
                                          expires_at__gt=now).order_by('created_at')):
        open_inv[inv.email.lower()] = inv
    out = []
    for m in (OrganizationMembership.objects.filter(organization=org)
              .select_related('user').order_by('user__first_name', 'user__email')):
        u = m.user
        inv = open_inv.get((u.email or '').lower())
        out.append({
            'name': u.get_full_name() or u.username,
            'email': u.email, 'role': m.role,
            'signed_in': u.last_login is not None,
            'last_login': u.last_login.isoformat() if u.last_login else None,
            'link_expires': inv.expires_at.isoformat() if inv else None,
        })
    return out


def send_invites(org, actor):
    """Issue links to everyone who has never signed in. Returns the links.

    Sent in the firm owner's name when there is one, otherwise the operator's.
    """
    from tracker.management.commands.provision_firm import issue_invites
    from tracker.models import OrganizationMembership
    owner = (OrganizationMembership.objects.filter(organization=org, role='owner')
             .select_related('user').first())
    inviter = owner.user if owner else actor
    return issue_invites(org, inviter)


def ensure_token(org, actor):
    from tracker.models import OrgDeploymentToken
    tok = (OrgDeploymentToken.objects.filter(organization=org, is_active=True)
           .order_by('-id').first())
    if tok and tok.is_valid:
        return tok, False
    tok = OrgDeploymentToken.objects.create(
        organization=org, is_active=True, created_by=actor,
        notes='Issued from the Onboarding Console',
    )
    return tok, True


def derive_aliases(org):
    out, err = io.StringIO(), io.StringIO()
    try:
        call_command('derive_aliases', org_id=org.id, stdout=out, stderr=err, no_color=True)
        ok = True
    except CommandError as e:
        ok = False
        err.write(str(e))
    return {'ok': ok, 'output': out.getvalue()[-20000:], 'errors': err.getvalue()}


def set_clio_trigger(org, trigger):
    if trigger not in ('approve', 'submit'):
        raise ConsoleError('Trigger must be "approve" or "submit".')
    org.clio_push_trigger = trigger
    org.save(update_fields=['clio_push_trigger'])


# ── Auto-pair, without pairing anything ──────────────────────────────────

def pairing_readiness(org):
    """What the agent's auto-pair call would find, checked without calling it.

    The playbook's test was a real auto-pair with a fake device and a hand-run
    reset afterwards — which pairs a real roster row, bumps the token's claim
    count, and on a missed reset leaves someone unable to auto-pair. Every
    thing it actually proved (token valid, hostnames on file and matchable) is
    readable directly, so it is read.
    """
    from tracker.models import DeviceProvisioningMap, OrgDeploymentToken
    tok = (OrgDeploymentToken.objects.filter(organization=org, is_active=True)
           .order_by('-id').first())
    token_ok = bool(tok and tok.is_valid)
    rows = []
    for m in DeviceProvisioningMap.objects.filter(organization=org).order_by('machine_hostname'):
        issues = []
        host = m.machine_hostname or ''
        if not host:
            issues.append('no hostname')
        if host.endswith('.LOCAL'):
            issues.append('ends in .local — the agent reports the name without it')
        if ' ' in host:
            issues.append('contains a space')
        if m.status == 'failed':
            issues.append(f'last attempt failed: {m.error_message or "no detail"}')
        rows.append({'hostname': host, 'email': m.email, 'display_name': m.display_name,
                     'windows_username': m.windows_username, 'status': m.status,
                     'issues': issues})
    flagged = sum(1 for r in rows if r['issues'])
    if not tok:
        summary = 'no deployment token'
    elif not token_ok:
        summary = f'{tok.token} is expired'
    elif not rows:
        summary = 'no hostnames on file'
    else:
        summary = (f'token {tok.token} valid · {len(rows)} hostname(s)'
                   + (f' · {flagged} with a problem' if flagged else ' · all matchable'))
    return {'ok': token_ok and bool(rows) and not flagged, 'summary': summary,
            'token': tok.token if tok else None, 'rows': rows}


# ── Stripe ───────────────────────────────────────────────────────────────

def stripe_config():
    prices = {
        f'{plan}_{interval}': bool(getattr(settings, f'STRIPE_PRICE_{plan.upper()}_{interval.upper()}', None))
        for plan in ('professional', 'executive') for interval in ('monthly', 'yearly')
    }
    return {'key_configured': bool(getattr(settings, 'STRIPE_SECRET_KEY', None)),
            'prices': prices}


def setup_stripe(org, *, plan, interval, seats, coupon_months, billing_email):
    """Coupon → customer → subscription → link to the org, in one action.

    The playbook's Phase 3 was four screens in the Stripe dashboard and then a
    shell snippet pasted against production. The customer id is saved the
    moment it exists, so a retry after a failed subscription reuses it rather
    than creating a second customer.
    """
    import stripe

    if plan not in ('professional', 'executive') or interval not in ('monthly', 'yearly'):
        raise ConsoleError('Pick a plan and a billing interval.')
    if org.stripe_subscription_id:
        raise ConsoleError(f'{org.name} already has a subscription '
                           f'({org.stripe_subscription_id}). Change it in Stripe.')
    key = getattr(settings, 'STRIPE_SECRET_KEY', None)
    if not key:
        raise ConsoleError('STRIPE_SECRET_KEY is not configured on this server.')
    price = getattr(settings, f'STRIPE_PRICE_{plan.upper()}_{interval.upper()}', None)
    if not price:
        raise ConsoleError(f'No Stripe price configured for {plan} {interval}.')
    try:
        seats = int(seats)
        coupon_months = int(coupon_months or 0)
    except (TypeError, ValueError):
        raise ConsoleError('Seats and coupon months must be whole numbers.')
    if seats < 1:
        raise ConsoleError('At least one seat.')
    if not (billing_email or '').strip():
        raise ConsoleError('A billing email is required — Stripe sends the invoice there.')

    stripe.api_key = key
    try:
        coupon_id = None
        if coupon_months > 0:
            coupon = stripe.Coupon.create(
                percent_off=100, duration='repeating', duration_in_months=coupon_months,
                name=f'{org.name} - Founding Client'[:40],
                metadata={'organization_id': str(org.id)},
            )
            coupon_id = coupon['id']

        if not org.stripe_customer_id:
            customer = stripe.Customer.create(
                name=org.name, email=billing_email.strip(),
                metadata={'organization_id': str(org.id)},
            )
            org.stripe_customer_id = customer['id']
            org.save(update_fields=['stripe_customer_id'])

        params = dict(
            customer=org.stripe_customer_id,
            items=[{'price': price, 'quantity': seats}],
            collection_method='send_invoice', days_until_due=30,
            metadata={'organization_id': str(org.id)},
        )
        if coupon_id:
            params['discounts'] = [{'coupon': coupon_id}]
        sub = stripe.Subscription.create(**params)
    except stripe.error.StripeError as e:
        raise ConsoleError(f'Stripe refused it: {getattr(e, "user_message", None) or e}')

    org.plan = plan
    org.seat_count = seats
    org.stripe_subscription_id = sub['id']
    org.save(update_fields=['plan', 'seat_count', 'stripe_subscription_id'])
    return {'customer': org.stripe_customer_id, 'subscription': sub['id'],
            'coupon': coupon_id, 'plan': plan, 'seats': seats}


# ── Deployment kit ───────────────────────────────────────────────────────

_TEMPLATE = os.path.join(settings.BASE_DIR, 'onboarding_templates',
                         'install_timetracker_FIRMSLUG.ps1')


def _windows_script(org, token):
    with open(_TEMPLATE, encoding='utf-8') as fh:
        text = fh.read()
    return (text.replace('REPLACE_WITH_ORG_TOKEN', token)
                .replace('FIRMSLUG', org.slug.replace('-', '').upper())
                .replace('FIRM_NAME', org.name))


def _mac_config_plist(token):
    return plistlib.dumps({'OrgToken': token, 'ApiEndpoint': API_ENDPOINT}).decode('utf-8')


def _mac_script(org, token):
    return f'''#!/bin/bash
# TimeTracker org-token config for {org.name}
# Run as root from your MDM (Jamf policy script / Kandji custom script /
# Mosyle custom command / Intune shell script) BEFORE or AFTER TimeTracker.pkg.
# It writes the file the agent reads on first run to auto-pair by hostname.
set -euo pipefail
DIR="/Library/Application Support/TimeTracker"
mkdir -p "$DIR"
cat > "$DIR/config.plist" <<'PLIST'
{_mac_config_plist(token).rstrip()}
PLIST
chown root:wheel "$DIR/config.plist"
chmod 644 "$DIR/config.plist"
echo "TimeTracker config written for {org.name}"
'''


def _it_email(org, project, token):
    contact = (project.contacts or {}).get('it_admin') or {}
    hi = contact.get('name') or 'there'
    if project.install_path == 'mac_mdm':
        body = f'''Hi {hi},

Here is everything to deploy TimeTracker to {org.name}'s Macs.

━━━ DEPLOY THREE THINGS ━━━
  1. TimeTracker.pkg  — {MAC_PKG_URL}
  2. timetracker_config_{org.slug}.sh — run as root (writes
     /Library/Application Support/TimeTracker/config.plist with your org token)
  3. The browser-extension profile — mavops-browser-extension.mobileconfig,
     staged by the pkg in /Library/Application Support/Mavops/. It
     force-installs and enables the Chrome extension silently.

The agent reads the config on first run and pairs itself to the right person
by hostname. Nobody sees a pairing window.

Accessibility still has to be switched on for TimeTracker on each Mac unless
you push your own PPPC profile for it. Without it, window titles are blank.

Apple Silicon (M1 or later) only.

━━━ WEB ACCESS ━━━
Staff review and submit time at https://timetracker.mavops.ai. Each person
gets their own setup link by email — there is nothing for you to distribute.

Dan Russell | Mavops AI | dan@mavops.ai
'''
    else:
        body = f'''Hi {hi},

Deployment files are in the shared folder linked below.

━━━ DESKTOP AGENT ━━━
Files:
  - TimeTracker-Windows-Setup.exe  ({WINDOWS_SETUP_URL})
  - install_timetracker_{org.slug.replace("-", "").upper()}.ps1

Steps:
  1. Place both files on your NETLOGON share
  2. GPO → User Configuration → Windows Settings → Scripts → Logon
  3. Add the .ps1 as a Logon script (Logon, not Startup)
  4. Run gpupdate /force on one test machine, log off and back on
  5. Confirm the TimeTracker tray icon appears

The script installs the agent, registers startup tasks, and launches the
watchdog. Updates after this are silent and automatic.

━━━ WEB ACCESS ━━━
Staff review and submit timesheets at https://timetracker.mavops.ai

Each person is getting their own setup link by email — they choose their
own password, so there's nothing for you to distribute or keep track of.
Anyone who doesn't see it can use "Forgot?" on the sign-in page.

Let me know if you hit anything during deployment.

Dan Russell | Mavops AI | dan@mavops.ai
'''
    return body


def deploy_kit(project, actor):
    """The files IT needs, filled in for this firm. Issues a token if needed."""
    org = project.organization
    tok, _ = ensure_token(org, actor)
    files = []
    if project.install_path in ('windows_gpo', 'windows_hand'):
        files.append({'name': f'install_timetracker_{org.slug.replace("-", "").upper()}.ps1',
                      'content': _windows_script(org, tok.token),
                      'note': 'Gmail blocks .ps1 — share via Drive, or rename to .txt.'})
        files.append({'name': 'TimeTracker-Windows-Setup.exe', 'url': WINDOWS_SETUP_URL,
                      'note': 'Latest release; IT never pushes updates again.'})
    else:
        files.append({'name': f'timetracker_config_{org.slug}.sh',
                      'content': _mac_script(org, tok.token),
                      'note': 'Run as root from the MDM.'})
        files.append({'name': 'config.plist', 'content': _mac_config_plist(tok.token),
                      'note': 'For MDMs that deploy a file directly to '
                              '/Library/Application Support/TimeTracker/.'})
        files.append({'name': 'TimeTracker.pkg', 'url': MAC_PKG_URL,
                      'note': 'Apple Silicon only.'})
    files.append({'name': f'email_to_it_{org.slug}.txt',
                  'content': _it_email(org, project, tok.token),
                  'note': 'Carries no credentials — paste it into your email to IT.'})
    return {'token': tok.token, 'files': files}


# ── Intake payload hygiene ───────────────────────────────────────────────

_MAX_ROWS = 1000
_MAX_PAYLOAD = 512 * 1024


def clean_intake_payload(data):
    """Bound what an unauthenticated form can store. Shape is kept loose on
    purpose — the console reads it — but size, row counts and types are not."""
    import json
    if not isinstance(data, dict):
        raise ConsoleError('Expected an object.')
    if len(json.dumps(data)) > _MAX_PAYLOAD:
        raise ConsoleError('That is too much data for one form — send us a file instead.')
    out = {}
    for key in ('team', 'services', 'clients'):
        rows = data.get(key) or []
        if not isinstance(rows, list):
            raise ConsoleError(f'"{key}" must be a list.')
        if len(rows) > _MAX_ROWS:
            raise ConsoleError(f'More than {_MAX_ROWS} rows in "{key}".')
        out[key] = [{str(k)[:64]: (v if isinstance(v, (bool, int, float)) or v is None
                                   else str(v)[:500])
                     for k, v in r.items()} for r in rows if isinstance(r, dict)]
    contacts = data.get('contacts') or {}
    if isinstance(contacts, dict):
        out['contacts'] = {str(k)[:32]: {str(f)[:32]: str(v)[:200] for f, v in c.items()}
                           for k, c in contacts.items() if isinstance(c, dict)}
    answers = data.get('answers') or {}
    if isinstance(answers, dict):
        out['answers'] = {str(k)[:64]: (v if isinstance(v, bool) else str(v)[:2000])
                          for k, v in answers.items()}
    return out



# ── Deleting an onboarding ───────────────────────────────────────────────

def _created_by_console(project):
    """True only when the console itself created this firm's organization.

    An adopted firm existed before the console touched it, so deleting the
    onboarding must never take its organization with it. Missing evidence
    counts as adopted.
    """
    ev = (project.audit_events.filter(action='project.create')
          .order_by('created_at').first())
    return bool(ev and ev.detail.get('adopted') is False)


def deletion_check(project):
    """What deleting this onboarding would do, and what blocks it."""
    from tracker.models import (
        AgentDevice, Block, Client, OrganizationMembership, Timesheet,
    )
    org = project.organization
    members = list(OrganizationMembership.objects.filter(organization=org)
                   .select_related('user'))
    user_ids = [m.user_id for m in members]
    blockers = []
    if Block.objects.filter(org=org).exists():
        blockers.append('time has been captured')
    if Timesheet.objects.filter(org=org).exists():
        blockers.append('timesheets exist')
    if org.stripe_subscription_id or org.stripe_customer_id:
        blockers.append('it is linked to Stripe')
    if AgentDevice.objects.filter(user_id__in=user_ids).exists():
        blockers.append('a device is paired')
    signed_in = [m.user.email for m in members if m.user.last_login]
    if signed_in:
        blockers.append(f'{len(signed_in)} member(s) have signed in')
    clients = Client.objects.filter(org=org).exclude(name__istartswith='Internal').count()
    return {
        'firm_created_here': _created_by_console(project),
        'blockers': blockers,
        'members': len(members),
        'clients': clients,
    }


@transaction.atomic
def delete_onboarding(project, actor, *, confirm_name, delete_firm):
    """Remove an onboarding — and, for a firm the console created, the firm.

    The confirmation is the firm's exact name. Staff accounts are deleted only
    when they were never used and belong to no other firm; anyone else keeps
    their account and just loses this membership.
    """
    from django.contrib.auth import get_user_model
    from tracker.models import OrganizationMembership

    org = project.organization
    if (confirm_name or '').strip() != org.name:
        raise ConsoleError('Type the firm name exactly to confirm.')
    check = deletion_check(project)
    if check['blockers']:
        raise ConsoleError('Not deleted — ' + '; '.join(check['blockers']) + '.')
    if delete_firm and not check['firm_created_here']:
        raise ConsoleError('This firm existed before its onboarding started, so only the '
                           'onboarding can be removed here — the firm itself stays.')

    summary = {'org_id': org.id, 'org': org.name, 'slug': org.slug,
               'deleted_firm': bool(delete_firm), 'members': check['members'],
               'clients': check['clients']}
    if delete_firm:
        User = get_user_model()
        user_ids = list(OrganizationMembership.objects.filter(organization=org)
                        .values_list('user_id', flat=True))
        org.delete()                       # cascades the project, memberships, clients
        # Memberships of the deleted firm are gone by now, so any membership
        # left means the person belongs to another firm — keep them.
        orphans = (User.objects.filter(id__in=user_ids, last_login__isnull=True,
                                       is_staff=False, is_superuser=False)
                   .exclude(memberships__isnull=False))
        summary['accounts_removed'] = orphans.count()
        orphans.delete()
    else:
        project.delete()
    # The project's own audit trail goes with it; this record outlives it.
    audit(None, actor, 'project.delete', **summary)
    return summary
