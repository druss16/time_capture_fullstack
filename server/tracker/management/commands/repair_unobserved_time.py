"""
Retire time a frozen agent billed to a client.

When the agent's tracking loop stops iterating — machine sleep, thread freeze, a
blocked syscall — nothing is observed and the open dwell is simply left open.
Idle detection is polled inside that same loop, so it cannot fire either. When
the loop comes back, the dwell is closed over the whole gap and chunked into
5-minute events that all look like active time.

TL Wall, 2026-09-16: a dwell opened at 20:01 local on QuickBooks, closed at 08:51
the next morning by a window change. 8h50m of it committed as billable time on
Syracuse Firefighters Assoc Local 280, because QuickBooks happened to be the
foreground window when she went home.

This command finds those stretches in events already stored, marks everything
past the idle-grace window as unobserved, and rebuilds the blocks that were made
from them. tracker/services/unobserved.py holds the rule; the same rule now runs
at ingest and (from v1.8.3) at the agent's own emit site, so this is a one-time
repair for history rather than an ongoing sweep.

Dry-run by default. Invoiced blocks are never touched — they are reported so a
human can decide.

    python manage.py repair_unobserved_time --org 21 --days 90
    python manage.py repair_unobserved_time --org 21 --days 90 --apply
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from tracker.models import Block, BlockAuditLog, RawEvent, Timesheet
from tracker.services.unobserved import (
    ABUT_TOLERANCE,
    GRACE_SECONDS,
    is_gap_chunk,
    mark_unobserved,
)


class Command(BaseCommand):
    help = "Mark and un-bill time the agent's tracking loop never observed."

    def add_arguments(self, parser):
        parser.add_argument("--org", type=int, help="Organization id (default: all)")
        parser.add_argument("--user", type=str, help="Username (default: all)")
        parser.add_argument("--days", type=int, default=60, help="Look-back window")
        parser.add_argument(
            "--min-minutes",
            type=int,
            default=30,
            help="Only report stretches at least this long (default 30)",
        )
        parser.add_argument("--apply", action="store_true", help="Write the changes")

    def handle(self, *args, **opts):
        apply_changes = opts["apply"]
        since = timezone.now() - timedelta(days=opts["days"])
        min_seconds = opts["min_minutes"] * 60

        events = RawEvent.objects.filter(start_ts__gte=since).select_related("user")
        if opts.get("org"):
            events = events.filter(user__memberships__organization_id=opts["org"])
        if opts.get("user"):
            events = events.filter(user__username=opts["user"])

        rows = list(
            events.order_by("user_id", "start_ts").values(
                "id", "user_id", "user__username", "start_ts", "end_ts",
                "window_title", "app_name", "bundle_id", "hostname", "block_id", "ctx",
            )
        )
        self.stdout.write(f"Scanning {len(rows)} events since {since.date()}...")

        stretches = self._find_stretches(rows, min_seconds)
        to_mark, affected_blocks = [], set()
        for st in stretches:
            self._report(st)
            to_mark.extend(st["drop"])
            affected_blocks.update(st["blocks"])

        if not stretches and not self._already_marked_blocks(opts):
            self.stdout.write(self.style.SUCCESS("No unobserved stretches found."))
            return

        # Blocks already holding marked events count too, not just the ones this
        # pass would mark. Marking and rebuilding are separate writes: if a run
        # marks events and then fails (or runs against a server whose compaction
        # has not been deployed yet), re-running must still finish the rebuild.
        affected_blocks |= self._already_marked_blocks(opts)
        affected = Block.all_objects.filter(id__in=affected_blocks, deleted_at__isnull=True)
        invoiced = list(affected.filter(invoiced=True))
        repairable = [b for b in affected if not b.invoiced]

        self.stdout.write("")
        self.stdout.write(
            f"{len(stretches)} stretches · {len(to_mark)} events to mark · "
            f"{len(repairable)} blocks to rebuild"
        )
        if invoiced:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(invoiced)} block(s) already invoiced — left alone: "
                    + ", ".join(str(b.id) for b in invoiced[:20])
                )
            )

        if not apply_changes:
            minutes = sum(b.minutes for b in repairable)
            money = sum((b.billing_amount or Decimal("0")) for b in repairable)
            # Suppressed blocks carry a billing_amount but never reach an
            # invoice, so quoting one total would overstate what is at stake.
            live = [b for b in repairable if b.classification_state != "suppressed"]
            live_min = sum(b.minutes for b in live)
            live_money = sum((b.billing_amount or Decimal("0")) for b in live)
            self.stdout.write("")
            self.stdout.write(f"  by state: {self._states(repairable)}")
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN — would retire {minutes} min ({minutes / 60:.1f}h) total, "
                    f"of which {live_min} min ({live_min / 60:.1f}h) / ${live_money:.2f} "
                    f"is live billable time (${money:.2f} counting suppressed). "
                    f"Re-run with --apply."
                )
            )
            return

        marked, rebuilt, removed, min_delta, money_delta = self._apply(to_mark, repairable)
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Marked {marked} events · rebuilt {rebuilt} blocks · removed {removed} · "
                f"-{min_delta} min ({min_delta / 60:.1f}h) · -${money_delta:.2f}"
            )
        )

    # ------------------------------------------------------------------ scan

    def _find_stretches(self, rows, min_seconds):
        """Contiguous same-title chunk runs, with the past-grace tail isolated."""
        stretches, run = [], None

        def close(run):
            if not run:
                return
            span = (run["end"] - run["start"]).total_seconds()
            if span < min_seconds:
                return
            # Credit the leading grace window; everything after it is the tail
            # the agent has no evidence for.
            cutoff = run["start"] + timedelta(seconds=GRACE_SECONDS)
            drop = [e for e in run["events"] if e["end_ts"] > cutoff and not is_unobserved_row(e)]
            if not drop:
                return
            run["drop"] = drop
            run["blocks"] = {e["block_id"] for e in drop if e["block_id"]}
            stretches.append(run)

        for e in rows:
            if not is_gap_chunk(
                e["app_name"], e["bundle_id"], e["start_ts"], e["end_ts"]
            ):
                close(run)
                run = None
                continue
            same = (
                run
                and e["user_id"] == run["user_id"]
                and e["window_title"] == run["title"]
                and e["start_ts"] - run["end"] <= ABUT_TOLERANCE
            )
            if same:
                run["end"] = e["end_ts"]
                run["events"].append(e)
            else:
                close(run)
                run = {
                    "user_id": e["user_id"],
                    "username": e["user__username"],
                    "title": e["window_title"],
                    "app": e["app_name"],
                    "host": e["hostname"],
                    "start": e["start_ts"],
                    "end": e["end_ts"],
                    "events": [e],
                }
        close(run)
        return stretches

    @staticmethod
    def _already_marked_blocks(opts):
        """Blocks still carrying events a previous pass marked unobserved."""
        qs = RawEvent.objects.filter(ctx__unobserved__isnull=False, block__isnull=False)
        if opts.get("org"):
            qs = qs.filter(user__memberships__organization_id=opts["org"])
        if opts.get("user"):
            qs = qs.filter(user__username=opts["user"])
        return set(qs.values_list("block_id", flat=True))

    @staticmethod
    def _states(blocks):
        counts = {}
        for b in blocks:
            counts[b.classification_state] = counts.get(b.classification_state, 0) + 1
        return ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"

    def _report(self, st):
        span = (st["end"] - st["start"]).total_seconds() / 60
        self.stdout.write(
            f"  {span:7.0f}m {st['username']:10s} "
            f"{timezone.localtime(st['start']):%m-%d %H:%M}"
            f"->{timezone.localtime(st['end']):%m-%d %H:%M} "
            f"{st['app']} · {(st['title'] or '')[:40]!r} "
            f"({len(st['drop'])} events, {len(st['blocks'])} blocks)"
        )

    # ----------------------------------------------------------------- apply

    def _apply(self, to_mark, blocks):
        from tracker.services.compaction import _calculate_minutes_from_events

        marked = 0
        with transaction.atomic():
            by_id = {e["id"]: e for e in to_mark}
            for ev in RawEvent.objects.select_for_update().filter(id__in=by_id):
                row = by_id[ev.id]
                gap = (row["end_ts"] - row["start_ts"]).total_seconds()
                ev.ctx = mark_unobserved(ev.ctx, gap)
                ev.save(update_fields=["ctx"])
                marked += 1

        rebuilt = removed = 0
        min_delta = 0
        money_delta = Decimal("0")
        timesheets = {b.timesheet_id for b in blocks if b.timesheet_id}

        for block in blocks:
            with transaction.atomic():
                locked = Block.all_objects.select_for_update().get(id=block.id)
                old_min = locked.minutes
                old_amt = locked.billing_amount or Decimal("0")
                new_min = _calculate_minutes_from_events(RawEvent.objects.filter(block=locked))

                if new_min == old_min:
                    continue  # already rebuilt by an earlier pass

                if new_min <= 0:
                    locked.deleted_at = timezone.now()
                    locked.save(update_fields=["deleted_at"])
                    removed += 1
                    action = "delete"
                    note = "Every event in this block covered time the agent never observed."
                else:
                    locked.minutes = new_min
                    locked.save(force_update=True)
                    rebuilt += 1
                    action = "update"
                    note = f"Minutes rebuilt from observed events only ({old_min} -> {new_min})."

                if new_min <= 0:
                    # Soft-deleted blocks keep their amount as evidence; the
                    # whole of it stops counting because the row is gone.
                    min_delta += old_min
                    money_delta += old_amt
                else:
                    min_delta += old_min - new_min
                    money_delta += old_amt - (locked.billing_amount or Decimal("0"))

                BlockAuditLog.objects.create(
                    block=locked,
                    action=action,
                    field_name="minutes",
                    old_value=str(old_min),
                    new_value=str(new_min),
                    notes=f"repair_unobserved_time: {note}",
                    snapshot={"old_billing_amount": str(old_amt)},
                )

        # Timesheet.total_hours is denormalized off the confirmed block set, so
        # removing blocks leaves an approved week still claiming hours that no
        # longer exist anywhere. Refresh every week we touched.
        for ts in Timesheet.objects.filter(id__in=timesheets):
            before = ts.total_hours
            ts.recalculate_totals(commit=True)
            if before != ts.total_hours:
                self.stdout.write(
                    f"  timesheet {ts.id} ({ts.week_start}, {ts.status}): "
                    f"{before}h -> {ts.total_hours}h"
                )

        return marked, rebuilt, removed, min_delta, money_delta


def is_unobserved_row(row) -> bool:
    return bool((row.get("ctx") or {}).get("unobserved"))
