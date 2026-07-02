"""
Suggest client ALIASES to add, mined from user CORRECTIONS.

The onboarding lever: during the first ~30-60 days reviewers correct blocks to the
right client. Each correction where the block's work-surface name (the QB company
file / document name) did NOT already match that client is an alias candidate —
add it and every future block with that name attributes automatically.

Human-in-the-loop and safe: it only SUGGESTS (or adds one you name); a person
already made the call (the correction) and a person approves the alias. It
reuses the matcher's normalize + safety gates, so suggestions are distinctive.

Usage:
  python manage.py suggest_aliases --org 21
  python manage.py suggest_aliases --org 21 --days 60
  python manage.py suggest_aliases --org 21 --add 388 "St Marys_Clinton"   # apply one
"""
import re
from collections import defaultdict
from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from tracker.models import Client, ClassificationAudit, Organization
from tracker.services.classification_service import ClassificationService as C

# strip app/window chrome from a title to get the work "subject" (client name)
_APP_TAIL = re.compile(
    r'\s*[-|]\s*(quickbooks|excel|adobe acrobat|acrobat|word|outlook|microsoft'
    r'|message \(html\)|google|work|search|yahoo|yelp|msn|file explorer|adobe'
    r'|reader|\d+ more).*$', re.I)
_DOC_EXT = re.compile(r'\.(pdf|xlsx?|xlsm|xlsb|docx?|csv|pptx?)\b.*$', re.I)
_PAREN = re.compile(r'\s*\((primary|secondary)\)\s*', re.I)
_GENERIC_SUBJ = {
    'home', 'documents', 'document', 'book1', 'untitled', 'downloads', 'desktop',
    'new tab', 'settings', 'all', 'office', 'inbox', 'save as', 'move or copy',
    'open', 'print', 'preview',
}


def _subject(title: str) -> str:
    t = C._strip_qb_screen_bracket(title or '')
    t = _APP_TAIL.sub('', t)
    t = _DOC_EXT.sub('', t)
    t = _PAREN.sub(' ', t)
    return re.sub(r'\s+', ' ', t).strip()


def _is_distinctive(subj: str) -> bool:
    n = C._normalize_name(subj)
    if not n or n in _GENERIC_SUBJ or len(n) < 5:
        return False
    toks = n.split()
    return len(toks) >= 2 and any(len(t) >= 4 for t in toks)


def build_suggestions(org, since):
    """Return {(client, subject): {'count', 'examples'}} from corrections."""
    clients = {c.id: c for c in Client.objects.filter(org=org)}
    audits = (ClassificationAudit.objects
              .filter(corrected_by_user=True, client_after__isnull=False,
                      created_at__gte=since)
              .select_related('block', 'client_after')
              .order_by('-created_at')[:5000])
    out = defaultdict(lambda: {'count': 0, 'examples': []})
    seen = set()
    for a in audits:
        b = a.block
        if not b or getattr(b, 'org_id', None) != org.id or b.id in seen:
            continue
        seen.add(b.id)
        X = a.client_after
        if X.id not in clients:
            continue
        subj = _subject(b.window_title)
        if not _is_distinctive(subj):
            continue
        names = [X.name] + list(X.aliases or [])
        if any(C._alias_matches_safely(n.lower(), subj.lower()) for n in names):
            continue  # already matches — no alias needed
        if C._normalize_name(subj) in {C._normalize_name(n) for n in names}:
            continue  # already an alias
        rec = out[(X.id, subj)]
        rec['count'] += 1
        if len(rec['examples']) < 3:
            rec['examples'].append(b.id)
    return out, clients


class Command(BaseCommand):
    help = "Suggest client aliases mined from user corrections (safe, read-only)."

    def add_arguments(self, parser):
        parser.add_argument('--org', required=True, help="org id or name")
        parser.add_argument('--days', type=int, default=90)
        parser.add_argument('--add', nargs=2, metavar=('CLIENT_ID', 'ALIAS'),
                            help="apply one suggestion: append ALIAS to CLIENT_ID")

    def _resolve_org(self, val):
        if str(val).isdigit():
            org = Organization.objects.filter(id=int(val)).first()
        else:
            org = Organization.objects.filter(name__icontains=val).first()
        if not org:
            raise CommandError(f"org not found: {val!r}")
        return org

    def handle(self, *args, **opts):
        org = self._resolve_org(opts['org'])

        if opts.get('add'):
            cid, alias = opts['add']
            c = Client.objects.filter(org=org, id=int(cid)).first()
            if not c:
                raise CommandError(f"client {cid} not found in org {org.id}")
            aliases = list(c.aliases or [])
            if alias in aliases:
                self.stdout.write(f"'{alias}' already an alias of {c.name!r}")
                return
            aliases.append(alias)
            c.aliases = aliases
            c.save(update_fields=['aliases'])
            self.stdout.write(self.style.SUCCESS(
                f"added alias '{alias}' -> {c.name!r} (id {c.id})"))
            return

        since = timezone.now() - timedelta(days=opts['days'])
        suggestions, clients = build_suggestions(org, since)
        ranked = sorted(suggestions.items(), key=lambda kv: -kv[1]['count'])
        self.stdout.write(
            f"\n{len(ranked)} alias suggestion(s) from corrections in the last "
            f"{opts['days']}d (org {org.id} {org.name!r}):\n")
        if not ranked:
            self.stdout.write("  (none — nothing to add right now)")
            return
        for (cid, subj), info in ranked:
            self.stdout.write(
                f"  seen {info['count']}x  add alias {subj!r} -> "
                f"{cid} ({clients[cid].name!r})   e.g. blocks {info['examples']}")
        self.stdout.write(
            f"\nTo apply one:\n  python manage.py suggest_aliases --org {org.id} "
            f"--add <client_id> \"<alias>\"")
