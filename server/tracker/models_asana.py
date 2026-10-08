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
        ('name', 'Matched by name'),
        ('client', 'Client named, project not'),
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
