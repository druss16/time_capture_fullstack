"""
Sync the support knowledge base from Notion.

Lives at: tracker/management/commands/sync_notion_kb.py
(same place as seed_support_docs.py — tracker's own management/commands,
NOT under tracker/support/, since tracker.support isn't a registered app)

Walks a parent Notion page recursively. Every page that has actual content
(a "leaf" — or any page with text blocks) becomes one SupportDoc set via
ingest_doc(). Section pages that only contain sub-pages are traversed but
not themselves ingested.

Setup (one time):
    pip install notion-client>=2.2.1     # add to requirements.txt too
    export NOTION_API_KEY=ntn_...        # Docker env + Render env
    # Share the parent page with the integration in Notion (••• → Connections)

Run it whenever you've edited docs in Notion:
    docker compose exec api python manage.py sync_notion_kb --page <PAGE_ID>

Or hard-code DEFAULT_PARENT_PAGE_ID below and just run:
    docker compose exec api python manage.py sync_notion_kb

Idempotent: ingest_doc() clears each doc's old chunks before re-inserting,
and --prune removes docs whose source slug is no longer in Notion.
"""
import os
import re

from django.core.management.base import BaseCommand, CommandError
from tracker.support.embeddings import ingest_doc
from tracker.models import SupportDoc


# Optional: paste your "TimeTracker Help" parent page ID here so you can run
# the command with no arguments. Leave as "" to require --page.
DEFAULT_PARENT_PAGE_ID = ""


def slugify(title: str) -> str:
    """Turn a page title into a stable source slug, e.g. 'Daily Review' -> 'daily-review'."""
    s = title.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "untitled"


def _rich_text_to_plain(rich) -> str:
    return "".join(rt.get("plain_text", "") for rt in (rich or []))


def block_to_markdown(client, block: dict, depth: int = 0) -> str:
    """
    Convert one Notion block (and its children) to markdown text.
    Handles the common block types used in help docs.
    """
    btype = block.get("type")
    data = block.get(btype, {}) if btype else {}
    indent = "  " * depth
    out = []

    text = _rich_text_to_plain(data.get("rich_text")) if isinstance(data, dict) else ""

    if btype == "heading_1":
        out.append(f"# {text}")
    elif btype == "heading_2":
        out.append(f"## {text}")
    elif btype == "heading_3":
        out.append(f"### {text}")
    elif btype == "paragraph":
        if text.strip():
            out.append(text)
    elif btype == "bulleted_list_item":
        out.append(f"{indent}- {text}")
    elif btype == "numbered_list_item":
        out.append(f"{indent}1. {text}")
    elif btype == "to_do":
        checked = "x" if data.get("checked") else " "
        out.append(f"{indent}- [{checked}] {text}")
    elif btype == "quote":
        out.append(f"> {text}")
    elif btype == "callout":
        out.append(f"> {text}")
    elif btype == "code":
        lang = data.get("language", "")
        out.append(f"```{lang}\n{text}\n```")
    elif btype == "toggle":
        if text.strip():
            out.append(text)
    elif btype == "divider":
        out.append("---")
    # child_page is handled by the tree walk, not here.

    # Recurse into children (e.g. nested list items, toggle contents).
    if block.get("has_children") and btype != "child_page":
        children = _get_block_children(client, block["id"])
        for child in children:
            child_md = block_to_markdown(client, child, depth + 1)
            if child_md:
                out.append(child_md)

    return "\n".join(out)


def _get_block_children(client, block_id: str) -> list:
    """Fetch all child blocks of a block/page, following pagination."""
    results = []
    cursor = None
    while True:
        resp = client.blocks.children.list(block_id=block_id, start_cursor=cursor)
        results.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return results


def page_title(client, page_id: str) -> str:
    """Read a page's title from its properties."""
    page = client.pages.retrieve(page_id=page_id)
    props = page.get("properties", {})
    # The title property can be named anything; find the one of type 'title'.
    for prop in props.values():
        if prop.get("type") == "title":
            return _rich_text_to_plain(prop.get("title")) or "Untitled"
    return "Untitled"


class Command(BaseCommand):
    help = "Sync the support KB from a Notion parent page (recursive)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--page",
            default=DEFAULT_PARENT_PAGE_ID,
            help="Notion parent page ID (the 'TimeTracker Help' page).",
        )
        parser.add_argument(
            "--prune",
            action="store_true",
            help="Delete SupportDocs whose source slug no longer exists in Notion.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List what would be ingested without writing anything.",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=4.0,
            help="Seconds to wait between docs, to stay under Voyage rate limits.",
        )

    def handle(self, *args, **opts):
        try:
            from notion_client import Client
        except ImportError:
            raise CommandError("notion-client not installed. Run: pip install notion-client")

        api_key = os.environ.get("NOTION_API_KEY")
        if not api_key:
            raise CommandError("NOTION_API_KEY not set in environment.")

        parent_id = (opts["page"] or "").replace("-", "").strip()
        if not parent_id:
            raise CommandError("No parent page ID. Pass --page <ID> or set DEFAULT_PARENT_PAGE_ID.")

        client = Client(auth=api_key)
        dry = opts["dry_run"]

        seen_slugs = set()
        total_docs = 0
        total_chunks = 0

        def walk(page_id: str, trail: str = ""):
            nonlocal total_docs, total_chunks
            title = page_title(client, page_id)
            children = _get_block_children(client, page_id)

            # Separate sub-pages from content blocks.
            subpages = [b for b in children if b.get("type") == "child_page"]
            content_blocks = [b for b in children if b.get("type") != "child_page"]

            # Build this page's own markdown body from its content blocks.
            body_parts = []
            for b in content_blocks:
                md = block_to_markdown(client, b)
                if md:
                    body_parts.append(md)
            body = "\n\n".join(body_parts).strip()

            label = f"{trail}{title}"

            # A page becomes a doc if it has real content. Pure section pages
            # (only sub-pages, no text) are traversed but not ingested.
            if body:
                slug = slugify(title)
                # Disambiguate slug collisions (e.g. two pages both 'Overview').
                base = slug
                i = 2
                while slug in seen_slugs:
                    slug = f"{base}-{i}"
                    i += 1
                seen_slugs.add(slug)

                if dry:
                    self.stdout.write(f"  • {label}  →  source='{slug}'  ({len(body)} chars)")
                else:
                    # Retry on Voyage 429 with exponential backoff, then pace
                    # the next doc with --delay to stay under the rate limit.
                    import time
                    import requests

                    attempt = 0
                    while True:
                        try:
                            n = ingest_doc(title=title, source=slug, markdown=body, org=None)
                            break
                        except requests.exceptions.HTTPError as e:
                            status = getattr(e.response, "status_code", None)
                            if status == 429 and attempt < 5:
                                wait = 2 ** attempt * 5  # 5, 10, 20, 40, 80s
                                self.stdout.write(self.style.WARNING(
                                    f"    … rate limited, waiting {wait}s (attempt {attempt + 1})"
                                ))
                                time.sleep(wait)
                                attempt += 1
                                continue
                            raise
                    total_chunks += n
                    self.stdout.write(self.style.SUCCESS(f"  ✓ {label}  →  {n} chunks  (source='{slug}')"))
                    time.sleep(opts["delay"])
                total_docs += 1
            else:
                self.stdout.write(f"  · {label}  (section page — no content, skipped)")

            # Recurse into sub-pages.
            for sp in subpages:
                walk(sp["id"], trail=f"{label} / ")

        self.stdout.write(f"Walking Notion page {parent_id}…\n")
        walk(parent_id)

        if opts["prune"] and not dry:
            # Remove docs whose slug prefix is no longer present in Notion.
            existing = (
                SupportDoc.objects.filter(org__isnull=True)
                .values_list("source", flat=True)
                .distinct()
            )
            existing_slugs = {s.split("#")[0] for s in existing}
            stale = existing_slugs - seen_slugs
            for slug in stale:
                deleted, _ = SupportDoc.objects.filter(
                    source__startswith=f"{slug}#", org__isnull=True
                ).delete()
                self.stdout.write(self.style.WARNING(f"  ✗ pruned '{slug}' ({deleted} chunks)"))

        if dry:
            self.stdout.write(f"\n[dry run] {total_docs} docs would be ingested.")
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\nSynced {total_docs} docs / {total_chunks} chunks from Notion."
            ))