"""
AI agent work — time an AI agent (Claude Code, Codex, ...) spent working on
the firm's behalf, recorded beside human time and NEVER inside it.

WHY A SEPARATE TABLE
--------------------
Every timesheet, billing total, report and analytics tile reads `Block`. Agent
minutes are not human minutes: agents run in parallel, run unattended, and
cost tokens rather than salary. Folding them into `Block` would inflate
utilization and anything quoted by the hour. Keeping them here means no
existing number can pick them up by accident — agent work only appears where
something reads this table on purpose (today: /api/agent-work/ only).

The desktop agent cannot see this work at all: it tracks the foreground window
and keyboard/mouse input, and a background agent has neither. So agents report
themselves — a Claude Code hook (windows_agent/agent_hooks/) posts a SNAPSHOT
of the session on every turn end. Snapshots are idempotent: the row is keyed by
(org, agent_kind, external_session_id) and each post overwrites the totals, so
a lost or repeated post never double-counts.

The person who ran the agent is `user` — the supervisor. Their own time at the
terminal is already captured as ordinary human time by the desktop agent.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class AgentWorkSession(models.Model):
    AGENT_KINDS = [
        ('claude_code', 'Claude Code'),
        ('codex', 'Codex'),
        ('other', 'Other'),
    ]
    CLIENT_SOURCES = [
        ('explicit', 'Named by the project'),   # .timetracker-client / env var
        ('none', 'Unassigned'),
    ]

    org = models.ForeignKey(
        'tracker.Organization', on_delete=models.CASCADE,
        related_name='agent_work_sessions')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='agent_work_sessions',
        help_text="The person who ran the agent.")
    device = models.ForeignKey(
        'tracker.AgentDevice', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='agent_work_sessions')

    agent_kind = models.CharField(max_length=32, choices=AGENT_KINDS, default='other')
    external_session_id = models.CharField(max_length=128)
    model_name = models.CharField(max_length=64, blank=True, default='')
    # How this session became known. Only 'hook' (the agent reported itself)
    # exists today; the desktop agent will add what it can see from outside.
    SOURCES = [
        ('hook', 'Agent reported itself'),
        ('local_log', "Desktop agent read the agent's local log"),
        ('synthetic_input', 'Desktop agent saw synthetic input'),
        ('process', 'Desktop agent saw the process running'),
    ]
    source = models.CharField(max_length=16, choices=SOURCES, default='hook')

    started_at = models.DateTimeField()
    last_activity_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)

    # Seconds the agent was actually working: the gaps inside a turn, from a
    # human's prompt to the agent's last action. Time spent waiting on the
    # human (between turns, or on an approval) is excluded — that is the
    # human's time, and the desktop agent already has it.
    active_seconds = models.PositiveIntegerField(default=0)
    turns = models.PositiveIntegerField(default=0)

    input_tokens = models.BigIntegerField(default=0)
    output_tokens = models.BigIntegerField(default=0)
    cache_read_tokens = models.BigIntegerField(default=0)
    cache_write_tokens = models.BigIntegerField(default=0)

    project_path = models.CharField(max_length=512, blank=True, default='')
    client = models.ForeignKey(
        'tracker.Client', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='agent_work_sessions')
    # What the project said its client was, verbatim — kept even when it did
    # not resolve, so an admin can see why a session is unassigned.
    client_hint = models.CharField(max_length=255, blank=True, default='')
    client_source = models.CharField(max_length=16, choices=CLIENT_SOURCES, default='none')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['org', 'agent_kind', 'external_session_id'],
                name='uniq_agent_work_session'),
        ]
        indexes = [
            models.Index(fields=['org', 'started_at']),
        ]
        ordering = ['-started_at']

    def __str__(self):
        return f"AgentWorkSession({self.agent_kind} {self.external_session_id[:8]}, {self.active_seconds}s)"


class AgentPresenceSample(models.Model):
    """One device-hour of agent-presence MEASUREMENT (desktop agent's
    agent_presence.py). Counts only — no titles, keystrokes or log contents.

    Read by nothing but the agent_presence_summary command. It exists to size
    the problem before anything changes attribution: how often the screen is
    driven by synthetic input the tracker currently books as a person, how
    often windows change with nobody at the keyboard, and which agent programs
    run where.
    """
    org = models.ForeignKey(
        'tracker.Organization', on_delete=models.CASCADE,
        related_name='agent_presence_samples')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='agent_presence_samples')
    device = models.ForeignKey(
        'tracker.AgentDevice', on_delete=models.CASCADE,
        related_name='agent_presence_samples')
    bucket_start = models.DateTimeField()
    app_version = models.CharField(max_length=32, blank=True, default='')

    seconds_observed = models.PositiveIntegerField(default=0)
    idle_seconds = models.PositiveIntegerField(default=0)
    remote_session = models.BooleanField(default=False)
    # ok | no_permission | error | off — whether click counts can be trusted
    input_monitor = models.CharField(max_length=16, blank=True, default='')

    clicks_real = models.PositiveIntegerField(default=0)
    clicks_synthetic = models.PositiveIntegerField(default=0)
    synthetic_by = models.JSONField(default=dict, blank=True)
    idle_changes = models.PositiveIntegerField(default=0)
    idle_changes_by_app = models.JSONField(default=dict, blank=True)
    # macOS: seconds the tracker's idle clock called active while the
    # hardware-only clock saw no physical input — mis-booked time, directly.
    unattended_active_seconds = models.PositiveIntegerField(default=0)
    unattended_active_by_app = models.JSONField(default=dict, blank=True)
    # The same seconds by cause. Only 'agent_busy' and 'unexplained' are
    # candidate agent time; remote_control / universal_control / sidecar /
    # tablet_driver / keep_awake are known false positives.
    unattended_by_cause = models.JSONField(default=dict, blank=True)
    processes = models.JSONField(default=dict, blank=True)
    local_sessions = models.JSONField(default=dict, blank=True)

    received_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['device', 'bucket_start'],
                                    name='uniq_agent_presence_device_hour'),
        ]
        indexes = [models.Index(fields=['org', 'bucket_start'])]


class AgentPresenceSwitch(models.Model):
    """Remote off switch for the desktop agent's agent-presence MEASUREMENT.
    Never affects time tracking.

    One row per scope: org_id and device_pk both null = everyone; org_id set =
    one firm; device_pk set = one machine. Most specific row wins; no row =
    on. The AGENT_PRESENCE_DISABLED env var turns it off for everyone with no
    database at all. Flip with `manage.py agent_presence_switch`.

    Plain integers, not foreign keys, on purpose: nothing that deletes a user,
    firm or device ever touches this table, so it can never be the reason a
    delete fails while a migration is pending.
    """
    org_id = models.IntegerField(null=True, blank=True, db_index=True)
    device_pk = models.IntegerField(null=True, blank=True, db_index=True)
    enabled = models.BooleanField(default=True)
    note = models.CharField(max_length=255, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['org_id', 'device_pk'],
                                    name='uniq_agent_presence_switch_scope'),
        ]

    def __str__(self):
        scope = (f"device {self.device_pk}" if self.device_pk else
                 f"org {self.org_id}" if self.org_id else "everyone")
        return f"agent presence {'ON' if self.enabled else 'OFF'} for {scope}"


class FirmFeatureFlag(models.Model):
    """A per-firm switch for features that ship dark. No row = off.

    First user: 'ai_agent_report' — Reports → AI agent activity, which stays
    hidden until MavOps turns it on for a firm (MavOps Admin → Agent Presence).
    Plain integer org_id, not a foreign key, so no delete ever touches it and a
    pending migration can never break anything: readers treat any error as off.
    """
    org_id = models.IntegerField(db_index=True)
    key = models.CharField(max_length=64)
    enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['org_id', 'key'], name='uniq_firm_feature_flag'),
        ]

    def __str__(self):
        return f"{self.key} {'ON' if self.enabled else 'OFF'} for org {self.org_id}"


class AgentActivityReview(models.Model):
    """An owner's answer on one 'time to review' row of the AI agent activity
    report: was that hour a person or an agent?

    RECORD ONLY. Nothing reads this to change time — it never touches a block,
    timesheet or report total. It exists so the owner's list shrinks as they
    answer, and so the answers can grade the measurement's accuracy.
    Plain integer ids (no foreign keys), same reasoning as FirmFeatureFlag.
    """
    VERDICTS = [('human', 'It was me / a person'), ('agent', 'It was an agent')]

    org_id = models.IntegerField(db_index=True)
    sample_id = models.IntegerField(unique=True)   # AgentPresenceSample pk
    verdict = models.CharField(max_length=8, choices=VERDICTS)
    reviewed_by_id = models.IntegerField(null=True, blank=True)
    reviewed_at = models.DateTimeField(auto_now=True)
