"""Deployment checks that a machine can make.

Registered from TrackerConfig.ready(), so they run with `manage.py check` and
before every management command.
"""
from datetime import date

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


# How long before a secret lapses we start saying so. Long enough to rotate
# without hurrying, short enough that the warning still means something when
# it appears.
SECRET_EXPIRY_WARN_DAYS = 60

# (label, client-id setting, secret setting, expiry setting, env var to set)
GRAPH_SECRETS = (
    (
        'calendar',
        'MS_GRAPH_CLIENT_ID',
        'MS_GRAPH_CLIENT_SECRET',
        'MS_GRAPH_CLIENT_SECRET_EXPIRES',
    ),
    (
        'mail',
        'MS_GRAPH_MAIL_CLIENT_ID',
        'MS_GRAPH_MAIL_CLIENT_SECRET',
        'MS_GRAPH_MAIL_CLIENT_SECRET_EXPIRES',
    ),
)


@register()
def graph_client_secrets_are_current(app_configs, **kwargs):
    """Warn before an Azure client secret lapses, and after.

    A Graph client secret dies on a fuse set two years earlier, and it dies
    quietly: sync stops for the whole firm and the only evidence is
    invalid_client in worker logs. Nothing in the UI attributes the outage to
    an expired credential, so the failure reads as "the integration broke".

    Not an Error, for the same reason as W001 above: an Error blocks migrate
    and would refuse a deployment that still works. A secret one day from
    expiry is a deployment we very much want to go out.

    Registrations that are not configured say nothing — an install with no
    calendar or no mail is not missing anything.
    """
    today = date.today()
    problems = []

    for label, id_setting, secret_setting, expiry_setting in GRAPH_SECRETS:
        client_id = (getattr(settings, id_setting, '') or '').strip()
        secret = (getattr(settings, secret_setting, '') or '').strip()
        if not (client_id and secret):
            # This registration is not in use here.
            continue

        raw = (getattr(settings, expiry_setting, '') or '').strip()
        if not raw:
            problems.append(Warning(
                f"No expiry date recorded for the Microsoft Graph {label} "
                f"client secret.",
                hint=(
                    f"Read the Expires column in Entra ID -> App registrations "
                    f"-> Certificates & secrets, then set "
                    f"{expiry_setting}=YYYY-MM-DD. Without it nothing warns you "
                    f"before {label} sync stops."
                ),
                id='tracker.W002',
            ))
            continue

        try:
            expires = date.fromisoformat(raw)
        except ValueError:
            # A malformed date must not raise: this check runs before every
            # management command, and a crash here would take down migrate.
            problems.append(Warning(
                f"{expiry_setting} is not a valid date: {raw!r}.",
                hint="Use YYYY-MM-DD, e.g. 2028-09-20.",
                id='tracker.W002',
            ))
            continue

        days_left = (expires - today).days
        if days_left < 0:
            problems.append(Warning(
                f"The Microsoft Graph {label} client secret EXPIRED "
                f"{abs(days_left)} day(s) ago, on {expires}.",
                hint=(
                    f"{label.title()} sync is failing with invalid_client until "
                    f"a new secret is issued. Create one in Entra ID -> "
                    f"Certificates & secrets, update the {secret_setting} env "
                    f"var, and move {expiry_setting} to the new date."
                ),
                id='tracker.W003',
            ))
        elif days_left <= SECRET_EXPIRY_WARN_DAYS:
            problems.append(Warning(
                f"The Microsoft Graph {label} client secret expires in "
                f"{days_left} day(s), on {expires}.",
                hint=(
                    f"Issue a replacement in Entra ID -> Certificates & secrets, "
                    f"update {secret_setting}, and move {expiry_setting} to the "
                    f"new date. When it lapses, {label} sync stops firm-wide."
                ),
                id='tracker.W003',
            ))

    return problems
