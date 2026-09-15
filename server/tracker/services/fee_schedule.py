"""
tracker/services/fee_schedule.py

Where a fee is remembered, as opposed to where it is applied.

A fee used to be written only onto the engagements that happened to be open
when someone typed it, which broke in both directions: a schedule handed over
during onboarding had no jobs to land on and evaporated, and a fee typed in
March was gone by April because next month's engagement is a new row that
derive_budget hands an estimate. One shared entry point so every path — the fee
box on a client's row in Fees, the editor and the CSV upload on Economics, the
management command, and provisioning through it — records the same thing in the
same place, at the same client x job-type grain.
"""
from __future__ import annotations

from decimal import Decimal


def record_fee(org, client_id, etype, hours, *, fee=None, user=None,
               set_in="Settings"):
    """Upsert this firm's price for one client x kind of work.

    Hours is what's stored, because an engagement budget is hours and keeping
    the conversion in one direction means a later change to the firm's rate
    cannot silently re-price history. `fee` is kept alongside it only so a row
    can say what was actually quoted.
    """
    from tracker.models_engagements import FeeScheduleEntry

    entry, _ = FeeScheduleEntry.objects.update_or_create(
        org=org, client_id=client_id, engagement_type=etype,
        defaults={
            "budget_hours": Decimal(str(round(float(hours), 2))),
            "fee_quoted": (Decimal(str(round(float(fee), 2)))
                           if fee not in (None, "") else None),
            "set_by": user if (user is not None and getattr(user, "is_authenticated", False)) else None,
            "set_in": (set_in or "")[:40],
        },
    )
    return entry
