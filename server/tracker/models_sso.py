"""
Sign in with Microsoft / Google — the link from a provider identity to a User.

The account system stays ours. A provider only proves who is at the keyboard;
it never creates a User. The first sign-in finds the invited User by verified
email and records a SocialLogin; every sign-in after that matches on the
provider's immutable subject, never the email again. That is the defence
against "nOAuth": Microsoft's `email` claim is editable by any tenant admin,
so an attacker's tenant can put a victim's address in it. Matching by subject
after first link means a later email change on either side moves nothing.

See views_sso.py for the flow.
"""
from django.conf import settings
from django.db import models


class SocialLogin(models.Model):
    PROVIDERS = (
        ('microsoft', 'Microsoft'),
        ('google', 'Google'),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name='social_logins')
    provider = models.CharField(max_length=20, choices=PROVIDERS)
    # Microsoft: "<tid>:<oid>" (oid is only unique within a tenant).
    # Google: the `sub` claim.
    subject = models.CharField(max_length=255)
    email_at_link = models.EmailField(blank=True, default='',
                                      help_text='The email the provider reported when this link was made')
    created_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    # One-time hand-off from the API callback to the SPA. The callback mints a
    # nonce here and signs (id, nonce) into a short code; /exchange/ clears it
    # in a single conditional UPDATE, so a code is good exactly once.
    ticket_nonce = models.CharField(max_length=64, blank=True, default='')
    ticket_issued_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('provider', 'subject')]

    def __str__(self):
        return f'{self.provider}:{self.email_at_link or self.subject} -> {self.user_id}'
