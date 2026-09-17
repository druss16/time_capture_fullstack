"""Encryption at rest for the columns that hold live credentials.

A refresh token is a standing key to someone's mailbox: it survives password
changes and can be exchanged for access tokens until the user revokes it.
Platform-level disk encryption protects those columns against a stolen drive
and nothing else — a database dump, a log of a query result, or a support
export hands over working credentials.

Two properties matter more than the cipher:

  · **Reads tolerate plaintext.** Rows written before this existed are
    returned as they are, so deploying this does not disconnect every
    integration. `manage.py encrypt_stored_tokens --apply` converts them.
  · **A missing key degrades to today's behaviour**, loudly, rather than
    taking every integration offline. Losing mail sync because an
    environment variable did not make it into a deploy would be a worse
    outcome than the plaintext it replaces. The system check in checks.py
    reports the missing key, and the module logs on first use.

Key rotation: TOKEN_ENCRYPTION_KEYS is an ordered, comma-separated list. The
first key encrypts; every key can decrypt. To rotate, prepend the new key,
deploy, run the backfill, then drop the old key on the next deploy.

These columns are no longer queryable by value — Fernet output is not
deterministic, so `filter(access_token=...)` cannot match. Nothing does that,
and nothing should.
"""
import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.db import models

logger = logging.getLogger(__name__)

# Fernet v1 ciphertext is base64 beginning with a 0x80 version byte, which
# always renders as this prefix. It is how a stored value announces itself as
# encrypted, and how legacy plaintext is recognised as plaintext.
FERNET_PREFIX = 'gAAAAA'

_cipher_cache = {}
_warned_no_key = False


def _cipher():
    """MultiFernet over the configured keys, or None when none are set."""
    global _warned_no_key

    keys = tuple(getattr(settings, 'TOKEN_ENCRYPTION_KEYS', ()) or ())
    if not keys:
        if not _warned_no_key:
            _warned_no_key = True
            logger.warning(
                "[CRYPTO] TOKEN_ENCRYPTION_KEYS is not set — OAuth tokens are "
                "being stored in plaintext. Generate one with: python -c "
                "'from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())'"
            )
        return None

    if keys not in _cipher_cache:
        _cipher_cache[keys] = MultiFernet([Fernet(k.encode() if isinstance(k, str) else k) for k in keys])
    return _cipher_cache[keys]


def encrypt(value):
    """Ciphertext for a non-empty string; the value unchanged without a key."""
    if not value:
        return value
    if isinstance(value, str) and value.startswith(FERNET_PREFIX):
        return value          # already encrypted; never double-wrap
    cipher = _cipher()
    if cipher is None:
        return value
    return cipher.encrypt(value.encode()).decode()


def decrypt(value):
    """Plaintext for ciphertext, and legacy plaintext returned untouched."""
    if not value or not isinstance(value, str) or not value.startswith(FERNET_PREFIX):
        return value          # written before encryption existed
    cipher = _cipher()
    if cipher is None:
        logger.error(
            "[CRYPTO] Encrypted token found but no key is configured. The "
            "integration will behave as disconnected until TOKEN_ENCRYPTION_KEYS "
            "is restored — do NOT let it reconnect and overwrite the row."
        )
        return ''
    try:
        return cipher.decrypt(value.encode()).decode()
    except InvalidToken:
        # Wrong key, or the row was written under a key since dropped.
        logger.error(
            "[CRYPTO] Stored token could not be decrypted with any configured "
            "key. Treating as empty so the integration reconnects rather than "
            "sending ciphertext as a bearer token."
        )
        return ''


class EncryptedTextField(models.TextField):
    """TextField whose value is encrypted on the way to the database.

    Same column type as TextField, so switching an existing field to this is
    a state-only migration with no data change.
    """

    def from_db_value(self, value, expression, connection):
        return decrypt(value)

    def get_prep_value(self, value):
        return encrypt(super().get_prep_value(value))
