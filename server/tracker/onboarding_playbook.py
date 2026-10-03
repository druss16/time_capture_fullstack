"""
The onboarding playbooks — CPA, law firm and marketing agency — as data.

They used to be three Notion pages, duplicated per firm, printed, and ticked
off with a pen. Most of their checkboxes recorded facts the database already
holds, so here each step says how it is satisfied:

  kind='auto'    a live check against the firm's own records (Facts below).
                 Never stored as done: re-evaluated on every read, so a firm
                 that loses a mapping or un-pairs goes back to red.
  kind='action'  the console has a button that does it, AND a live check
                 that says whether it worked.
  kind='manual'  a person ticks it: a call, a decision, or the firm's IT doing
                 its part. `who` says whose job it is.

`verticals` and `paths` filter a step to the firms it applies to; empty means
every firm. The step order inside a phase is the order to do them in.

Adding a step is adding a row here. Nothing else needs to change: the console
renders whatever this list returns.
"""
from dataclasses import dataclass
from datetime import timedelta
from functools import cached_property

from django.db.models import Count, F, Q
from django.utils import timezone

PHASES = [
    ('intake', 'Intake'),
    ('provision', 'Provision'),
    ('billing', 'Billing'),
    ('invites', 'Setup links'),
    ('install', 'Install'),
    ('golive', 'Go-live'),
    ('postlaunch', 'Post-launch'),
]

WINDOWS = ('windows_gpo', 'windows_hand')
MAC = ('mac_hand', 'mac_mdm')
AUTO_PAIR = ('windows_gpo', 'mac_mdm')


@dataclass(frozen=True)
class Step:
    key: str
    phase: str
    title: str
    kind: str                       # auto / action / manual
    who: str = 'us'                 # us / firm / firm_it / system
    help: str = ''
    verticals: tuple = ()
    paths: tuple = ()
    check: str = ''                 # Facts method name, for auto/action
    action: str = ''                # console UI action id

    def applies(self, vertical, path):
        return ((not self.verticals or vertical in self.verticals)
                and (not self.paths or path in self.paths))


STEPS = [
    # ── Intake ──────────────────────────────────────────────────────────
    Step('signed', 'intake', 'Sales call done; firm signed', 'manual'),
    Step('intake_sent', 'intake', 'Intake link sent to the firm', 'action',
         check='intake_sent', action='intake',
         help='One link replaces the intake doc and the spreadsheet chase. The firm '
              'fills in its team, services and contacts; you import from it.'),
    Step('intake_back', 'intake', 'Intake answers received', 'auto', who='firm',
         check='intake_received'),
    Step('macs_checked', 'intake', 'Every Mac is Apple Silicon (M1 or later)', 'manual',
         who='firm', paths=MAC,
         help='The agent is Apple Silicon only. An Intel Mac cannot run it — find out '
              'now, not on install day.'),
    Step('mac_admin', 'intake', 'Know who holds each Mac\'s admin password', 'manual',
         who='firm', paths=MAC,
         help='Needed for about 5 minutes per Mac, once: the install and the '
              'Accessibility switch. Updates need no password from v1.9.11 on. '
              'Record WHO, never the password.'),
    Step('billing_model', 'intake', 'Billing model confirmed: hourly / retainer / mix', 'manual',
         verticals=('marketing',),
         help='And where the rate comes from — the person, the service, or the client.'),
    Step('clio_decision', 'intake', 'Decided: push time to Clio, on submit or on approve?',
         'manual', verticals=('legal',),
         help='On approve (default): time reaches Clio after a manager signs off. On '
              'submit: as soon as the timekeeper submits. Confirm it out loud on the call.'),
    Step('it_contact', 'intake', 'IT admin contact collected', 'manual', paths=AUTO_PAIR),
    Step('billing_contact', 'intake', 'Billing contact collected', 'manual'),
    Step('seats', 'intake', 'Seat count confirmed', 'manual'),

    # ── Provision ───────────────────────────────────────────────────────
    Step('vertical', 'provision', 'Organization created with the right vertical', 'auto',
         check='vertical',
         help='industry_type is fixed when the onboarding is created, so the old silent '
              'failure (a whole firm provisioned as "general") cannot happen here.'),
    Step('team', 'provision', 'Team imported', 'action', check='team', action='import_team',
         help='Upload the team CSV or use the intake roster. You see a dry run first.'),
    Step('device_maps', 'provision', 'Every member has a machine hostname for auto-pair',
         'auto', check='device_maps', paths=AUTO_PAIR,
         help='Hostname case matters. A mismatch means that person pairs by hand.'),
    Step('qbo_connected', 'provision', 'QuickBooks Online connected', 'auto', who='firm',
         check='qbo_connected', verticals=('marketing',),
         help='The agency\'s QuickBooks admin connects it in Settings → Connections → '
              'Integrations → QuickBooks, then Import Clients. For an agency, QuickBooks '
              'is its OWN books — time in it is admin, never client work.'),
    Step('clio_connected', 'provision', 'Clio connected (correct region)', 'auto', who='firm',
         check='clio_connected', verticals=('legal',),
         help='Settings → Connections → Integrations → Clio. Pick US / EU / AU correctly '
              'or the OAuth round-trip fails.'),
    Step('clio_trigger', 'provision', 'Clio push trigger set to the firm\'s choice', 'action',
         check='clio_trigger', action='clio_trigger', verticals=('legal',)),
    Step('clients', 'provision', 'Clients imported', 'action', check='clients',
         action='import_clients',
         help='Prefer pulling from the firm\'s system (QuickBooks, Clio) over a CSV — '
              'retyping a list is how you get two of everything.'),
    Step('qbo_cleanup', 'provision', 'Vendors / partners / internal entries removed from '
         'the imported customers', 'manual', verticals=('marketing',)),
    Step('campaigns', 'provision', 'Campaigns added', 'manual', verticals=('marketing',),
         help='QuickBooks Projects don\'t come across yet. Use the web client import '
              '(project column) or add them in the app.'),
    Step('task_types', 'provision', 'Service codes / activity types imported', 'action',
         check='task_types', action='import_task_types'),
    Step('mappings', 'provision', 'Every canonical category mapped', 'action',
         check='mappings', action='mappings',
         help='The AI draft is a starting point. Review every row — the grid will not '
              'save with a category left blank.'),
    Step('aliases', 'provision', 'Under 5% of clients without aliases', 'action',
         check='aliases', action='derive_aliases'),
    Step('token', 'provision', 'Deployment token issued', 'action', check='token',
         action='token', paths=AUTO_PAIR),

    # ── Billing ─────────────────────────────────────────────────────────
    Step('stripe', 'billing', 'Stripe subscription linked', 'action', check='stripe',
         action='stripe',
         help='Before setup links go out, or staff hit the billing wall.'),

    # ── Setup links ─────────────────────────────────────────────────────
    Step('invites', 'invites', 'Every member has a setup link (or has signed in)', 'action',
         check='invites', action='invites',
         help='Single-use, 7 days. Never set passwords by hand. If mail is down the '
              'links are shown here — send each person only their own.'),

    # ── Install ─────────────────────────────────────────────────────────
    Step('pair_dry_run', 'install', 'Auto-pair dry run passes', 'action',
         check='pair_dry_run', action='pair_dry_run', paths=AUTO_PAIR,
         help='Checks the token and every hostname the way the agent will, without '
              'pairing anything — no reset needed afterwards.'),
    Step('deploy_kit', 'install', 'Deployment kit built', 'action', action='deploy_kit',
         paths=AUTO_PAIR,
         help='Windows: installer + the token-filled logon script. Mac MDM: the pkg + '
              'the config.plist (OrgToken + ApiEndpoint) + the extension profile.'),
    Step('sent_to_it', 'install', 'Kit and instructions sent to IT', 'manual',
         paths=AUTO_PAIR,
         help='Gmail blocks .ps1 and .exe — use a Drive link.'),
    Step('it_gpo', 'install', 'IT added the script as ONE GPO Logon script', 'manual',
         who='firm_it', paths=('windows_gpo',),
         help='User Configuration → Windows Settings → Scripts → Logon. Logon, not '
              'Startup. Do not use the old TimeTrackerWatchdog_GPO.xml.'),
    Step('it_mdm', 'install', 'IT pushed the pkg, config profile and extension profile',
         'manual', who='firm_it', paths=('mac_mdm',),
         help='Accessibility still has to be granted on each Mac unless IT pushes its own '
              'PPPC profile — not the one in the repo, it targets the wrong bundle ID.'),
    Step('hand_install', 'install', 'Agent installed by hand on every machine', 'manual',
         who='firm', paths=('mac_hand', 'windows_hand'),
         help='Mac: download TimeTracker.pkg, admin password, pair with the code from '
              'timetracker.mavops.ai/devices (not Settings → Devices), then '
              'Accessibility ON, Allow each Automation prompt, Enable the Chrome '
              'extension in every profile.'),
    Step('extension', 'install', 'Chrome extension enabled in every profile', 'manual',
         who='firm', paths=('mac_hand',)),
    Step('first_device', 'install', 'First device paired', 'auto', who='system',
         check='first_device'),
    Step('all_devices', 'install', 'Every member has a paired device', 'auto', who='system',
         check='all_devices'),

    # ── Go-live ─────────────────────────────────────────────────────────
    Step('signed_in', 'golive', 'Everyone has signed in', 'auto', who='firm',
         check='signed_in'),
    Step('titles', 'golive', 'Blocks carry real window titles', 'auto', who='system',
         check='titles', paths=MAC,
         help='Blocks showing only an app name ("Google Chrome", "Figma") mean '
              'Accessibility is off on that Mac.'),
    Step('pipeline', 'golive', 'Under 10% of categorized time missing a service code',
         'auto', who='system', check='pipeline',
         help='Higher means a category is missing from the mapping.'),
    Step('needs_matter', 'golive', '"Needs a matter" lane trending down', 'manual',
         verticals=('legal',),
         help='Busy in week one is normal; still busy in week three means matters '
              'are not being pulled or the list is stale.'),
    Step('first_clio_push', 'golive', 'First Clio push landed', 'auto', who='system',
         check='first_clio_push', verticals=('legal',),
         help='Then confirm the entries in Clio itself.'),
    Step('social_review', 'golive', 'Week one: non-billable lane checked for real work',
         'manual', verticals=('marketing',),
         help='Podcast production and hospitality-client research are the known '
              'suspects. Social media arriving in Needs You is by design.'),
    Step('followup', 'golive', 'Follow-up call scheduled', 'manual'),

    # ── Post-launch ─────────────────────────────────────────────────────
    Step('capturing', 'postlaunch', 'Everyone capturing time this week', 'auto',
         who='system', check='capturing'),
    Step('first_approved', 'postlaunch', 'First timesheet submitted and approved', 'auto',
         who='firm', check='first_approved',
         help='Exercises the whole loop.'),
    Step('first_month', 'postlaunch', 'First month reviewed with the partner / owner',
         'manual',
         help='Do the hours and the split by client match their sense of the work?'),
    Step('departments', 'postlaunch', 'Departments list handed over for the department '
         'feature', 'manual', verticals=('marketing',)),
    Step('coupon_reminder', 'postlaunch', 'Reminder set for coupon expiry', 'manual'),
    Step('live', 'postlaunch', 'Marked live', 'action', check='live', action='go_live'),
]

STEPS_BY_KEY = {s.key: s for s in STEPS}
assert len(STEPS_BY_KEY) == len(STEPS), 'duplicate step key'


def steps_for(project):
    return [s for s in STEPS if s.applies(project.vertical, project.install_path)]


class Facts:
    """Everything the auto checks read, computed once per request."""

    def __init__(self, project):
        self.project = project
        self.org = project.organization
        self.now = timezone.now()

    # ── shared inputs ───────────────────────────────────────────────────
    @cached_property
    def members(self):
        from tracker.models import OrganizationMembership
        return list(OrganizationMembership.objects
                    .filter(organization=self.org).select_related('user'))

    @cached_property
    def member_ids(self):
        return [m.user_id for m in self.members]

    @cached_property
    def device_user_ids(self):
        from tracker.models import AgentDevice
        return set(AgentDevice.objects.filter(user_id__in=self.member_ids, is_active=True)
                   .values_list('user_id', flat=True))

    @cached_property
    def recent_blocks(self):
        from tracker.models import Block
        return Block.objects.filter(org=self.org, start__gte=self.now - timedelta(days=7))

    @cached_property
    def recent_user_ids(self):
        return set(self.recent_blocks.values_list('user_id', flat=True).distinct())

    def _integration(self, provider):
        from tracker.models import Integration
        return Integration.objects.filter(organization=self.org, provider=provider).first()

    # ── checks: each returns (done, detail) ─────────────────────────────
    def intake_sent(self):
        from tracker.models_onboarding_console import OnboardingIntake
        last = OnboardingIntake.objects.filter(project=self.project).first()
        if not last:
            return False, 'no link yet'
        if last.submitted_at:
            return True, f'submitted {last.submitted_at:%b %d}'
        if not last.is_open:
            return False, 'last link expired or revoked — send a new one'
        # A link existing is not a link sent: it ticks once it has gone out.
        from tracker.services.onboarding_console import intake_sent_event
        sent = intake_sent_event(last)
        if not sent:
            return False, 'link made but not sent — Send by email, or mark it sent'
        to = sent.detail.get('to') or 'the firm'
        return True, f'sent to {to} {sent.created_at:%b %d} · open until {last.expires_at:%b %d}'

    def intake_received(self):
        from tracker.models_onboarding_console import OnboardingIntake
        sub = (OnboardingIntake.objects.filter(project=self.project,
                                               submitted_at__isnull=False).first())
        if sub:
            return True, f'submitted {sub.submitted_at:%b %d}'
        draft = OnboardingIntake.objects.filter(project=self.project,
                                                last_saved_at__isnull=False).first()
        if draft:
            return False, f'firm started it — last saved {draft.last_saved_at:%b %d}'
        return False, 'not started'

    def vertical(self):
        from tracker.industry_categories import get_categories_for_industry
        cats = get_categories_for_industry(self.org.industry_type) or []
        if not cats:
            return False, f'"{self.org.industry_type}" has no categories'
        return True, f'{self.org.industry_type} ({len(cats)} categories)'

    def team(self):
        n = len(self.members)
        return n > 0, f'{n} member(s)' if n else 'nobody imported yet'

    def device_maps(self):
        from tracker.models import DeviceProvisioningMap
        maps = DeviceProvisioningMap.objects.filter(organization=self.org).count()
        n = len(self.members)
        if not n:
            return False, 'import the team first'
        return maps >= n, f'{maps} hostname(s) for {n} member(s)'

    def qbo_connected(self):
        i = self._integration('quickbooks')
        return bool(i and i.is_connected), 'connected' if i and i.is_connected else 'not connected'

    def clio_connected(self):
        i = self._integration('clio')
        if i and i.is_connected:
            return True, f'connected ({i.api_region or "region unknown"})'
        return False, 'not connected'

    def clio_trigger(self):
        from tracker.models_onboarding_console import OnboardingStepState
        decided = OnboardingStepState.objects.filter(
            project=self.project, step_key='clio_trigger', done=True).exists()
        trig = getattr(self.org, 'clio_push_trigger', 'approve')
        return decided, f'on {trig}' + ('' if decided else ' (default — not confirmed)')

    def clients(self):
        from tracker.industry_categories import real_clients
        from tracker.models import Client
        n = real_clients(Client.objects.filter(org=self.org, is_active=True)).count()
        return n > 0, f'{n} active' if n else 'none yet'

    def task_types(self):
        from tracker.models import TaskType, TaskTypeSet
        n = TaskType.objects.filter(org=self.org, is_active=True).count()
        if not n:
            return False, 'none yet'
        if not TaskTypeSet.objects.filter(org=self.org, is_default=True).exists():
            return False, f'{n}, but no default set'
        return True, f'{n} active'

    @cached_property
    def unmapped(self):
        from tracker.industry_categories import get_categories_for_industry
        from tracker.services.task_type_resolver import resolve_task_type_for_category
        missing = []
        for cat in get_categories_for_industry(self.org.industry_type) or []:
            try:
                if not resolve_task_type_for_category(self.org, cat):
                    missing.append(cat)
            except Exception:                       # noqa: BLE001
                missing.append(cat)
        return missing

    def mappings(self):
        from tracker.industry_categories import get_categories_for_industry
        total = len(get_categories_for_industry(self.org.industry_type) or [])
        missing = self.unmapped
        return not missing and total > 0, f'{total - len(missing)}/{total} resolve'

    def aliases(self):
        from tracker.industry_categories import real_clients
        from tracker.models import Client
        vals = list(real_clients(Client.objects.filter(org=self.org, is_active=True))
                    .values_list('aliases', flat=True))
        if not vals:
            return False, 'no clients yet'
        none = sum(1 for a in vals if not a)
        pct = none / len(vals) * 100
        return pct < 5, f'{none} of {len(vals)} without aliases ({pct:.0f}%)'

    @cached_property
    def active_token(self):
        from tracker.models import OrgDeploymentToken
        return (OrgDeploymentToken.objects.filter(organization=self.org, is_active=True)
                .order_by('-id').first())

    def token(self):
        t = self.active_token
        if not t:
            return False, 'none'
        if not t.is_valid:
            return False, f'{t.token} expired'
        return True, t.token

    def stripe(self):
        plan = self.org.plan or 'none'
        if plan == 'none':
            return False, 'plan is none — staff will hit the billing wall'
        return True, f'{plan} · {self.org.seat_count} seats'

    def invites(self):
        from tracker.models import Invitation
        never = [m.user for m in self.members if m.user.last_login is None and m.user.email]
        if not self.members:
            return False, 'import the team first'
        if not never:
            return True, 'everyone has signed in'
        open_emails = {e.lower() for e in Invitation.objects.filter(
            organization=self.org, accepted_at__isnull=True, expires_at__gt=self.now,
        ).values_list('email', flat=True)}
        without = [u for u in never if u.email.lower() not in open_emails]
        detail = f'{len(never) - len(without)} link(s) out'
        if without:
            detail += f' · {len(without)} without a live link'
        return not without, detail

    def pair_dry_run(self):
        from tracker.services.onboarding_console import pairing_readiness
        r = pairing_readiness(self.org)
        return r['ok'], r['summary']

    def first_device(self):
        n = len(self.device_user_ids)
        return n > 0, f'{n} member(s) with a device' if n else 'none yet'

    def all_devices(self):
        n, total = len(self.device_user_ids), len(self.members)
        return total > 0 and n >= total, f'{n}/{total}'

    def signed_in(self):
        total = len(self.members)
        never = sum(1 for m in self.members if m.user.last_login is None)
        return total > 0 and never == 0, f'{total - never}/{total} signed in'

    def titles(self):
        per_user = (self.recent_blocks.values('user_id')
                    .annotate(n=Count('id'),
                              blank=Count('id', filter=Q(title='') | Q(title__iexact=F('app_name')))))
        rows = list(per_user)
        if not rows:
            return False, 'no blocks yet'
        bad = [r for r in rows if r['n'] and r['blank'] / r['n'] > 0.5]
        if bad:
            return False, f'{len(bad)} member(s) mostly app-name-only — Accessibility off?'
        return True, f'{len(rows)} member(s) with titled blocks'

    def pipeline(self):
        cat = self.recent_blocks.filter(is_categorized=True)
        n = cat.count()
        if not n:
            return False, 'no categorized blocks in 7 days'
        null = cat.filter(task_type__isnull=True).count()
        pct = null / n * 100
        return pct <= 10, f'{pct:.0f}% missing a service code ({n} blocks/7d)'

    def first_clio_push(self):
        from tracker.models import Timesheet
        ok = Timesheet.objects.filter(org=self.org, clio_push_status='done').exists()
        failed = Timesheet.objects.filter(org=self.org, clio_push_status='failed').exists()
        return ok, 'pushed' if ok else ('a push FAILED — open the timesheet banner'
                                        if failed else 'nothing pushed yet')

    def capturing(self):
        total = len(self.members)
        n = len(set(self.member_ids) & self.recent_user_ids)
        return total > 0 and n >= total, f'{n}/{total} with time in the last 7 days'

    def first_approved(self):
        from tracker.models import Timesheet
        ok = Timesheet.objects.filter(org=self.org, status__in=('approved', 'locked')).exists()
        return ok, 'yes' if ok else 'not yet'

    def live(self):
        p = self.project
        return p.status == 'live', ('live since ' + f'{p.went_live_at:%b %d}'
                                    if p.went_live_at else p.get_status_display())


def evaluate(project, include_checks=True):
    """The project's checklist with every step's live state.

    Returns {'phases': [...], 'progress': {...}, 'current_phase': key}.
    """
    from tracker.models_onboarding_console import OnboardingStepState

    facts = Facts(project)
    marks = {s.step_key: s for s in
             OnboardingStepState.objects.filter(project=project).select_related('updated_by')}
    phases = {k: {'key': k, 'title': t, 'steps': []} for k, t in PHASES}
    done_n = total_n = 0

    for step in steps_for(project):
        mark = marks.get(step.key)
        done, detail, error = False, '', None
        if step.check and include_checks:
            try:
                done, detail = getattr(facts, step.check)()
            except Exception as e:                  # noqa: BLE001
                error = str(e)
        if step.kind == 'manual' or (step.kind == 'action' and not step.check):
            done = bool(mark and mark.done)
        na = bool(mark and mark.not_applicable)
        if not na:
            total_n += 1
            done_n += 1 if done else 0
        phases[step.phase]['steps'].append({
            'key': step.key, 'title': step.title, 'kind': step.kind, 'who': step.who,
            'help': step.help, 'action': step.action, 'live': bool(step.check),
            'done': done, 'not_applicable': na, 'detail': detail, 'error': error,
            'note': mark.note if mark else '',
            'marked_by': (mark.updated_by.get_full_name() or mark.updated_by.email)
                         if mark and mark.updated_by else None,
            'marked_at': mark.updated_at.isoformat() if mark else None,
        })

    out = [p for p in phases.values() if p['steps']]
    current = None
    for p in out:
        open_steps = [s for s in p['steps'] if not s['done'] and not s['not_applicable']]
        p['done'] = not open_steps
        p['open'] = len(open_steps)
        if current is None and open_steps:
            current = p['key']
    return {
        'phases': out,
        'progress': {'done': done_n, 'total': total_n},
        'current_phase': current or 'postlaunch',
    }
