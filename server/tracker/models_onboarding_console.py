"""
The Onboarding Console — MavOps' own tool for onboarding firms at scale.

Before this, onboarding was three Notion playbooks printed on paper, ticked off
by hand, with every provisioning step pasted into a `docker compose exec` shell
connected to the PRODUCTION database. Most of the checkboxes recorded facts the
database already knew ("first device paired", "19/19 mappings resolve").

So a firm's onboarding is now a row here, the playbook is data
(tracker/onboarding_playbook.py), and each step is one of:

  auto    — evaluated live from the firm's own records; nobody ticks it
  action  — a button in the console that runs the real provisioning code
  manual  — a human thing (a call, a decision, the firm's IT doing a GPO),
            ticked with a date and a note

Deliberately NOT part of MavOps admin. It has its own permission group
(OPERATOR_GROUP), its own API prefix (/api/onboard/) and an audit log of
every write, so a future hire can run onboardings without being handed View-as
and the cross-org MavOps console.
"""
import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

OPERATOR_GROUP = 'Onboarding Operator'

# Auth groups that are permission roles, not firms. tracker/signals.py turns
# every other group a user joins into an Organization of the same name, so a
# role group must be listed here or granting it creates a phantom firm.
ROLE_GROUPS = frozenset({OPERATOR_GROUP})

INSTALL_PATH_CHOICES = [
    ('windows_gpo', 'Windows — GPO logon script'),
    ('windows_hand', 'Windows — installed by hand'),
    ('mac_hand', 'Mac — installed by hand'),
    ('mac_mdm', 'Mac — MDM (Jamf / Kandji / Mosyle / Intune)'),
]


class OnboardingProject(models.Model):
    STATUS_CHOICES = [
        ('active', 'Onboarding'),
        ('paused', 'Paused'),
        ('live', 'Live'),          # Status → Active in the old Notion tracker
        ('cancelled', 'Cancelled'),
    ]

    organization = models.OneToOneField(
        'tracker.Organization', on_delete=models.CASCADE,
        related_name='onboarding_project',
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='active')
    install_path = models.CharField(
        max_length=16, choices=INSTALL_PATH_CHOICES, default='windows_gpo',
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='onboarding_projects_owned',
    )

    # The handful of facts the playbooks collected on paper.
    contacts = models.JSONField(
        default=dict, blank=True,
        help_text='{"it_admin": {...}, "billing": {...}, "qbo_admin": {...}, ...}',
    )
    billing_model = models.CharField(
        max_length=16, blank=True, default='',
        help_text='hourly / retainer / mix — agencies only',
    )
    coupon_months = models.PositiveSmallIntegerField(default=0)
    target_go_live = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    went_live_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Onboarding({self.organization.name}, {self.status})'

    @property
    def vertical(self):
        return self.organization.industry_type


class OnboardingStepState(models.Model):
    """A human's mark on one playbook step.

    Only manual steps are ticked here. Auto steps are never stored as done —
    they are re-evaluated every time, so a firm that un-pairs or loses a
    mapping goes back to red instead of keeping a stale tick. Any step may be
    marked not-applicable, with a note saying why.
    """
    project = models.ForeignKey(
        OnboardingProject, on_delete=models.CASCADE, related_name='step_states',
    )
    step_key = models.CharField(max_length=64)
    done = models.BooleanField(default=False)
    not_applicable = models.BooleanField(default=False)
    note = models.TextField(blank=True, default='')
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+',
    )
    updated_at = models.DateTimeField(auto_now=True)
    done_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('project', 'step_key')]


class OnboardingAuditEvent(models.Model):
    """Every write the console makes, by whom. The console acts on production
    records for a firm that is not the operator's own, so the trail is the
    point — not a nicety."""
    project = models.ForeignKey(
        OnboardingProject, on_delete=models.CASCADE, null=True, blank=True,
        related_name='audit_events',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+',
    )
    action = models.CharField(max_length=64)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']


INTAKE_TTL = timedelta(days=30)


class OnboardingIntake(models.Model):
    """The customer-facing intake form, reached by a single unguessable link.

    Replaces emailing the firm a doc and chasing spreadsheets. Only a SHA-256
    of the token is stored; the raw link is shown to the operator once, and a
    lost link is replaced rather than recovered. The link grants exactly one
    thing — reading and writing this firm's intake answers — and stops working
    once submitted or expired.
    """
    project = models.ForeignKey(
        OnboardingProject, on_delete=models.CASCADE, related_name='intakes',
    )
    token_hash = models.CharField(max_length=64, unique=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    last_saved_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    @staticmethod
    def hash_token(raw):
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    @classmethod
    def mint(cls, project):
        """Retire any open link for the project and return (intake, raw_token)."""
        now = timezone.now()
        cls.objects.filter(project=project, revoked_at__isnull=True,
                           submitted_at__isnull=True).update(revoked_at=now)
        # Carry the previous answers forward so re-issuing a link never makes
        # the firm start over.
        prev = cls.objects.filter(project=project).order_by('-created_at').first()
        raw = secrets.token_urlsafe(32)
        intake = cls.objects.create(
            project=project,
            token_hash=cls.hash_token(raw),
            payload=(prev.payload if prev else {}),
            expires_at=now + INTAKE_TTL,
        )
        return intake, raw

    @property
    def is_open(self):
        return (self.revoked_at is None and self.submitted_at is None
                and self.expires_at > timezone.now())


CONNECT_LINK_TTL = timedelta(days=7)
CONNECT_PROVIDERS = ('quickbooks', 'qb_time')


class ConnectLink(models.Model):
    """A single unguessable link that lets a firm's QuickBooks admin connect
    QuickBooks Online and/or QuickBooks Time without a TimeTracker login.

    Intuit only lets someone with admin rights on the company approve a
    connection, and at most firms that is a bookkeeper who will never use
    TimeTracker. This link is the whole credential for one thing: starting the
    Intuit OAuth flow for THIS firm. It cannot sign anyone in, read time, or
    touch another firm. Only a SHA-256 of the token is stored.

    The OAuth state minted for each provider is kept here so the shared
    callbacks (views_integrations.quickbooks_callback,
    qb_time/views.qb_time_callback) can tell a link-started grant from one
    started in Settings and finish it accordingly.
    """
    organization = models.ForeignKey('tracker.Organization', on_delete=models.CASCADE,
                                     related_name='connect_links')
    project = models.ForeignKey(OnboardingProject, on_delete=models.SET_NULL,
                                null=True, blank=True, related_name='connect_links')
    token_hash = models.CharField(max_length=64, unique=True)
    providers = models.JSONField(default=list)
    sent_to = models.EmailField(blank=True, default='')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    qbo_state = models.CharField(max_length=64, blank=True, default='', db_index=True)
    qbt_state = models.CharField(max_length=64, blank=True, default='', db_index=True)
    qbo_connected_at = models.DateTimeField(null=True, blank=True)
    qbt_connected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    @staticmethod
    def hash_token(raw):
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()

    @classmethod
    def mint(cls, organization, providers, *, project=None, created_by=None, sent_to=''):
        """Retire the firm's open links and return (link, raw_token)."""
        now = timezone.now()
        cls.objects.filter(organization=organization, revoked_at__isnull=True).update(revoked_at=now)
        raw = secrets.token_urlsafe(32)
        link = cls.objects.create(
            organization=organization, project=project, token_hash=cls.hash_token(raw),
            providers=[p for p in CONNECT_PROVIDERS if p in (providers or [])],
            created_by=created_by, sent_to=(sent_to or '')[:254],
            expires_at=now + CONNECT_LINK_TTL,
        )
        return link, raw

    @property
    def is_open(self):
        return self.revoked_at is None and self.expires_at > timezone.now()
