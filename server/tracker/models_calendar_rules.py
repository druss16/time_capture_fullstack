"""Direct mapping rules for calendar events → clients."""
from django.db import models


class OrgCalendarRule(models.Model):
    """
    Per-org rule for matching calendar events to clients.
    
    Examples:
    - "Title contains 'BOW-2400' → Acme Corp"
    - "Title contains 'Smith Family' → Smith Family"
    - "External attendee from acmecorp.com → Acme Corp"
    """
    MATCH_TYPE_CHOICES = [
        ('title_contains', 'Title contains text'),
        ('title_pattern', 'Title regex pattern'),
        ('attendee_domain', 'External attendee email domain'),
        ('category_label', 'Outlook category label'),
    ]
    
    org = models.ForeignKey(
        'tracker.Org',
        on_delete=models.CASCADE,
        related_name='calendar_rules',
    )
    target_client = models.ForeignKey(
        'tracker.Client',
        on_delete=models.CASCADE,
        related_name='calendar_rules',
    )
    
    match_type = models.CharField(max_length=30, choices=MATCH_TYPE_CHOICES)
    match_value = models.CharField(max_length=255, help_text="Text to match")
    
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(default=100, help_text="Higher = checked first")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'tracker_org_calendar_rule'
        ordering = ['-priority', 'id']
    
    def __str__(self):
        return f"{self.org} | {self.match_type}={self.match_value!r} → {self.target_client}"