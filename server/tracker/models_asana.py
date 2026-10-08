"""
Asana — what a firm's Asana says about which project time belongs to.

Read-only. Asana is where an agency runs its projects, but it is not where its
projects come FROM: More Than Cars' projects arrive from QuickBooks Time, so an
Asana project is LINKED to a TimeTracker project, never made into one. A second
mirror would put every project in every picker twice.

Two kinds of evidence:

  * a browser tab's address carries the Asana project's id, so a linked
    project names itself (AsanaProjectLink);
  * the Asana desktop app's window is only ever titled "Asana", so there the
    evidence is what the person did in Asana at the time: a comment, an edit,
    a completion, each stamped with who and when (AsanaActivity).
"""
from django.conf import settings
from django.db import models


class AsanaProjectLink(models.Model):
    """One Asana project, and the TimeTracker project it is (if known)."""
    LINK_SOURCES = [
        ('field', 'Linked by its QB Time field in Asana'),
        ('name', 'Matched by name'),
        ('client', 'Client named, project not'),
        ('ignored', 'Not a client (by hand)'),
        ('manual', 'Linked by hand'),
    ]

    integration = models.ForeignKey(
        'tracker.Integration', on_delete=models.CASCADE, related_name='asana_projects')
    asana_gid = models.CharField(max_length=64)
    asana_name = models.CharField(max_length=500, blank=True, default='')
    archived = models.BooleanField(default=False)

    project = models.ForeignKey(
        'tracker.Project', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='asana_links')
    link_source = models.CharField(max_length=16, blank=True, default='', choices=LINK_SOURCES)
    # The client, when the name says whose work it is but no project of that
    # client fits ("Tom Gill: KBB Buy Back June Event"). Asana time then gets
    # the client and asks only for the project. Set with `project` too.
    client = models.ForeignKey(
        'tracker.Client', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='asana_links')

    # What Asana itself says about whose project this is, when the firm uses
    # it: the project's team ("Tom Gill Buick GMC"), and a project custom
    # field named Client / Customer / Account. Each names a client more
    # reliably than the project's name does (see matching.py).
    asana_team = models.CharField(max_length=255, blank=True, default='')
    client_hint = models.CharField(max_length=255, blank=True, default='')
    # A project custom field naming the QuickBooks Time project ("QB Time
    # Project": its id or its name). Names are typed twice by hand and drift
    # ("Deal Maker" / "Dealmaker"); this is the shared key that makes the
    # link exact. Outranks every name rule; only a hand link outranks it.
    qbt_ref = models.CharField(max_length=255, blank=True, default='')

    # Tasks modified after this have not had their activity read yet.
    activity_cursor = models.DateTimeField(null=True, blank=True)
    last_seen_in_source = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['integration', 'asana_gid']]

    def __str__(self):
        return f'Asana {self.asana_name or self.asana_gid} → {self.project_id or "unlinked"}'


class AsanaActivity(models.Model):
    """Something a person did on an Asana task, and when — one Asana story."""
    integration = models.ForeignKey(
        'tracker.Integration', on_delete=models.CASCADE, related_name='asana_activity')
    story_gid = models.CharField(max_length=64)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='asana_activity')
    at = models.DateTimeField()
    asana_project_gid = models.CharField(max_length=64, blank=True, default='')
    project = models.ForeignKey('tracker.Project', on_delete=models.SET_NULL,
                                null=True, blank=True, related_name='asana_activity')
    client = models.ForeignKey('tracker.Client', on_delete=models.SET_NULL,
                               null=True, blank=True, related_name='asana_activity')
    task_gid = models.CharField(max_length=64, blank=True, default='')
    task_name = models.CharField(max_length=500, blank=True, default='')
    kind = models.CharField(max_length=64, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['integration', 'story_gid']]
        indexes = [models.Index(fields=['user', 'at'])]

    def __str__(self):
        return f'{self.user_id} {self.kind} {self.task_name!r} @ {self.at:%Y-%m-%d %H:%M}'


class AsanaNameMap(models.Model):
    """'DeNooyer' in an Asana project's name means Robert DeNooyer Chevrolet —
    one choice an operator makes once, applied to every project that starts
    with it (the onboarding link report). `client` empty + `ignore` marks a
    name that is not a client at all ("ASOTU CON", internal work).

    Deliberately NOT a Client alias: aliases match window titles, and "Tom
    Gill" chosen for Buick GMC must not start pulling Tom Gill Chevrolet's
    windows to the wrong client. This only reads Asana project names.
    """
    integration = models.ForeignKey('tracker.Integration', on_delete=models.CASCADE,
                                    related_name='asana_name_maps')
    prefix = models.CharField(max_length=255)          # canonical (matching.canon)
    label = models.CharField(max_length=255, blank=True, default='')   # as the firm wrote it
    client = models.ForeignKey('tracker.Client', on_delete=models.CASCADE,
                               null=True, blank=True, related_name='asana_name_maps')
    ignore = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['integration', 'prefix']]

    def __str__(self):
        return f'{self.label or self.prefix} -> {"(not a client)" if self.ignore else self.client_id}'
