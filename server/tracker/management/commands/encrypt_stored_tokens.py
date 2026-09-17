"""Rewrite plaintext OAuth tokens as ciphertext.

Reports by default; --apply writes. Safe to run repeatedly — a partial run
converts the rows it reached and the next run picks up the rest, because what
counts as "still plaintext" is re-read from the database each time.

Which rows are plaintext can only be answered in SQL: reading through the ORM
runs the decrypt converter, so every value looks like plaintext by the time
Python sees it. The SELECT below therefore goes straight at the column and
matches on the Fernet prefix.
"""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from tracker.crypto_fields import FERNET_PREFIX
from tracker.models import Integration, UserIntegration
from tracker.utils.db_iter import keyset_iter

FIELDS = ('access_token', 'refresh_token')
TABLES = (
    (UserIntegration, 'tracker_userintegration'),
    (Integration, 'tracker_integration'),
)


def _plaintext_ids(table):
    """Ids whose token columns hold something that is not ciphertext."""
    where = ' OR '.join(
        f"({f} IS NOT NULL AND {f} <> '' AND {f} NOT LIKE %s)" for f in FIELDS
    )
    with connection.cursor() as cur:
        cur.execute(f"SELECT id FROM {table} WHERE {where}", [f'{FERNET_PREFIX}%'] * len(FIELDS))
        return [row[0] for row in cur.fetchall()]


class Command(BaseCommand):
    help = "Encrypt OAuth tokens still stored in plaintext."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Write. Without it, this only reports.')

    def handle(self, *args, **options):
        if not getattr(settings, 'TOKEN_ENCRYPTION_KEYS', None):
            self.stderr.write(self.style.ERROR(
                "TOKEN_ENCRYPTION_KEYS is not set, so a rewrite would store plaintext "
                "again. Generate a key with:\n"
                "  python -c 'from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())'"
            ))
            return

        apply = options['apply']
        pending = 0

        for model, table in TABLES:
            ids = _plaintext_ids(table)
            pending += len(ids)
            verb = 'Encrypting' if apply else 'Would encrypt'
            self.stdout.write(f"{model.__name__}: {verb} {len(ids)} row(s) holding plaintext.")

            if not apply:
                continue

            done = 0
            # keyset_iter, not .iterator(): the latter opens a named
            # server-side cursor, which Neon's transaction pooler invalidates
            # as soon as the loop writes — and this loop writes to the rows it
            # is walking.
            for row in keyset_iter(model.objects.filter(id__in=ids)):
                # The values are already decrypted in memory; writing them back
                # sends them through the field, which encrypts.
                model.objects.filter(pk=row.pk).update(
                    **{f: getattr(row, f) for f in FIELDS}
                )
                done += 1
            self.stdout.write(self.style.SUCCESS(f"  {done} row(s) rewritten."))

        if not apply and pending:
            self.stdout.write(self.style.WARNING("\nRe-run with --apply to write."))
        elif not pending:
            self.stdout.write(self.style.SUCCESS("Nothing to do — no plaintext tokens found."))
