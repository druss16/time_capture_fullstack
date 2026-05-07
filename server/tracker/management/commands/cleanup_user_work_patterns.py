"""
Wipe contaminated learned patterns from UserWorkPattern.

Same contamination categories as the agent's LearnedRules cleanup:
  - IDE source-file titles ("main.py - Sublime Text")
  - Email titles without strong client name match
  - Pure stop-word patterns ("tax inbox outlook")
  - Generic browser/app chrome titles
  - Patterns with too few hits to be reliable

Usage:
  python manage.py cleanup_user_work_patterns --dry-run
  python manage.py cleanup_user_work_patterns --apply
  python manage.py cleanup_user_work_patterns --apply --user wayne
  python manage.py cleanup_user_work_patterns --apply --org "TL Wall Accounting"
"""

import re
import logging
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from tracker.models import UserWorkPattern, Organization

logger = logging.getLogger(__name__)
User = get_user_model()


# Same as ai_client_switcher.py — IDE markers and source-file extensions
IDE_MARKERS = [
    '- sublime text', '- visual studio code', 'visual studio code -',
    '- pycharm', '- intellij', '- webstorm', '- vim', '- neovim',
    '- notepad++', '- atom', '- emacs',
]
SOURCE_EXTENSIONS = [
    '.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs', '.java',
    '.cpp', '.c', '.h', '.rb', '.php', '.html', '.css', '.json',
    '.yaml', '.yml', '.md', '.sql',
]

# Stop-words that, when ALL tokens of a pattern are in this set, indicate
# the pattern is too generic to be a reliable signal
STOP_WORDS = {
    'and', 'the', 'for', 'inc', 'llc', 'ltd', 'corp', 'co', 'group',
    'tax', 'firm', 'cpas', 'cpa', 'associates', 'partners', 'services',
    'inbox', 'outlook', 'mail', 'message', 'email',
    'document', 'file', 'folder', 'window', 'tab', 'page',
}

# Generic chrome titles that should never have been learned
GENERIC_CHROME_TITLES = {
    'google chrome', 'microsoft edge', 'firefox', 'brave browser',
    'safari', 'opera', 'new tab', 'untitled',
    'microsoft outlook', 'microsoft word', 'microsoft excel',
    'microsoft powerpoint', 'microsoft teams',
    'sublime text', 'visual studio code', 'pycharm',
    'terminal', 'iterm', 'command prompt', 'powershell',
    'finder', 'file explorer',
}


def is_contaminated(pattern_key: str, pattern_type: str = '') -> tuple:
    """
    Returns (is_contaminated, reason). Reason is a short string for logging.
    """
    if not pattern_key or not pattern_key.strip():
        return True, 'empty'

    key_low = pattern_key.lower().strip()

    # Generic chrome titles
    if key_low in GENERIC_CHROME_TITLES:
        return True, 'generic_chrome'

    # IDE source files
    # IDE source files
    for marker in IDE_MARKERS:
        if marker in key_low:
            return True, 'ide_marker'

    # Source-code extensions — must appear at end of a "filename-ish" token,
    # not as a substring of a domain like ".gov" or ".com"
    # Match: "main.py" "app.tsx" "config.json - Sublime Text"
    # Don't match: "ny.gov" ".com/personal"
    for ext in SOURCE_EXTENSIONS:
        # Pattern: alphanumeric/underscore, then the extension, then either
        # end-of-string, whitespace, or punctuation that's NOT a path separator
        pat = r'\b\w+' + re.escape(ext) + r'(?:$|[\s\-,)\]"\'])'
        if re.search(pat, key_low):
            return True, 'source_extension'

    # Pure stop-words / tokens too short
    tokens = set(re.split(r'[\s_\-.,|:/\\&()]+', key_low))
    tokens.discard('')
    if not tokens:
        return True, 'no_tokens'
    if all(t in STOP_WORDS or len(t) < 3 for t in tokens):
        return True, 'stop_words_only'

    return False, ''


class Command(BaseCommand):
    help = 'Cleanup contaminated UserWorkPattern entries'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without deleting',
        )
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Actually delete the patterns',
        )
        parser.add_argument(
            '--user',
            type=str,
            help='Limit to a single user (username)',
        )
        parser.add_argument(
            '--org',
            type=str,
            help='Limit to a single org (name)',
        )
        parser.add_argument(
            '--min-hits',
            type=int,
            default=0,
            help='Also delete patterns with total_predictions < N (default: 3)',
        )

    def handle(self, *args, **opts):
        if not opts['dry_run'] and not opts['apply']:
            self.stderr.write(
                self.style.ERROR(
                    'Must specify --dry-run or --apply'
                )
            )
            return

        qs = UserWorkPattern.objects.all()

        if opts['user']:
            try:
                user = User.objects.get(username=opts['user'])
                qs = qs.filter(user=user)
                self.stdout.write(f'Filter: user={user.username}')
            except User.DoesNotExist:
                self.stderr.write(self.style.ERROR(f'User {opts["user"]!r} not found'))
                return

        if opts['org']:
            try:
                org = Organization.objects.get(name=opts['org'])
                qs = qs.filter(org=org)
                self.stdout.write(f'Filter: org={org.name}')
            except Organization.DoesNotExist:
                self.stderr.write(self.style.ERROR(f'Org {opts["org"]!r} not found'))
                return

        total = qs.count()
        self.stdout.write(f'Examining {total} patterns...')

        contaminated = []
        low_hit = []
        clean = 0

        min_hits = opts['min_hits']

        for pat in qs.iterator(chunk_size=500):
            is_bad, reason = is_contaminated(pat.pattern_key, pat.pattern_type)
            if is_bad:
                contaminated.append((pat, reason))
                continue

            if pat.total_predictions < min_hits:
                low_hit.append(pat)
                continue

            clean += 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Clean: {clean}'))
        self.stdout.write(self.style.WARNING(f'Contaminated: {len(contaminated)}'))
        self.stdout.write(self.style.WARNING(f'Low-hit (<{min_hits}): {len(low_hit)}'))

        # Breakdown by reason
        if contaminated:
            from collections import Counter
            by_reason = Counter(r for _, r in contaminated)
            self.stdout.write('')
            self.stdout.write('Contamination breakdown:')
            for reason, count in by_reason.most_common():
                self.stdout.write(f'  {reason}: {count}')

        # Show first 20 examples
        if contaminated and opts['dry_run']:
            self.stdout.write('')
            self.stdout.write('Sample contaminated patterns:')
            for pat, reason in contaminated[:20]:
                key_short = pat.pattern_key[:60]
                self.stdout.write(
                    f'  [{reason}] {pat.user.username} | '
                    f'{pat.pattern_type} | "{key_short}" | '
                    f'hits={pat.total_predictions}'
                )

        if opts['apply']:
            ids_to_delete = [p.pk for p, _ in contaminated] + [p.pk for p in low_hit]
            deleted, _ = UserWorkPattern.objects.filter(pk__in=ids_to_delete).delete()
            self.stdout.write('')
            self.stdout.write(
                self.style.SUCCESS(f'✅ Deleted {deleted} patterns')
            )
        else:
            total_to_delete = len(contaminated) + len(low_hit)
            self.stdout.write('')
            self.stdout.write(
                self.style.WARNING(
                    f'Would delete {total_to_delete} patterns. '
                    'Re-run with --apply to actually delete.'
                )
            )