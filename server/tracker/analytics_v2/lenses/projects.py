"""
Projects — an agency's retainer, project by project: budgeted hours against
the hours actually spent, what that budget earns, and what it really cost.

The agency question this answers: "which projects are quietly eating the
retainer?" A client paying $3,300 a month for a 20-hour project that takes 26.5
hours is being served at $125 an hour, not the $165 the fee was priced at —
and nothing on an invoice ever says so, because the invoice is the same every
month. So the lead number is the EFFECTIVE RATE: fee ÷ hours actually used.

THE PERIOD
----------
Budgets are monthly; the dashboard's period is anything. Budgets are prorated
by calendar coverage (services/project_budgets.window_budget): "this month" is
the full monthly budget, "last quarter" three of them, a rolling 30 days an
honest blend of the months it straddles. Pace compares burn with the share of
the period already gone, so a project 47% through its budget a week into the
month reads as running hot, not as fine.

FLAGS — objective only, never a target someone made up:
  over budget    used more hours than budgeted for the period
  ahead of pace  burn more than 15 points ahead of the calendar while the
                 period is still running (a finished period is simply over or not)
  no budget      time was filed to it, but it has no monthly budget

COST is owner-only. Tile ids `labor_cost` / `gross_margin` and the `cost`,
`margin`, `margin_pct` columns are exactly the keys cost_visibility strips, so
a non-owner sees hours, fees and effective rates with every cost figure gone.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from tracker.analytics_v2.cost_rates import cost_rate_map, default_cost_rate
from tracker.models import Project
from tracker.services import project_budgets as pb

from ..types import DataTablePayload, KPITile, MetricState, MetricValue, Section
from .base import Lens, register_lens
from .helpers import column

# How far burn may run ahead of the calendar before it is worth a flag. Not a
# target: a project is allowed to front-load, and this only names the ones far
# enough ahead that the month cannot plausibly even out.
AHEAD_OF_PACE_PTS = 15.0

_FLAG_LABEL = {
    'over_budget': 'Over budget',
    'ahead_of_pace': 'Ahead of pace',
    'no_budget': 'No budget',
}


def plan_end(time):
    """
    The last day of the period the budget is judged over.

    "This month" resolves to the 1st through TODAY — right for counting hours,
    wrong for a budget: on the 2nd it would prorate a 20-hour project to 1.3
    hours and call the month 100% gone. For a period still running, the budget
    is the whole period's and "gone" means days so far. A finished or rolling
    window is judged on exactly the days it covers.
    """
    from datetime import timedelta
    expr = getattr(time, 'relative_expr', None)
    if expr == 'this_week':
        return time.start + timedelta(days=6)
    if expr == 'this_month':
        return pb.next_month(time.start) - timedelta(days=1)
    if expr == 'this_quarter':
        return pb.next_month(pb.next_month(pb.next_month(time.start))) - timedelta(days=1)
    return time.end


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def project_columns() -> list[dict]:
    return [
        column('client', 'Client', 'text'),
        column('label', 'Project', 'text'),
        column('flag_label', 'Flag', 'text', sortable=False),
        column('budget_hours', 'Budget hrs', 'hours_1dp',
               tooltip='Monthly budget, prorated to the selected period.'),
        column('hours', 'Used hrs', 'hours_1dp',
               tooltip='Confirmed hours filed to the project in the period, everyone.'),
        column('burn_pct', 'Burn', 'percent_0dp', tooltip='Used ÷ budget.'),
        column('pace_pts', 'Pace', 'decimal_1dp',
               tooltip='Burn minus the share of the period already gone, in points. '
                       'Positive is running hot.'),
        column('fee', 'Fee', 'currency_0dp', tooltip='Budget hours × the client\'s rate.'),
        column('effective_rate', 'Effective $/hr', 'currency_0dp',
               tooltip='Fee earned so far ÷ hours actually used. The fee accrues evenly '
                       'over the period, so mid-month this compares like with like. Below '
                       'the list rate means the project is taking more time than it was priced for.'),
        column('cost', 'Labor cost', 'currency_0dp',
               tooltip='Used hours × each person\'s cost rate.'),
        column('margin', 'Margin', 'currency_0dp', tooltip='Fee earned so far − labor cost.'),
        column('margin_pct', 'Margin %', 'percent_0dp'),
    ]


def client_columns() -> list[dict]:
    return [
        column('label', 'Client', 'text'),
        column('projects', 'Projects', 'integer'),
        column('budget_hours', 'Budget hrs', 'hours_1dp'),
        column('hours', 'Used hrs', 'hours_1dp'),
        column('burn_pct', 'Burn', 'percent_0dp'),
        column('fee', 'Fees', 'currency_0dp'),
        column('effective_rate', 'Effective $/hr', 'currency_0dp'),
        column('cost', 'Labor cost', 'currency_0dp'),
        column('margin', 'Margin', 'currency_0dp'),
        column('margin_pct', 'Margin %', 'percent_0dp'),
    ]


def build_rows(org, scope, time) -> dict:
    """Project rows, client rows and totals for the period. Pure data, no payloads."""
    projects = Project.objects.filter(org=org).select_related('client')
    client_ids = set(scope.ids) if scope.type == 'client' else None
    project_ids = set(scope.ids) if scope.type == 'engagement' else None
    if scope.filters.get('client'):
        f = set(scope.filters['client'])
        client_ids = f if client_ids is None else client_ids & f
    if scope.filters.get('engagement'):
        f = set(scope.filters['engagement'])
        project_ids = f if project_ids is None else project_ids & f
    if client_ids is not None:
        projects = projects.filter(client_id__in=client_ids)
    if project_ids is not None:
        projects = projects.filter(id__in=project_ids)
    projects = list(projects)
    by_id = {p.id: p for p in projects}

    period_end = plan_end(time)
    budgets = pb.window_budget(org, time.start, period_end, projects)
    minutes = pb.window_minutes_by_project_user(org, time.start, time.end, list(by_id))
    elapsed = pb.window_elapsed(time.start, period_end)
    list_rates = pb.fee_rates(org, {p.client_id for p in projects}, pb.month_start(time.end))

    costs = cost_rate_map(org)
    fallback_cost = default_cost_rate(org)
    used = defaultdict(float)
    cost = defaultdict(float)
    for (pid, uid), m in minutes.items():
        h = m / 60.0
        used[pid] += h
        cost[pid] += h * float(costs.get(uid, fallback_cost) or 0)

    rows = []
    for pid in set(budgets) | set(used):
        p = by_id.get(pid)
        if p is None:
            continue
        budget_h, fee = budgets.get(pid, (None, None))
        hours = round(used.get(pid, 0.0), 2)
        if budget_h is not None and budget_h <= 0:
            budget_h, fee = None, None
        if budget_h is None and not hours:
            continue
        burn = (hours / float(budget_h) * 100) if budget_h else None
        pace = round(burn - elapsed * 100, 1) if burn is not None else None
        flags = []
        if burn is not None and burn > 100:
            flags.append('over_budget')
        elif pace is not None and elapsed < 1.0 and pace > AHEAD_OF_PACE_PTS:
            flags.append('ahead_of_pace')
        if budget_h is None:
            flags.append('no_budget')
        c = round(cost.get(pid, 0.0), 2)
        # The fee accrues evenly over its period. Comparing a whole month's fee
        # with two days of hours made every project look like a $255/hour
        # gold mine on the 2nd; what has been EARNED so far is the honest
        # numerator. A finished period earns all of it.
        earned = _f(fee) * elapsed if fee is not None else None
        rows.append({
            'id': p.id,
            'project_id': p.id,
            'client_id': p.client_id,
            'client': p.client.name,
            'label': p.name,
            'budget_hours': _f(budget_h) if budget_h is not None else None,
            'hours': hours,
            'burn_pct': round(burn, 1) if burn is not None else None,
            'pace_pts': pace,
            'fee': _f(fee) if fee is not None else None,
            'list_rate': _f(list_rates.get(p.client_id)),
            'earned': round(earned, 2) if earned is not None else None,
            'effective_rate': round(earned / hours, 2) if earned is not None and hours else None,
            'cost': c,
            'margin': round(earned - c, 2) if earned is not None else None,
            'margin_pct': round((earned - c) / earned * 100, 1) if earned else None,
            'flags': [{'key': f, 'label': _FLAG_LABEL[f]} for f in flags],
            'flag_label': ' · '.join(_FLAG_LABEL[f] for f in flags),
        })
    rows.sort(key=lambda r: (-(r['pace_pts'] if r['pace_pts'] is not None else -999), r['client'], r['label']))

    clients = {}
    for r in rows:
        c = clients.setdefault(r['client_id'], {
            'id': r['client_id'], 'label': r['client'], 'projects': 0, 'budget_hours': 0.0,
            'hours': 0.0, 'fee': 0.0, 'earned': 0.0, 'cost': 0.0, 'budgeted_hours_used': 0.0,
        })
        c['projects'] += 1
        c['hours'] += r['hours']
        c['cost'] += r['cost']
        if r['budget_hours'] is not None:
            c['budget_hours'] += r['budget_hours']
            c['fee'] += r['fee']
            c['earned'] += r['earned']
            c['budgeted_hours_used'] += r['hours']
    client_rows = []
    for c in clients.values():
        earned, used_b = c['earned'], c.pop('budgeted_hours_used')
        client_rows.append({
            **{k: round(v, 2) if isinstance(v, float) else v for k, v in c.items()},
            'burn_pct': round(used_b / c['budget_hours'] * 100, 1) if c['budget_hours'] else None,
            'effective_rate': round(earned / used_b, 2) if earned and used_b else None,
            'margin': round(earned - c['cost'], 2) if earned else None,
            'margin_pct': round((earned - c['cost']) / earned * 100, 1) if earned else None,
        })
    client_rows.sort(key=lambda c: -c['fee'])

    budgeted = [r for r in rows if r['budget_hours'] is not None]
    fee_total = sum(r['fee'] for r in budgeted)
    earned_total = sum(r['earned'] for r in budgeted)
    used_on_budgeted = sum(r['hours'] for r in budgeted)
    cost_total = sum(r['cost'] for r in rows)
    totals = {
        'fee': round(fee_total, 2),
        'budget_hours': round(sum(r['budget_hours'] for r in budgeted), 2),
        'hours': round(sum(r['hours'] for r in rows), 2),
        'hours_on_budgeted': round(used_on_budgeted, 2),
        'earned': round(earned_total, 2),
        'effective_rate': round(earned_total / used_on_budgeted, 2) if used_on_budgeted else None,
        'list_rate': max((r['list_rate'] for r in budgeted), default=None),
        'over': sum(1 for r in rows if any(f['key'] == 'over_budget' for f in r['flags'])),
        'ahead': sum(1 for r in rows if any(f['key'] == 'ahead_of_pace' for f in r['flags'])),
        'unbudgeted_hours': round(sum(r['hours'] for r in rows if r['budget_hours'] is None), 2),
        'cost': round(cost_total, 2),
        'margin': round(earned_total - cost_total, 2) if earned_total else None,
        'margin_pct': round((earned_total - cost_total) / earned_total * 100, 1) if earned_total else None,
        'elapsed': elapsed,
    }
    return {'rows': rows, 'clients': client_rows, 'totals': totals}


def _tile(id, label, fmt, value, tooltip='', **extra) -> KPITile:
    state = MetricState.READY if value is not None else MetricState.EMPTY
    return KPITile(id=id, label=label, size='large', format=fmt, tooltip=tooltip,
                   metric=MetricValue(state=state, value=value, **extra))


@register_lens('projects')
class ProjectsLens(Lens):
    label = 'Projects'

    def assemble(self, org, scope, time, compare=None):
        data = build_rows(org, scope, time)
        t = data['totals']
        pct_gone = round(t['elapsed'] * 100)

        tiles = [
            _tile('project_fees', 'Budgeted fees', 'currency_0dp', t['fee'] or None,
                  tooltip='Monthly budget hours × each client\'s rate, prorated to the period.'),
            _tile('project_effective_rate', 'Effective rate', 'currency_0dp', t['effective_rate'],
                  tooltip='Fees earned so far ÷ hours used on budgeted projects (the fee accrues '
                          'evenly over the period). Below the list rate means the work is taking '
                          'more hours than it was priced for.',
                  secondary_value=t['list_rate'] if t['effective_rate'] is not None else None,
                  secondary_label='list rate', secondary_format='currency_0dp',
                  threshold_zone=('good' if t['effective_rate'] is not None and t['list_rate']
                                  and t['effective_rate'] >= t['list_rate'] else
                                  'watch' if t['effective_rate'] is not None and t['list_rate'] else None)),
            _tile('project_hours_used', 'Hours used', 'hours_1dp', t['hours'] or None,
                  tooltip='Confirmed hours filed to projects in the period.',
                  secondary_value=t['budget_hours'] or None, secondary_label='budgeted',
                  secondary_format='hours_1dp'),
            _tile('projects_over_budget', 'Over budget', 'integer', t['over'] if data['rows'] else None,
                  tooltip='Projects that used more hours than budgeted for the period.',
                  secondary_value=t['ahead'] or None, secondary_label='ahead of pace',
                  secondary_format='integer'),
            # Ids chosen to match cost_visibility.COST_METRIC_IDS: removed for non-owners.
            _tile('labor_cost', 'Labor cost', 'currency_0dp', t['cost'] or None,
                  tooltip='Hours used × each person\'s cost rate.'),
            _tile('gross_margin', 'Project margin', 'percent_1dp', t['margin_pct'],
                  tooltip='(Fees earned so far − labor cost) ÷ fees earned, on budgeted projects.',
                  secondary_value=t['margin'], secondary_label='margin', secondary_format='currency_0dp'),
        ]

        subtitle = f"{time.label} · {pct_gone}% of the period gone. Budgets are monthly, prorated to the period."
        if t['unbudgeted_hours']:
            subtitle += f" {t['unbudgeted_hours']:.1f}h went to projects with no budget."
        projects_table = DataTablePayload(
            id='projects_table', title='Projects, hottest first', subtitle=subtitle,
            columns=project_columns(), rows=data['rows'],
            default_sort={'key': 'pace_pts', 'direction': 'desc'},
            row_drilldown={'scope_type': 'client', 'lens': 'projects',
                           'id_key': 'client_id', 'label_key': 'client'},
            bar_columns=['hours'],
            state=MetricState.READY if data['rows'] else MetricState.EMPTY,
            error_message=None if data['rows'] else
                'No project budgets or project time in this period. Set monthly hours '
                'in Settings → Clients → Projects, or connect QuickBooks Time.',
        )
        sections = [Section(id='headline', type='kpi_row', children=tiles),
                    Section(id='projects', type='section', title='Projects', children=[projects_table])]
        if scope.type != 'client' and len(data['clients']) > 1:
            sections.append(Section(id='clients', type='section', title='By client', children=[
                DataTablePayload(
                    id='project_clients_table', title='Clients', subtitle='The monthly retainer, per client.',
                    columns=client_columns(), rows=data['clients'],
                    default_sort={'key': 'fee', 'direction': 'desc'},
                    row_drilldown={'scope_type': 'client', 'lens': 'projects',
                                   'id_key': 'id', 'label_key': 'label'},
                    bar_columns=['fee'],
                ),
            ]))
        return sections
