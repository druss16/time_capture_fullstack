"""
Suppress AFK / lock-screen blocks that leaked in as normal captured time.

A locked machine (or screensaver / sign-in screen) is idle — never work,
never billable. Going forward the classifier's Stage 0 suppresses these
(_stage_0_suppress in classification_service.py); this command is the one-time /
periodic cleanup for blocks that already exist (or predate the classifier fix).

Detection mirrors the classifier exactly:
  - app_name or bundle_id in {Lockapp, LockApp.exe, LogonUI, LogonUI.exe}
  - window_title contains "lock screen" / "screensaver" / "screen saver"

Suppressing removes them from the review pile, totals, and billable everywhere
(today_time, reports, and the pending predicate all exclude suppressed).

Dry-run by default. --apply to write. --org-id to scope.

Usage:
  python manage.py suppress_afk_blocks                 # dry-run, all orgs
  python manage.py suppress_afk_blocks --org-id 21     # dry-run, org 21
  python manage.py suppress_afk_blocks --apply         # write, all orgs
  python manage.py suppress_afk_blocks --org-id 21 --apply
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Q, Sum, Count

from tracker.models import Block

# Keep in step with classification_service._stage_0_suppress (AFK sentinels).
AFK_APPS = ['lockapp', 'lockapp.exe', 'logonui', 'logonui.exe']
AFK_TITLE_HINTS = ['lock screen', 'screensaver', 'screen saver']


def _afk_q():
    q = Q()
    for a in AFK_APPS:
        q |= Q(app_name__iexact=a) | Q(bundle_id__iexact=a)
    for h in AFK_TITLE_HINTS:
        q |= Q(window_title__icontains=h)
    return q


class Command(BaseCommand):
    help = "Suppress AFK / lock-screen blocks (idle, never billable)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Write changes (default: dry-run).")
        parser.add_argument("--org-id", type=int, default=None,
                            help="Limit to a single org.")

    def handle(self, *args, **opts):
        apply = opts["apply"]
        org_id = opts["org_id"]

        qs = Block.objects.filter(
            _afk_q(), deleted_at__isnull=True,
        ).exclude(classification_state="suppressed")
        if org_id:
            qs = qs.filter(org_id=org_id)

        agg = qs.aggregate(
            n=Count("id"), minutes=Sum("minutes"), amount=Sum("billing_amount"),
        )
        n = agg["n"] or 0
        minutes = agg["minutes"] or 0
        amount = agg["amount"] or Decimal("0.00")

        self.stdout.write(
            f"AFK/lock-screen blocks to suppress: {n}  |  {minutes} min "
            f"({minutes/60:.1f} h)  |  billable now: {qs.filter(is_billable=True).count()}  "
            f"|  billing_amount to zero: {amount}"
        )
        for row in (qs.values("org_id", "app_name")
                      .annotate(n=Count("id"), minutes=Sum("minutes"))
                      .order_by("-n")[:20]):
            self.stdout.write(
                f"    org {row['org_id']}  {row['app_name']!r}: "
                f"{row['n']} blocks, {row['minutes'] or 0} min"
            )

        if n == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to do."))
            return

        if not apply:
            self.stdout.write(self.style.WARNING(
                "DRY RUN — no changes written. Re-run with --apply to commit."
            ))
            return

        updated = qs.update(
            classification_state="suppressed",
            is_billable=False,
            billing_amount=Decimal("0.00"),
        )
        self.stdout.write(self.style.SUCCESS(
            f"Applied: suppressed {updated} AFK block(s) (is_billable=False, billing_amount=0)."
        ))
