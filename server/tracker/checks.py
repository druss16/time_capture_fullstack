"""Deployment checks that a machine can make.

Registered from TrackerConfig.ready(), so they run with `manage.py check` and
before every management command.
"""
from django.conf import settings
from django.core.checks import Warning, register


@register()
def oauth_tokens_are_encrypted(app_configs, **kwargs):
    """Warn when live credentials are being stored in plaintext.

    Not an Error: raising one would block `migrate` and refuse to start a
    deployment that works today, which is a worse failure than the warning.
    """
    if getattr(settings, 'TOKEN_ENCRYPTION_KEYS', None):
        return []

    return [Warning(
        "OAuth access and refresh tokens are being stored in plaintext.",
        hint=(
            "Set TOKEN_ENCRYPTION_KEYS (comma-separated, first key encrypts). "
            "Generate one with: python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'. Then run "
            "manage.py encrypt_stored_tokens --apply to convert existing rows."
        ),
        id='tracker.W001',
    )]
