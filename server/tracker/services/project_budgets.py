"""
Monthly project budgets: what is in effect, what was spent, what it is worth.

    budget  — ProjectBudget in effect for the month (latest row at or before it)
    actual  — confirmed hours filed to the project that month, counted by the
              same rules Reports and Daily Review use (billing_totals)
    fee     — budget hours × the client's rate, else the firm's default rate

One place for all three so Settings, the picker and the analytics view can
never disagree about "Spring Launch: 26.5 of 20 hours this month".
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.utils import timezone

ZERO = Decimal('0')


def month_start(d: date | None = None) -> date:
    d = d or timezone.localdate()
    return d.replace(day=1)


def next_month(m: date) -> date:
    return (m.replace(day=28) + timedelta(days=4)).replace(day=1)


def parse_month(raw: str | None) -> date:
    """'2026-10' or '2026-10-15' → 2026-10-01; blank → this month."""
    if not raw:
        return month_start()
    return datetime.strptime(raw[:7], '%Y-%m').date()


def budgets_in_effect(org, month: date, project_ids=None) -> dict:
    """project_id -> the ProjectBudget row in effect for `month`."""
    from tracker.models import ProjectBudget
    qs = ProjectBudget.objects.filter(org=org, effective_month__lte=month)
    if project_ids is not None:
        qs = qs.filter(project_id__in=list(project_ids))
    out = {}
    for row in qs.order_by('project_id', '-effective_month'):
        out.setdefault(row.project_id, row)
    return out


def set_monthly_budget(project, hours, *, month: date | None = None,
                       source: str = 'manual', user=None):
    """Budget `hours`/month for `project` from `month` (default: this month) on."""
    from tracker.models import ProjectBudget
    month = month_start(month)
    row, _ = ProjectBudget.objects.update_or_create(
        project=project, effective_month=month,
        defaults={'org_id': project.org_id, 'monthly_hours': Decimal(str(hours)),
                  'source': source, 'set_by': user},
    )
    return row


def apply_source_estimate(project, hours, *, source: str = 'qb_time') -> str:
    """
    Carry an external estimate into the budget — unless a person overrode it.

    A budget someone typed here outranks the source system: they set it on
    purpose, and an hourly sync quietly undoing it would be the worst kind of
    surprise. The source's number is still recorded on its mapping, so nothing
    is lost. Returns 'unchanged', 'kept_manual' or 'applied'.
    """
    current = budgets_in_effect(project.org, month_start(), [project.id]).get(project.id)
    hours = Decimal(str(hours)).quantize(Decimal('0.01'))
    if current and current.source == 'manual':
        return 'kept_manual'
    if current and current.monthly_hours == hours:
        return 'unchanged'
    set_monthly_budget(project, hours, source=source)
    return 'applied'


def fee_rates(org, client_ids, month: date) -> dict:
    """client_id -> hourly fee rate in effect at the end of `month`.

    A firm-wide client rate (BillingRate with no user and no task type) when
    one is set, else the firm's default. One firm rate is the norm for an
    agency; the client rate is the override.
    """
    from tracker.models import BillingRate
    last_day = next_month(month) - timedelta(days=1)
    rates = {}
    for r in (BillingRate.objects
              .filter(org=org, user__isnull=True, task_type__isnull=True,
                      client_id__in=list(client_ids), effective_date__lte=last_day)
              .order_by('client_id', '-effective_date')):
        rates.setdefault(r.client_id, r.rate)
    default = org.billing_rate_default or ZERO
    return {cid: rates.get(cid, default) for cid in client_ids}


def actual_hours(org, month: date, project_ids=None) -> dict:
    """project_id -> confirmed hours filed to it in `month` (all people)."""
    from tracker.services.billing_totals import committed_block_qs
    from tracker.views_reports import _block_minutes

    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(month, datetime.min.time()), tz)
    end = timezone.make_aware(datetime.combine(next_month(month), datetime.min.time()), tz)
    qs = committed_block_qs(org, start, end, can_see_all=True).filter(project__isnull=False)
    if project_ids is not None:
        qs = qs.filter(project_id__in=list(project_ids))
    minutes = defaultdict(int)
    for b in qs:
        minutes[b.project_id] += _block_minutes(b)
    return {pid: (Decimal(m) / 60).quantize(Decimal('0.01')) for pid, m in minutes.items()}


def month_elapsed(month: date, today: date | None = None) -> float:
    """Share of `month` gone: 1.0 for a past month, 0.0 for a future one."""
    today = today or timezone.localdate()
    end = next_month(month)
    if today >= end:
        return 1.0
    if today < month:
        return 0.0
    days = (end - month).days
    return round(((today - month).days + 1) / days, 3)


def month_summary(org, month: date, *, client_ids=None) -> dict:
    """
    Every live project, plus any project with time this month, with its budget,
    actual hours, fee and burn. Rows and per-client totals.
    """
    from tracker.models import Project

    projects = Project.objects.filter(org=org).select_related('client')
    if client_ids is not None:
        projects = projects.filter(client_id__in=list(client_ids))
    projects = list(projects)
    ids = [p.id for p in projects]

    budgets = budgets_in_effect(org, month, ids)
    actuals = actual_hours(org, month, ids)
    rates = fee_rates(org, {p.client_id for p in projects}, month)

    rows = []
    for p in projects:
        b = budgets.get(p.id)
        budget = b.monthly_hours if b and b.monthly_hours > 0 else None
        actual = actuals.get(p.id, ZERO)
        # A closed project only matters in a month it took time.
        if not p.is_active and not actual:
            continue
        rate = rates.get(p.client_id, ZERO)
        rows.append({
            'project_id': p.id,
            'project': p.name,
            'client_id': p.client_id,
            'client': p.client.name,
            'is_active': p.is_active,
            'budget_hours': float(budget) if budget is not None else None,
            'budget_source': b.source if b and budget is not None else None,
            'budget_since': b.effective_month.isoformat() if b and budget is not None else None,
            'actual_hours': float(actual),
            'rate': float(rate),
            'fee': float(budget * rate) if budget is not None else None,
            'burn_pct': round(float(actual / budget) * 100, 1) if budget else None,
        })
    rows.sort(key=lambda r: (r['client'].lower(), r['project'].lower()))

    clients = {}
    for r in rows:
        c = clients.setdefault(r['client_id'], {
            'client_id': r['client_id'], 'client': r['client'], 'budget_hours': 0.0,
            'actual_hours': 0.0, 'fee': 0.0, 'projects': 0, 'unbudgeted_projects': 0,
        })
        c['projects'] += 1
        c['actual_hours'] += r['actual_hours']
        if r['budget_hours'] is None:
            c['unbudgeted_projects'] += 1
        else:
            c['budget_hours'] += r['budget_hours']
            c['fee'] += r['fee']
    for c in clients.values():
        for k in ('budget_hours', 'actual_hours', 'fee'):
            c[k] = round(c[k], 2)

    return {
        'month': month.strftime('%Y-%m'),
        'month_elapsed': month_elapsed(month),
        'rows': rows,
        'clients': sorted(clients.values(), key=lambda c: c['client'].lower()),
    }


# ============================================================================
# Arbitrary windows (Analytics) — budgets prorated by calendar coverage
# ============================================================================

def months_in(start: date, end: date) -> list[date]:
    out, m = [], month_start(start)
    while m <= end:
        out.append(m)
        m = next_month(m)
    return out


def window_budget(org, start: date, end: date, projects) -> dict:
    """
    project_id -> (budget_hours, fee) for [start, end], prorated by calendar days.

    A month budget covers its whole month, so a window holding ten of October's
    thirty-one days holds 10/31 of October's budget. That makes "this month"
    the full monthly budget, "last quarter" three of them, and a rolling
    30-day window an honest blend of the two months it straddles — rather
    than comparing a week of hours against a month of budget. Each month's
    share is priced at the rate in force that month.
    """
    projects = list(projects)
    client_of = {p.id: p.client_id for p in projects}
    hours = defaultdict(lambda: ZERO)
    fees = defaultdict(lambda: ZERO)
    for m in months_in(start, end):
        m_end = next_month(m) - timedelta(days=1)
        covered = (min(end, m_end) - max(start, m)).days + 1
        if covered <= 0:
            continue
        share = Decimal(covered) / Decimal((m_end - m).days + 1)
        rates = fee_rates(org, set(client_of.values()), m)
        for pid, row in budgets_in_effect(org, m, list(client_of)).items():
            if row.monthly_hours > 0:
                h = row.monthly_hours * share
                hours[pid] += h
                fees[pid] += h * rates.get(client_of[pid], ZERO)
    q = Decimal('0.01')
    return {pid: (hours[pid].quantize(q), fees[pid].quantize(q)) for pid in hours}


def window_elapsed(start: date, end: date, today: date | None = None) -> float:
    """Share of the window's days that have happened (1.0 once it is over)."""
    today = today or timezone.localdate()
    total = (end - start).days + 1
    if today >= end:
        return 1.0
    if today < start:
        return 0.0
    return round(((today - start).days + 1) / total, 3)


def window_minutes_by_project_user(org, start: date, end: date, project_ids=None) -> dict:
    """(project_id, user_id) -> confirmed minutes in [start, end]."""
    from tracker.services.billing_totals import committed_block_qs
    from tracker.views_reports import _block_minutes

    tz = timezone.get_current_timezone()
    s = timezone.make_aware(datetime.combine(start, datetime.min.time()), tz)
    e = timezone.make_aware(datetime.combine(end + timedelta(days=1), datetime.min.time()), tz)
    qs = committed_block_qs(org, s, e, can_see_all=True).filter(project__isnull=False)
    if project_ids is not None:
        qs = qs.filter(project_id__in=list(project_ids))
    out = defaultdict(int)
    for b in qs:
        out[(b.project_id, b.user_id)] += _block_minutes(b)
    return dict(out)
