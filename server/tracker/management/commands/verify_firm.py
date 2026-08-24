"""
tracker/management/commands/verify_firm.py

One go/no-go report for a firm's onboarding.

Replaces the pile of hand-pasted `shell -c` snippets the playbook used to carry
at Phase 2.3, Phase 4 and Phase 7. Those were multi-line Python scripts typed
against the production database with the slug re-entered each time, which is
both slow and the easiest place in the whole rollout to act on the wrong org.

Run the same command at every stage and watch the numbers move:

    after provisioning   → team and clients land, mappings still missing
    after mappings       → 19/19 resolve
    at go-live           → invites out, pairing starts
    24h later            → blocks flowing, task types attached

Checks are ordered by how silently the thing fails. industry_type is first
because it breaks category mapping without any error at provisioning time —
the whole firm imports cleanly and the problem only shows up several steps
later, which is exactly how it cost an hour on TL Wall.

Usage:
    python manage.py verify_firm --org tl-wall
    python manage.py verify_firm --org tl-wall --quiet   # only problems
"""

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Max
from django.utils import timezone

from tracker.models import (
    Organization, OrganizationMembership, Client, TaskType, TaskTypeSet,
    OrgDeploymentToken, DeviceProvisioningMap, Block, AgentDevice,
)

OK, WARN, BAD = 'ok', 'warn', 'bad'

ICON = {OK: '✓', WARN: '⚠', BAD: '✗'}

CANONICAL = [
    'Tax Preparation', 'Tax Planning', 'Tax Research', 'Tax Compliance',
    'Accounting/Bookkeeping', 'Financial Statement Prep', 'Audit/Assurance',
    'Payroll Services', 'Advisory', 'Document Management', 'Research',
    'Email/Communication', 'Meetings', 'Administration', 'Billing/Admin',
    'Training', 'General Client Work', 'Idle', 'Personal/Non-Billable',
]


class Command(BaseCommand):
    help = "Verify a firm's onboarding end to end: config, team, clients, mappings, pairing, pipeline"

    def add_arguments(self, parser):
        parser.add_argument('--org', required=True, help='Organization slug')
        parser.add_argument(
            '--quiet', action='store_true',
            help='Print only checks that are not clean',
        )

    # ── reporting helpers ────────────────────────────────────────────────
    def _line(self, label, state, detail, quiet):
        if quiet and state == OK:
            return
        style = {
            OK: self.style.SUCCESS, WARN: self.style.WARNING, BAD: self.style.ERROR,
        }[state]
        dots = '.' * max(2, 22 - len(label))
        self.stdout.write(f'  {style(ICON[state])} {label} {dots} {detail}')

    def handle(self, *args, **options):
        slug = options['org']
        quiet = options['quiet']

        try:
            org = Organization.objects.get(slug=slug)
        except Organization.DoesNotExist:
            raise CommandError(f'No organization with slug "{slug}".')

        self.stdout.write(f'\n{"=" * 62}')
        self.stdout.write(f'  VERIFY: {org.name}  (slug={org.slug}, id={org.id})')
        self.stdout.write(f'{"=" * 62}\n')

        results = []
        for check in (
            self._check_config,
            self._check_token,
            self._check_team,
            self._check_activation,
            self._check_clients,
            self._check_task_types,
            self._check_mappings,
            self._check_pairing,
            self._check_pipeline,
        ):
            results.extend(check(org, quiet))

        blockers = [r for r in results if r[0] == BAD]
        warnings = [r for r in results if r[0] == WARN]

        self.stdout.write('')
        if blockers:
            self.stdout.write(self.style.ERROR(
                f'  {len(blockers)} blocker(s) — this firm is not ready:'
            ))
            for _, label, fix in blockers:
                self.stdout.write(self.style.ERROR(f'    · {label}: {fix}'))
        if warnings:
            self.stdout.write(self.style.WARNING(f'  {len(warnings)} warning(s):'))
            for _, label, fix in warnings:
                self.stdout.write(self.style.WARNING(f'    · {label}: {fix}'))
        if not blockers and not warnings:
            self.stdout.write(self.style.SUCCESS('  All checks clean.'))
        self.stdout.write('')

        # Non-zero on a blocker so this can gate a script, not just inform a human.
        if blockers:
            raise SystemExit(1)

    # ── checks ───────────────────────────────────────────────────────────
    def _check_config(self, org, quiet):
        """industry_type first: it is the one that fails without saying so."""
        out = []
        industry = (org.industry_type or '').strip()
        if not industry:
            out.append((BAD, 'industry_type', "unset — set it to 'cpa' before importing anything"))
            self._line('industry_type', BAD, 'UNSET', quiet)
        else:
            try:
                from tracker.industry_categories import get_categories_for_industry
                cats = get_categories_for_industry(industry)
            except Exception:
                cats = []
            if not cats:
                out.append((BAD, 'industry_type', f'"{industry}" has no canonical categories — category mapping will silently break'))
                self._line('industry_type', BAD, f'{industry} (no categories!)', quiet)
            else:
                self._line('industry_type', OK, f'{industry} ({len(cats)} categories)', quiet)

        plan = org.plan or 'none'
        if plan == 'none':
            out.append((WARN, 'plan', "still 'none' — staff will hit the billing wall; link Stripe before sending invites"))
            self._line('plan', WARN, "none — billing wall", quiet)
        else:
            self._line('plan', OK, f'{plan} · {org.seat_count or 0} seats', quiet)

        members = OrganizationMembership.objects.filter(organization=org).count()
        seats = org.seat_count or 0
        if seats and members > seats:
            out.append((WARN, 'seats', f'{members} members in {seats} seats — over by {members - seats}'))
            self._line('seats', WARN, f'{members} members / {seats} seats', quiet)
        else:
            self._line('seats', OK, f'{members} members / {seats or "?"} seats', quiet)
        return out

    def _check_token(self, org, quiet):
        tok = OrgDeploymentToken.objects.filter(
            organization=org, is_active=True
        ).order_by('-id').first()
        if not tok:
            self._line('deployment token', BAD, 'none', quiet)
            return [(BAD, 'deployment token', 'none active — re-run provision_firm with --generate-token')]
        if not tok.is_valid:
            self._line('deployment token', BAD, f'{tok.token} expired', quiet)
            return [(BAD, 'deployment token', f'{tok.token} is expired — regenerate it')]
        self._line('deployment token', OK, tok.token, quiet)
        return []

    def _check_team(self, org, quiet):
        maps = DeviceProvisioningMap.objects.filter(organization=org)
        total = maps.count()
        members = OrganizationMembership.objects.filter(organization=org).count()
        if total == 0:
            self._line('device maps', WARN, 'none', quiet)
            return [(WARN, 'device maps', 'no DeviceProvisioningMap rows — auto-pair cannot match; every machine falls back to a manual code')]
        by_status = dict(
            maps.values_list('status').annotate(n=Count('id')).values_list('status', 'n')
        )
        detail = ' · '.join(f'{k}={v}' for k, v in sorted(by_status.items())) or f'{total}'
        self._line('device maps', OK, f'{total} ({detail})', quiet)

        out = []
        if total < members:
            out.append((WARN, 'device maps', f'{total} maps for {members} members — someone will pair by hand'))
        return out

    def _check_activation(self, org, quiet):
        """Same rungs as the activation roster, so the CLI and the UI agree."""
        members = list(
            OrganizationMembership.objects.filter(organization=org).select_related('user')
        )
        if not members:
            self._line('activation', BAD, 'no members', quiet)
            return [(BAD, 'activation', 'no members — run provision_firm --team first')]

        user_ids = [m.user_id for m in members]
        cutoff = timezone.now() - timedelta(days=7)
        with_device = set(
            AgentDevice.objects.filter(user_id__in=user_ids)
            .values_list('user_id', flat=True)
        )
        recent = set(
            Block.objects.filter(user_id__in=user_ids, org=org, start__gte=cutoff)
            .values_list('user_id', flat=True)
        )

        never = sum(1 for m in members if m.user.last_login is None)
        flowing = sum(1 for m in members if m.user_id in recent)
        paired = sum(1 for m in members if m.user_id in with_device and m.user_id not in recent)
        signed_in = len(members) - never - flowing - paired

        self._line(
            'activation', OK if flowing == len(members) else WARN,
            f'{flowing}/{len(members)} capturing · {paired} paired · {signed_in} signed in · {never} never signed in',
            quiet,
        )
        out = []
        if never:
            out.append((WARN, 'activation', f'{never} member(s) have never signed in — provision_firm --org {org.slug} --send-invites'))
        return out

    def _check_clients(self, org, quiet):
        """Clients with no aliases are the CCH-import gap in a number.

        Alias derivation runs automatically on QuickBooks and Xero imports but
        not on every path, and a client with no aliases is close to unmatchable
        from a window title. Counting them beats remembering to ask.
        """
        qs = Client.objects.filter(org=org, is_active=True)
        total = qs.count()
        if total == 0:
            self._line('clients', BAD, 'none', quiet)
            return [(BAD, 'clients', 'no active clients — run provision_firm --clients')]

        no_alias = sum(1 for aliases in qs.values_list('aliases', flat=True) if not aliases)
        pct = (no_alias / total * 100) if total else 0
        state = OK if pct < 5 else (WARN if pct < 40 else BAD)
        self._line('clients', state, f'{total} active · {no_alias} without aliases ({pct:.0f}%)', quiet)

        if state != OK:
            return [(state, 'client aliases',
                     f'{no_alias} of {total} clients have no aliases — attribution will be weak. '
                     f'Run: derive_aliases --org-id {org.id}')]
        return []

    def _check_task_types(self, org, quiet):
        tts = TaskType.objects.filter(org=org)
        total = tts.count()
        if total == 0:
            self._line('task types', BAD, 'none', quiet)
            return [(BAD, 'task types', 'none — run provision_firm --task-types')]
        default_set = TaskTypeSet.objects.filter(org=org, is_default=True).first()
        if not default_set:
            self._line('task types', WARN, f'{total}, no default set', quiet)
            return [(WARN, 'task types', 'no default TaskTypeSet — the firm has no vocabulary attached')]
        in_set = default_set.members.count()
        self._line('task types', OK, f'{total} · {in_set} in "{default_set.name}"', quiet)
        return []

    def _check_mappings(self, org, quiet):
        """The bridge. Without it AI categories never reach billing codes."""
        try:
            from tracker.services.task_type_resolver import resolve_task_type_for_category
        except Exception as e:
            self._line('category mappings', BAD, f'resolver import failed: {e}', quiet)
            return [(BAD, 'category mappings', f'could not import the resolver: {e}')]

        missing = []
        for cat in CANONICAL:
            try:
                if not resolve_task_type_for_category(org, cat):
                    missing.append(cat)
            except Exception:
                missing.append(cat)

        if missing:
            self._line('category mappings', BAD, f'{len(CANONICAL) - len(missing)}/{len(CANONICAL)} resolve', quiet)
            shown = ', '.join(missing[:4]) + (f' +{len(missing) - 4} more' if len(missing) > 4 else '')
            return [(BAD, 'category mappings',
                     f'{len(missing)} unmapped ({shown}) — add them and re-run provision_firm --category-mappings')]
        self._line('category mappings', OK, f'{len(CANONICAL)}/{len(CANONICAL)} resolve', quiet)
        return []

    def _check_pairing(self, org, quiet):
        """Auto-pair progress, reconciled against machines that are really live.

        DeviceProvisioningMap.status only ever records the AUTO-pair path, so
        anyone who paired with a manual code leaves their row sitting at
        'pending' forever. Reporting that number alone says "0 paired" for a
        firm whose staff are visibly sending time, which is worse than saying
        nothing. Count real devices too and name the difference.
        """
        maps = DeviceProvisioningMap.objects.filter(organization=org)
        total = maps.count()
        if not total:
            return []

        auto = maps.filter(status='paired').count()
        failed = maps.filter(status='failed').count()

        # Devices that actually exist for this firm's members, however they got here.
        member_ids = OrganizationMembership.objects.filter(
            organization=org
        ).values_list('user_id', flat=True)
        live = AgentDevice.objects.filter(
            user_id__in=list(member_ids)
        ).values('user_id').distinct().count()

        detail = f'{auto}/{total} auto-paired · {live} member(s) with a live device'
        if failed:
            detail += f' · {failed} failed'

        state = OK if (auto == total or live >= total) else (BAD if failed else WARN)
        self._line('pairing', state, detail, quiet)

        out = []
        if failed:
            out.append((BAD, 'pairing', f'{failed} device(s) failed to pair — check hostname case against the team CSV'))
        elif auto == 0 and live > 0:
            out.append((WARN, 'pairing',
                        f'{live} member(s) are sending time but no map row says "paired" — '
                        f'they paired by manual code, so auto-pair is not being exercised. '
                        f'Worth checking hostnames match the team CSV before the next rollout'))
        elif auto < total and live < total:
            out.append((WARN, 'pairing', f'{total - max(auto, live)} device(s) not paired yet — normal before the GPO script runs'))
        return out

    def _check_pipeline(self, org, quiet):
        """Are classifications actually reaching the firm's billing codes?"""
        cutoff = timezone.now() - timedelta(days=7)
        recent = Block.objects.filter(org=org, start__gte=cutoff)
        total = recent.count()
        if total == 0:
            last = Block.objects.filter(org=org).aggregate(last=Max('start'))['last']
            detail = f'nothing in 7 days (last: {last:%Y-%m-%d})' if last else 'no blocks yet'
            self._line('pipeline', WARN, detail, quiet)
            return [(WARN, 'pipeline', detail + ' — expected before go-live, a problem after')]

        categorized = recent.filter(is_categorized=True)
        cat_total = categorized.count()
        null_tt = categorized.filter(task_type__isnull=True).count()
        pct = (null_tt / cat_total * 100) if cat_total else 0
        state = OK if pct <= 10 else BAD
        self._line('pipeline', state, f'{total} blocks/7d · {pct:.0f}% missing task_type', quiet)

        if state != OK:
            return [(BAD, 'pipeline',
                     f'{null_tt}/{cat_total} categorized blocks have no task_type ({pct:.0f}%) — '
                     f'a canonical category is missing from the mapping CSV')]
        return []
