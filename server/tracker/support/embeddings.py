"""
Embedding + retrieval helpers for the support KB.

Embeddings: Anthropic doesn't serve an embeddings endpoint, so use Voyage
(Anthropic's recommended partner) or OpenAI. Swap the one function below.
Both return 1536-dim with the models named here; if you pick a model with a
different dim, update VectorField(dimensions=...) on SupportDoc.
"""
import os
import time
import requests

from tracker.models import SupportDoc


EMBED_MODEL = "voyage-3-lite"  # or "text-embedding-3-small" on OpenAI

# Voyage's free tier rate-limits requests-per-minute. Retry on 429 with
# exponential backoff so bulk ingest doesn't fall over.
_MAX_RETRIES = 5
_BASE_DELAY = 2.0  # seconds; doubles each retry (2, 4, 8, 16, 32)


def embed_text(text: str) -> list[float]:
    """
    Return an embedding vector for a string. Retries on 429 (rate limit)
    with exponential backoff. Raises on any other error or after max retries.
    """
    for attempt in range(_MAX_RETRIES):
        resp = requests.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {os.environ['VOYAGE_API_KEY']}"},
            json={"model": EMBED_MODEL, "input": [text]},
            timeout=30,
        )
        if resp.status_code == 429:
            if attempt == _MAX_RETRIES - 1:
                resp.raise_for_status()  # give up, surface the 429
            delay = _BASE_DELAY * (2 ** attempt)
            time.sleep(delay)
            continue
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]


def chunk_markdown(text: str, max_chars: int = 1200) -> list[str]:
    """
    Naive but effective: split on headings, then pack paragraphs up to max_chars.
    Good enough for a focused product KB; revisit if docs get large.
    """
    blocks, current = [], ""
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if para.startswith("#") or len(current) + len(para) > max_chars:
            if current:
                blocks.append(current.strip())
            current = para
        else:
            current += "\n\n" + para
    if current:
        blocks.append(current.strip())
    return blocks


def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Embed multiple strings in ONE request. Voyage accepts up to 128 inputs
    per call, so a whole doc's chunks usually fit in a single request —
    far fewer calls than embedding one chunk at a time, which avoids the
    rate limit. Retries on 429 with backoff, same as embed_text.
    """
    if not texts:
        return []
    for attempt in range(_MAX_RETRIES):
        resp = requests.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {os.environ['VOYAGE_API_KEY']}"},
            json={"model": EMBED_MODEL, "input": texts},
            timeout=60,
        )
        if resp.status_code == 429:
            if attempt == _MAX_RETRIES - 1:
                resp.raise_for_status()
            time.sleep(_BASE_DELAY * (2 ** attempt))
            continue
        resp.raise_for_status()
        data = resp.json()["data"]
        # Voyage returns results in input order, but sort by index to be safe.
        data.sort(key=lambda d: d["index"])
        return [d["embedding"] for d in data]


def ingest_doc(title: str, source: str, markdown: str, org=None):
    """
    Chunk a markdown doc, embed all chunks in one batch, upsert SupportDoc rows.

    `org` is an Organization instance (or None for a global doc).
    Idempotent: clears existing chunks for this source+org before re-inserting.
    """
    SupportDoc.objects.filter(source__startswith=f"{source}#", org=org).delete()
    chunks = chunk_markdown(markdown)
    embeddings = embed_batch(chunks)  # one request for the whole doc
    rows = [
        SupportDoc(
            title=title,
            source=f"{source}#chunk{i}",
            content=chunk,
            embedding=emb,
            org=org,
        )
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
    ]
    SupportDoc.objects.bulk_create(rows)
    return len(rows)


def retrieve(query: str, org_id: int, k: int = 5) -> list[SupportDoc]:
    """
    Cosine-distance nearest chunks. Includes this org's docs plus global
    docs (org is null). `org_id` is the Organization pk.
    """
    from pgvector.django import CosineDistance
    from django.db.models import Q

    qvec = embed_text(query)
    return list(
        SupportDoc.objects
        .filter(is_active=True)
        .filter(Q(org_id=org_id) | Q(org__isnull=True))
        .annotate(distance=CosineDistance("embedding", qvec))
        .order_by("distance")[:k]
    )