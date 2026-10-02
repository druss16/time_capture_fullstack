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
    processes = models.JSONField(default=dict, blank=True)
    local_sessions = models.JSONField(default=dict, blank=True)

    received_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['device', 'bucket_start'],
                                    name='uniq_agent_presence_device_hour'),
        ]
        indexes = [models.Index(fields=['org', 'bucket_start'])]
