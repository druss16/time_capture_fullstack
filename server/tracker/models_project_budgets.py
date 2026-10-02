"""
Monthly hour budgets for projects — an agency's retainer, per project.

An agency prices each client's monthly fee as rate × the hours it estimates
each project will take that month (More Than Cars: $165 × estimated hours).
So the budget is HOURS PER MONTH, per project, and it repeats every month
until someone changes it.

Effective-dated rather than one row per month: a row says "from this month on,
this project gets N hours a month". The budget for any month is the latest row
at or before it. That keeps the number nobody re-types — May's 20 hours is
still June's 20 hours — and keeps history honest: changing the budget in
August leaves March's budget as it was, so last quarter's burn does not
silently re-score against today's number.

Hours, not money, is what's stored. The fee is derived at read time from the
client's rate (or the firm's default), so a rate change applies forward from
when it is dated instead of rewriting every budget.
"""
from django.conf import settings
from django.db import models


class ProjectBudget(models.Model):
    SOURCE_CHOICES = [
        ('manual', 'Set by the firm'),
        ('qb_time', 'QuickBooks Time estimate'),
        ('csv', 'Imported from a file'),
    ]

    org = models.ForeignKey(
        'tracker.Organization', on_delete=models.CASCADE, related_name='project_budgets',
    )
    project = models.ForeignKey(
        'tracker.Project', on_delete=models.CASCADE, related_name='monthly_budgets',
    )
    effective_month = models.DateField(
        help_text='First day of the month this budget starts applying.',
    )
    monthly_hours = models.DecimalField(
        max_digits=7, decimal_places=2,
        help_text='Budgeted hours per month from effective_month on. 0 ends the budget.',
    )
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default='manual')
    set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='project_budget_changes',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tracker_projectbudget'
        ordering = ['project_id', '-effective_month']
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'effective_month'], name='uniq_project_budget_month',
            ),
        ]
        indexes = [models.Index(fields=['org', 'effective_month'])]

    def __str__(self):
        return f'{self.project.name}: {self.monthly_hours}h/mo from {self.effective_month:%Y-%m}'


class CurrentProject(models.Model):
    """
    The project a person said they are on, from the desktop ticker.

    Applies to that person's blocks of the SAME client from `started_at` until
    they switch (a new row) or it goes stale (services/projects.CURRENT_PROJECT_TTL).
    A file named by the firm's convention still outranks it: that names the
    project of one specific piece of work, this states a general intention.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='current_project',
    )
    project = models.ForeignKey(
        'tracker.Project', on_delete=models.CASCADE, related_name='current_for',
    )
    started_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tracker_currentproject'

    def __str__(self):
        return f'{self.user_id} on {self.project_id} since {self.started_at:%Y-%m-%d %H:%M}'


class OrgFeatureFlag(models.Model):
    """
    Per-org switches MavOps staff flip in MavOps Admin — not firm settings.

    A table rather than a column on Organization on purpose: Organization is
    loaded on every authenticated request, so a new column there 500s ALL of
    prod in the minutes between the code deploying and the migration running.
    A missing table can only break the few reads of it, and those read through
    services/feature_flags.feature_enabled, which answers False on any error.
    """
    KEYS = [
        ('project_switch', 'Switch Project in the desktop ticker'),
    ]
    org = models.ForeignKey(
        'tracker.Organization', on_delete=models.CASCADE, related_name='feature_flags',
    )
    key = models.CharField(max_length=40, choices=KEYS)
    enabled = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tracker_orgfeatureflag'
        constraints = [
            models.UniqueConstraint(fields=['org', 'key'], name='uniq_org_feature_flag'),
        ]

    def __str__(self):
        return f'{self.org_id}:{self.key}={self.enabled}'
