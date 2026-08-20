"""
Safe large-queryset iteration under a transaction pooler.

`QuerySet.iterator()` opens a NAMED server-side cursor. Our Postgres is Neon
behind its connection pooler (PgBouncer-style transaction pooling), where that
cursor is invalidated the moment the loop does a write — or, as with
`derive_engagements`, sometimes on the very first fetch:

    psycopg2.errors.InvalidCursorName:
        cursor "_django_curs_..." does not exist

The codebase's existing answer is "materialize to a list" (see
management/commands/migrate_block_categories.py and
backfill_business_return_routing.py), which is fine for a few thousand rows and
not fine for a nightly sweep over every org's blocks.

`keyset_chunks` gets both: no server-side cursor, and bounded memory. It pages
by primary key, so it's also safe when the loop WRITES to the rows it is
walking — each page re-queries with `pk > last_seen`, and rows that drop out of
the filter simply don't come back.

Because it pages by pk, it imposes `order_by("pk")`. Callers that were relying
on a different order need to sort the page themselves or not use this.
"""
from __future__ import annotations

from typing import Iterator

from django.db.models import QuerySet

DEFAULT_CHUNK = 1000


def keyset_chunks(
    qs: QuerySet, chunk_size: int = DEFAULT_CHUNK, descending: bool = False
) -> Iterator[list]:
    """Yield successive lists of objects, paging by primary key.

    `descending=True` walks newest-pk-first, for callers that keep only the
    first N rows they see and want those to be the most recent ones.
    """
    last_pk = None
    while True:
        page = qs.order_by("-pk" if descending else "pk")
        if last_pk is not None:
            page = page.filter(pk__lt=last_pk) if descending else page.filter(pk__gt=last_pk)
        rows = list(page[:chunk_size])
        if not rows:
            return
        yield rows
        last_pk = rows[-1].pk
        if len(rows) < chunk_size:
            return


def keyset_iter(
    qs: QuerySet, chunk_size: int = DEFAULT_CHUNK, descending: bool = False
) -> Iterator:
    """Flat row-by-row version of keyset_chunks — a drop-in for .iterator()."""
    for rows in keyset_chunks(qs, chunk_size, descending=descending):
        yield from rows
