"""
The email outbox: every transactional email is recorded here before SendGrid
sees it, and MavOps decides from MavOps Admin whether it goes out.

Tables of their own with no foreign keys onto User or Organization: those rows
are read and deleted on hot paths, and during the minutes between Render
deploying this code and the migration running, Django's delete collector would
query a table that does not exist yet. The ids here are plain integers.
"""
from django.db import models


class EmailSendSettings(models.Model):
    """
    The one global switch for outgoing email. A single row (pk=1).

    mode
      hold     — record every email, send none (the default, and what a missing
                 row or an unreadable table means)
      redirect — send every email to `redirect_to` instead of its recipient,
                 so a real inbox shows exactly what the customer would get
      live     — send normally
    live_types are email types that send for real even while the mode is hold
    or redirect — how types go live one at a time once they have been seen.
    """
    MODE_CHOICES = [
        ('hold', 'Hold everything'),
        ('redirect', 'Send everything to me instead'),
        ('live', 'Live — send to real recipients'),
    ]
    mode = models.CharField(max_length=16, choices=MODE_CHOICES, default='hold')
    redirect_to = models.EmailField(blank=True, default='')
    live_types = models.JSONField(default=list, blank=True)
    updated_by_id = models.IntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tracker_emailsendsettings'

    def __str__(self):
        return f'email mode={self.mode} live_types={self.live_types}'


class OutboundEmail(models.Model):
    STATUS_CHOICES = [
        ('held', 'Held'),
        ('sent', 'Sent'),
        ('redirected', 'Sent to test inbox'),
        ('failed', 'Failed'),
        ('discarded', 'Discarded'),
    ]
    email_type = models.CharField(max_length=40, db_index=True)
    to_email = models.CharField(max_length=254)
    from_email = models.CharField(max_length=254)
    from_name = models.CharField(max_length=120, blank=True, default='')
    reply_to = models.CharField(max_length=254, blank=True, default='')
    subject = models.CharField(max_length=500)
    html_content = models.TextField()
    plain_content = models.TextField(blank=True, default='')
    categories = models.JSONField(default=list, blank=True)

    # Resolved from the recipient at queue time, for display and filtering only.
    org_id = models.IntegerField(null=True, blank=True, db_index=True)
    org_name = models.CharField(max_length=255, blank=True, default='')

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='held', db_index=True)
    # Where it actually went: the recipient, or the test inbox for a redirect.
    sent_to = models.CharField(max_length=254, blank=True, default='')
    sent_at = models.DateTimeField(null=True, blank=True)
    sendgrid_status = models.IntegerField(null=True, blank=True)
    error = models.TextField(blank=True, default='')
    acted_by_id = models.IntegerField(null=True, blank=True)

    # Same recipient + subject + body inside one time window. Unique, so the
    # second of two schedulers firing the same task 30ms apart cannot insert.
    dedupe_key = models.CharField(max_length=80, null=True, blank=True, unique=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'tracker_outboundemail'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.email_type} to {self.to_email}: {self.status}'


class OrgEmailSetting(models.Model):
    """
    One company's own email mode, overriding the global EmailSendSettings.mode.
    No row means the company follows the global mode. Email types switched live
    globally still send for every company — they are the vetted ones (password
    reset), and a firm that wants no notifications still needs those.

    org_id is a plain integer, not an FK: see the module docstring.
    """
    MODE_CHOICES = EmailSendSettings.MODE_CHOICES
    org_id = models.IntegerField(unique=True)
    mode = models.CharField(max_length=16, choices=MODE_CHOICES)
    updated_by_id = models.IntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tracker_orgemailsetting'

    def __str__(self):
        return f'org {self.org_id} email mode={self.mode}'
