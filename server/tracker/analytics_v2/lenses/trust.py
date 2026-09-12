"""
Trust lens — whether the time data is sound enough to run the other lenses on.

Why this exists, in the words of the room it kept failing in: a firm's general
ledger answers revenue and payroll at the firm level and stops there. It cannot
say which client was profitable, which engagement overran, or where a person's
week went, because all three take per-client time as their input — and every
partner knows their timesheets are reconstructed on Friday afternoon from memory.

So realization, utilization, margin-by-client and WIP are not numbers we are
competing with. They are numbers nobody can currently produce. That is the
opportunity, and it has a precondition: the input has to be shown to be sound
before the economics built on it are worth reading.

This lens is that showing, in the order the questions actually get asked:

  1. is it right?              — autonomy and measured precision, together
  2. what did it cost?         — human decisions per day, hours per decision
  3. what does it unlock?      — the per-client view the ledger cannot produce
  4. what is waiting on you?   — the queue, aged, with owners

Two rules this file holds itself to. Accuracy arithmetic is not reimplemented —
`tracker.services.accuracy` owns it, and a disagreement with the Accuracy tab is
a bug here. And the boundaries are stated on the page rather than in a footnote:
the closing cards say what these numbers are NOT, because a partner who finds an
unstated limit himself stops believing the stated ones.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Sum

from tracker.models import Block
from tracker.services import accuracy as acc

from ..types import (
    ChartCardPayload, DataTablePayload, InsightCardPayload, MetricState,
    Section, to_float,
)
from .base import Lens, register_lens
from .helpers import column, headline_row

# Precision below this reads as "not yet good enough to build billing on".
PRECISION_FLOOR = 0.85
# An audit sample older than this is stale enough to say so out loud.
SAMPLE_STALE_DAYS = 35
# Above this many attributed blocks the evidence audit is too slow to run
# inline; the section is omitted rather than stalling the whole page.
AUDIT_BLOCK_CEILING = 40_000

# Evidence palette. Teal carries "we know", rust carries "we don't", and the
# faded steps are subdivisions within each — so the page reads as two positions
# at a glance and five only when you look. Checked for colour-vision
# separation against both the light and dark chart surfaces.
C_KNOWN = "#00897b"
C_KNOWN_2 = "#4db6ac"
C_KNOWN_3 = "#a7d8d2"
C_OPEN = "#c2410c"
C_OPEN_2 = "#e09a72"
C_PERSON = "#2563a8"
C_MUTED = "#8a9c97"


@register_lens("trust")
class TrustLens(Lens):
    label = "Trust"

    def assemble(self, org, scope, time, compare=None):
        # Every metric here is org-wide (the accuracy service has no scope
        # argument). On a client or staff page the honest move is to show the
        # firm-level evidence with the headline row omitted rather than to
        # relabel firm numbers as that client's.
        firm = scope.type == "firm"

        sections: list[Section] = []

        if firm:
            sections.append(headline_row(
                ["attribution_autonomy", "attribution_precision",
                 "review_burden", "hours_per_decision"],
                org, scope, time, compare, section_id="headline",
            ))

        sections.append(self._decided_by_section(org, time))

        audit = self._audit_section(org, time)
        if audit is not None:
            sections.append(audit)

        if firm:
            trend = self._trend_section(org, time)
            if trend is not None:
                sections.append(trend)

            provable = self._provable_section(org, time)
            if provable is not None:
                sections.append(provable)

        unlocked = self._unlocked_section(org, scope, time)
        if unlocked is not None:
            sections.append(unlocked)

        queue = self._queue_section(org, scope, time)
        if queue is not None:
            sections.append(queue)

        sections.append(self._boundaries_section(org, time))
        return sections

    # ── 1. who decided each hour ────────────────────────────────────────────
    def _decided_by_section(self, org, time) -> Section:
        """The autonomy split, as a shape.

        The middle bar is the one that matters and it is the one that reads as
        failure at a glance, so the subtitle says what it is before the viewer
        decides for themselves: held-back time is the software declining to
        guess, and it is the reason the left bar can be believed.
        """
        cov = acc.coverage(org.id, time.start, time.end)
        filed = (cov.get("filed_minutes") or 0) / 60.0
        asked = (cov.get("asked_minutes") or 0) / 60.0
        human = (cov.get("human_filed_minutes") or 0) / 60.0
        discarded = (cov.get("discarded_minutes") or 0) / 60.0
        total = filed + asked + human

        chart = ChartCardPayload(
            id="decided_by",
            title="Every recorded hour, by who decided it",
            subtitle=(
                f"{time.label} · {total:,.1f} h recorded. Held-back time is the "
                f"matcher refusing to guess — it is what makes the first bar "
                f"worth reading."
            ),
            chart_type="proportion_bar",
            data=[
                {"label": "Filed to a client with nobody asked",
                 "value": round(filed, 1), "color": C_KNOWN},
                {"label": "Held back — evidence too thin to guess",
                 "value": round(asked, 1), "color": C_OPEN},
                {"label": "Set by a person at the keyboard",
                 "value": round(human, 1), "color": C_PERSON},
            ],
            series=[{"key": "value", "label": "h"}],
            state=MetricState.READY if total else MetricState.EMPTY,
        )

        rows = [
            {"who": "Filed automatically",
             "hours": round(filed, 1),
             "share": (filed / total) if total else None,
             "means": "Assigned to a client with nobody asked"},
            {"who": "Held for review",
             "hours": round(asked, 1),
             "share": (asked / total) if total else None,
             "means": "Evidence too thin to guess — waiting on a person"},
            {"who": "Set by a person",
             "hours": round(human, 1),
             "share": (human / total) if total else None,
             "means": "Someone chose the client at the keyboard"},
        ]

        table = DataTablePayload(
            id="decided_by_rows",
            title="The same three numbers, exactly",
            subtitle=(
                f"{discarded:,.1f} h was judged not to be real activity and is on "
                f"neither side of this ratio."
            ),
            columns=[
                column("who", "Decided by", "text"),
                column("hours", "Hours", "hours_1dp"),
                column("share", "Share", "percent_1dp"),
                column("means", "Which means", "text"),
            ],
            rows=rows,
            state=MetricState.READY if total else MetricState.EMPTY,
        )
        return Section(
            id="decided_by_section", type="section",
            title="Who Decided Each Hour", collapsible=False,
            children=[chart, table],
        )

    # ── 2. the audit ────────────────────────────────────────────────────────
    def _audit_section(self, org, time) -> Section | None:
        """Sample composition, including the draws with no verdict yet.

        Showing `pending` and `unverifiable` beside the wins is the whole point.
        A precision figure quoted without its undecided remainder is the kind of
        number a partner discovers is incomplete, and then discounts everything
        else on the page.
        """
        from ..metrics.attribution import sample_for_window

        samp, period = sample_for_window(org.id, time)
        drawn = samp.get("drawn") or 0
        if not drawn:
            return Section(
                id="audit", type="section", title="How Often We Were Right",
                collapsible=False,
                children=[InsightCardPayload(
                    id="no_sample",
                    severity="watch",
                    headline="No audit sample has been drawn yet",
                    body=("Precision is only measurable against blocks a person "
                          "has judged one at a time. Draw a sample and this "
                          "section fills in — without one there is no defensible "
                          "accuracy claim, only autonomy, and autonomy on its own "
                          "would be perfect for a system that guessed wildly."),
                    source="rule", dismissible=False,
                )],
            )

        correct = samp.get("correct") or 0
        wrong = samp.get("wrong") or 0
        unver = samp.get("unverifiable") or 0
        # `pending`, `precision`, `ci_low/high` and `worst_case` are computed by
        # the accuracy service. Recomputing them here is how the two drift.
        pending = samp.get("pending") or 0
        decided = correct + wrong

        chart = ChartCardPayload(
            id="audit_composition",
            title="What the random audit found",
            subtitle=(
                f"{drawn} blocks drawn at random from what we filed "
                f"automatically, then judged by hand"
                + (f" · measured over {period[0]:%-d %b}–{period[1]:%-d %b %Y}, "
                   f"not the range selected above"
                   if period and (period[0] != time.start or period[1] != time.end)
                   else "")
            ),
            chart_type="dot_matrix",
            data=[
                {"label": "correct", "value": correct, "color": C_KNOWN},
                {"label": "wrong", "value": wrong, "color": C_OPEN},
                {"label": "unverifiable", "value": unver, "color": C_MUTED},
                {"label": "not yet judged", "value": pending,
                 "color": C_MUTED, "outline": True},
            ],
            series=[{"key": "value", "label": "Blocks"}],
            state=MetricState.READY,
        )

        children: list = [chart]

        if decided:
            lo = samp.get("ci_low") or 0.0
            hi = samp.get("ci_high") or 0.0
            precision = samp.get("precision") or (correct / decided)
            floor = samp.get("worst_case") or (correct / drawn)
            good = precision >= PRECISION_FLOOR
            children.append(InsightCardPayload(
                id="precision_reading",
                severity="good" if good else "watch",
                headline=(f"{precision * 100:.1f}% of judged blocks were "
                          f"on the right client"),
                body=(f"{correct} correct and {wrong} wrong of {decided} judged, "
                      f"95% confidence interval {lo * 100:.1f}–{hi * 100:.1f}%. "
                      f"If every one of the {drawn - decided} undecided draws were "
                      f"counted as wrong, the figure would still be "
                      f"{floor * 100:.1f}% — that is the floor, not the estimate."),
                source="rule", dismissible=False,
            ))

        if pending:
            children.append(InsightCardPayload(
                id="pending_draws",
                severity="watch",
                headline=f"{pending} drawn blocks are still waiting on a verdict",
                body=("Each one judged narrows the confidence interval above. "
                      "This is the cheapest accuracy work available — the blocks "
                      "are already selected and the evidence is already attached."),
                source="rule", dismissible=False,
            ))

        if unver:
            children.append(InsightCardPayload(
                id="unverifiable_draws",
                severity="info",
                headline=f"{unver} blocks could not be settled either way",
                body=("Usually a QuickBooks window that reported no company name "
                      "at all, so nothing on screen could confirm or refute the "
                      "client. They are excluded from the percentage rather than "
                      "quietly counted as correct."),
                source="rule", dismissible=False,
            ))

        if period:
            age = (time.end - period[1]).days
            if age > SAMPLE_STALE_DAYS:
                children.append(InsightCardPayload(
                    id="stale_sample",
                    severity="watch",
                    headline=f"The accuracy measurement is {age} days old",
                    body=(f"It covers {period[0]:%-d %b}–{period[1]:%-d %b %Y}. "
                          f"Everything above has moved since then — draw a fresh "
                          f"sample before quoting this figure to anyone."),
                    source="rule", dismissible=False,
                ))

        fixed = acc.self_correction_count(org.id, time.start, time.end)
        if fixed:
            children.append(InsightCardPayload(
                id="self_corrections",
                severity="good",
                headline=f"{fixed} client attributions were corrected automatically",
                body=("Blocks the system re-filed on its own during this window — "
                      "a QuickBooks company file read later, or a vendor "
                      "fingerprint that resolved two same-named parishes. Nobody "
                      "was asked, and nobody had to notice."),
                source="rule", dismissible=False,
            ))

        return Section(
            id="audit", type="section", title="How Often We Were Right",
            collapsible=False, children=children,
        )


    # ── 2b. is it getting better? ───────────────────────────────────────────
    def _trend_section(self, org, time) -> Section | None:
        """Autonomy month by month.

        This is the section that answers the objection nobody says out loud:
        "your data is imperfect today, so why would I build on it?" A single
        accuracy reading cannot answer that. A rising line can — it turns an
        imperfect number into a compounding one, and it is the difference
        between a snapshot and an argument.
        """
        from django.db.models.functions import TruncMonth

        months = max(int((time.end - time.start).days / 30) + 1, 6)
        first = (time.end.replace(day=1) - timedelta(days=31 * (months - 1))).replace(day=1)

        rows = (
            Block.objects
            .filter(org=org, deleted_at__isnull=True,
                    day__gte=first, day__lte=time.end)
            .exclude(classification_state='suppressed')
            .annotate(mo=TruncMonth('day'))
            .values('mo', 'classification_state', 'state_changed_by', 'categorized_by')
            .annotate(m=Sum('minutes'))
        )

        by_month: dict = {}
        for r in rows:
            mo = r['mo']
            if mo is None:
                continue
            slot = by_month.setdefault(mo, {'filed': 0, 'other': 0})
            m = to_float(r['m'])
            auto = (
                r['classification_state'] == 'committed'
                and (r['state_changed_by'] or '') not in acc.HUMAN_SET_STATES
                and (r['categorized_by'] or '') != 'manual'
            )
            slot['filed' if auto else 'other'] += m

        data = []
        for mo in sorted(by_month):
            v = by_month[mo]
            total = v['filed'] + v['other']
            if total < 60:  # under an hour in a month is noise, not a trend point
                continue
            data.append({
                'month': mo.strftime('%b %Y'),
                'autonomy': round(100.0 * v['filed'] / total, 1),
            })

        if len(data) < 3:
            return None

        first_pt, last_pt = data[0], data[-1]
        gain = last_pt['autonomy'] - first_pt['autonomy']

        chart = ChartCardPayload(
            id='autonomy_trend',
            title='Share filed without asking, by month',
            subtitle=(f"{first_pt['month']} {first_pt['autonomy']:.0f}% → "
                      f"{last_pt['month']} {last_pt['autonomy']:.0f}%. The current "
                      f"month is partial and will move."),
            chart_type='line',
            data=data,
            series=[{'key': 'autonomy', 'label': 'Filed without asking (%)',
                  'color': C_KNOWN}],
            state=MetricState.READY,
        )

        children: list = [chart]
        if gain >= 5:
            children.append(InsightCardPayload(
                id='autonomy_improving',
                severity='good',
                headline=f'Up {gain:.0f} points since {first_pt["month"]}',
                body=('Each correction and each client name the firm confirms feeds '
                      'the matcher, so the share it can file unaided compounds. '
                      'This is the number to watch across a beta: a single month\'s '
                      'accuracy is a snapshot, this is the trajectory.'),
                source='rule', dismissible=False,
            ))

        return Section(
            id='trend', type='section', title='Is It Getting Better?',
            collapsible=False, children=children,
        )

    # ── 3b. the two books ───────────────────────────────────────────────────
    def _provable_section(self, org, time) -> Section | None:
        """Split the book by whether the evidence can name the client.

        This is the section that stops one messy client family from discrediting
        the whole dataset. A firm with six parishes called some variant of "St.
        Mary's" does not have bad data — it has two populations, and only one of
        them is in question:

          PROVABLE      the block's own text distinguishes this client from
                        every look-alike. Economics here are safe to report.
          UNPROVEN      the text names the family but not the member. The pick
                        may well be right; the data cannot show it.

        Reporting one blended accuracy number over both is what makes the whole
        thing feel hopeless. Reporting them apart makes the second one finite,
        owned, and fixable — usually by renaming a handful of roster entries.
        """
        from tracker.services import attribution_audit as aa

        days = max((time.end - time.start).days + 1, 1)

        # The audit walks every attributed block through the family resolver —
        # roughly 13k blocks for a 90-day range at TL Wall's size. That is fine
        # for a CLI run and too slow to do twice on a page load, so it is capped
        # and memoised per request. The durable fix is a nightly rollup; until
        # then, a wide range gets the section omitted rather than a page that
        # hangs.
        cached = getattr(self, "_audit_cache", None)
        if cached is not None and cached[0] == (org.id, days):
            rep = cached[1]
        else:
            est = Block.objects.filter(
                org=org, day__gte=time.start, day__lte=time.end,
                client_id__isnull=False,
            ).count()
            if est > AUDIT_BLOCK_CEILING:
                return None
            try:
                rep = aa.audit_org(org.id, days=days)
            except Exception:
                return None
            self._audit_cache = ((org.id, days), rep)

        mins = rep.get('minutes') or {}
        # The AMBIGUOUS bucket contains two different things. Splitting them is
        # the difference between "a third of your book is in doubt" and "a fifth
        # of it has a question someone can answer" — see attribution_audit.
        incidental = (rep.get('ambiguous_incidental') or {}).get('minutes', 0) / 60.0
        answerable = (rep.get('ambiguous_answerable') or {}).get('minutes', 0) / 60.0
        singular = mins.get(aa.SINGULAR, 0) / 60.0
        resolved = mins.get(aa.RESOLVED, 0) / 60.0
        no_ev = mins.get(aa.NO_EVIDENCE, 0) / 60.0
        provable = singular + resolved + incidental
        unproven = answerable + no_ev
        total = provable + unproven
        if total <= 0:
            return None

        chart = ChartCardPayload(
            id='provable_split',
            title='Booked time, by whether the evidence names the client',
            subtitle=(f"{provable / total * 100:.0f}% of booked hours can be shown "
                      f"to be on the right client from the block's own text."),
            chart_type='proportion_bar',
            data=[
                {'label': 'Only one client it could be',
                 'value': round(singular, 1), 'color': C_KNOWN},
                {'label': 'Look-alikes exist, the text separates them',
                 'value': round(resolved, 1), 'color': C_KNOWN_2},
                {'label': 'Collision nothing would ever ask about',
                 'value': round(incidental, 1), 'color': C_KNOWN_3},
                {'label': 'Names the family, not the member',
                 'value': round(answerable, 1), 'color': C_OPEN},
                {'label': 'The text names nothing at all',
                 'value': round(no_ev, 1), 'color': C_OPEN_2},
            ],
            series=[{'key': 'value', 'label': 'h'}],
            state=MetricState.READY,
        )

        children: list = [chart, InsightCardPayload(
            id='two_books',
            severity='good' if provable / total >= 0.7 else 'watch',
            headline=(f'{provable:,.0f} of {total:,.0f} booked hours are on solid ground'),
            body=(f"Report economics on those without reservation — that figure "
                  f"includes {incidental:,.0f} h whose only rival is an incidental "
                  f"word match the software would never put to a person. The "
                  f"remaining {unproven:,.0f} h sit on client families whose members "
                  f"genuinely share a name: the pick may be right, but nothing in "
                  f"the text proves it. Keeping the two apart is what stops one "
                  f"ambiguous family from putting the whole book in doubt."),
            source='rule', dismissible=False,
        )]

        picks = rep.get('session_decisions') or 0
        if picks:
            children.append(InsightCardPayload(
                id='picks_to_settle',
                severity='info',
                headline=f'{picks} human picks would settle the unproven pile',
                body=(f"Consecutive work by the same person counts as one decision, "
                      f"which is how it actually gets reviewed. Over {days} days "
                      f"that is about {picks / days:.1f} decisions a day to move "
                      f"{unproven:,.0f} hours onto solid ground."),
                source='rule', dismissible=False,
            ))

        # {client_id: [(name_form, [(other_id, other_name, relation), ...]), ...]}
        forms = rep.get('ambiguous_name_forms') or {}
        by_id = rep.get('by_id') or {}
        per_client = rep.get('per_client') or {}
        if forms:
            # Ranked by the hours actually at stake, so the rename that buys the
            # most comes first. An alphabetical list of 54 names is a chore; a
            # list with hours against it is a decision.
            def at_stake(cid):
                buckets = per_client.get(cid) or {}
                return sum(buckets.values())

            rows = []
            for cid in sorted(forms, key=at_stake, reverse=True)[:15]:
                client = by_id.get(cid)
                for name_form, collisions in forms[cid][:1]:
                    others = [f"{n} ({rel})" for _oid, n, rel in collisions[:2]]
                    extra = len(collisions) - len(others)
                    if extra > 0:
                        others.append(f"+{extra} more")
                    rows.append({
                        'client': getattr(client, 'name', None) or f'Client {cid}',
                        'form': name_form,
                        'collides': ', '.join(others),
                        'hours': round(at_stake(cid) / 60.0, 1),
                    })

            children.append(DataTablePayload(
                id='rename_candidates',
                title='Roster entries worth renaming',
                subtitle=(f"{len(forms)} clients carry a name or alias that cannot "
                          f"exclude another client. Renaming one settles every "
                          f"future block in that family — the cheapest accuracy "
                          f"work there is, and the firm's to do, not ours. "
                          f"Ranked by hours currently at stake."),
                columns=[
                    column('client', 'Client', 'text'),
                    column('form', 'Name or alias', 'text'),
                    column('collides', 'Also matches', 'text'),
                    column('hours', 'Hours at stake', 'hours_1dp'),
                ],
                rows=rows,
                default_sort={'key': 'hours', 'direction': 'desc'},
                state=MetricState.READY,
            ))

        return Section(
            id='provable', type='section',
            title='Which Hours Can Be Proved', collapsible=False,
            children=children,
        )

    # ── 3. what trustworthy time unlocks ────────────────────────────────────
    def _unlocked_section(self, org, scope, time) -> Section | None:
        """The per-client view a general ledger structurally cannot produce.

        Hours, the number of people who touched the client, and the number of
        distinct days it was worked. The last two are the ones that land: a
        ledger can never say a parish was touched by six people across
        forty-two separate days, because it never sees the work, only the bill.
        """
        from ..blocks import billable_q, confirmed_qs

        qs = confirmed_qs(Block.objects.filter(
            org=org, day__gte=time.start, day__lte=time.end,
        )).filter(billable_q(org), client_id__isnull=False)
        qs = self._apply_scope_qs(qs, scope)

        agg = list(
            qs.values("client__name")
              .annotate(minutes=Sum("minutes"),
                        people=Count("user_id", distinct=True),
                        days=Count("day", distinct=True))
              .order_by("-minutes")[:15]
        )
        if not agg:
            return None

        total_min = to_float(qs.aggregate(s=Sum("minutes"))["s"])
        client_count = qs.values("client_id").distinct().count()

        rows = [{
            "client": r["client__name"],
            "hours": round(to_float(r["minutes"]) / 60.0, 1),
            "people": r["people"],
            "days": r["days"],
            "share": (to_float(r["minutes"]) / total_min) if total_min else None,
        } for r in agg]

        table = DataTablePayload(
            id="client_effort",
            title="Where the work actually went",
            subtitle=(
                f"{time.label} · {total_min / 60.0:,.1f} billable hours across "
                f"{client_count} clients. 'People' and 'Days' are the columns a "
                f"general ledger can never fill — it sees the invoice, never the work."
            ),
            columns=[
                column("client", "Client", "text"),
                column("hours", "Hours", "hours_1dp"),
                column("share", "Share of hours", "percent_1dp"),
                column("people", "People", "integer",
                       tooltip="Distinct staff who worked on this client."),
                column("days", "Days touched", "integer",
                       tooltip="Distinct days on which someone worked on this client."),
            ],
            rows=rows,
            default_sort={"key": "hours", "direction": "desc"},
            state=MetricState.READY,
        )

        children: list = [table]

        # The one missing input that turns all of this into money.
        missing_fees = self._clients_without_fees(org)
        if missing_fees:
            children.append(InsightCardPayload(
                id="fees_missing",
                severity="watch",
                headline="One input away from per-client profitability",
                body=(f"{missing_fees} of the clients worked in this period have no "
                      f"fee or rate recorded, so this table can only be shown in "
                      f"hours. Load the fee schedule and every row above gains a "
                      f"realized rate and a margin — the first time the firm can "
                      f"see which clients pay for themselves. Nothing else is "
                      f"blocking it; the hours are already here."),
                source="rule", dismissible=False,
            ))

        return Section(
            id="unlocked", type="section",
            title="What Trustworthy Time Makes Visible", collapsible=False,
            children=children,
        )

    def _clients_without_fees(self, org) -> int:
        from tracker.models import ClientBillingProfile

        priced = set(
            ClientBillingProfile.objects
            .filter(org=org, flat_amount__isnull=False)
            .values_list("client_id", flat=True)
        )
        worked = set(
            Block.objects.filter(org=org, client_id__isnull=False)
            .values_list("client_id", flat=True).distinct()
        )
        return len(worked - priced)

    # ── 4. what is waiting ──────────────────────────────────────────────────
    def _queue_section(self, org, scope, time) -> Section | None:
        """The held-back pile, aged, with owners.

        Aged rather than totalled because the two halves need different verbs.
        Recent blocks are a weekly habit worth ten minutes; old ones are a
        cleanup project, and presenting them as one number makes the habit look
        hopeless.
        """
        from django.utils import timezone

        today = timezone.localdate()
        qs = Block.objects.filter(
            org=org, deleted_at__isnull=True,
            classification_state__in=("proposed", "captured"),
        )
        qs = self._apply_scope_qs(qs, scope)

        bands = [
            ("0–7 days", today - timedelta(days=7), today),
            ("8–30 days", today - timedelta(days=30),
             today - timedelta(days=8)),
            ("31–90 days", today - timedelta(days=90),
             today - timedelta(days=31)),
        ]
        data = []
        live_h = 0.0
        for label, lo, hi in bands:
            m = to_float(qs.filter(day__gte=lo, day__lte=hi)
                           .aggregate(s=Sum("minutes"))["s"])
            data.append({"age": label, "hours": round(m / 60.0, 1)})
            if label != "31–90 days":
                live_h += m / 60.0
        older = to_float(
            qs.filter(day__lt=today - timedelta(days=90))
              .aggregate(s=Sum("minutes"))["s"]
        ) / 60.0
        data.append({"age": "Over 90 days", "hours": round(older, 1)})

        if not any(d["hours"] for d in data):
            return None

        chart = ChartCardPayload(
            id="queue_aging",
            title="Time waiting on a decision",
            subtitle=(f"{live_h:,.1f} h from the last month is live work, one click "
                      f"each from being booked. Anything older is a cleanup project, "
                      f"not a weekly habit."),
            chart_type="horizontal_bar",
            data=data,
            series=[{"key": "hours", "label": "Hours", "color": C_OPEN}],
            state=MetricState.READY,
        )

        owners = list(
            qs.filter(day__gte=today - timedelta(days=30))
              .values("user__first_name", "user__last_name", "user__username")
              .annotate(minutes=Sum("minutes"), blocks=Count("id"))
              .order_by("-minutes")[:12]
        )
        children: list = [chart]
        if owners:
            rows = []
            for o in owners:
                name = f"{o['user__first_name'] or ''} {o['user__last_name'] or ''}".strip()
                rows.append({
                    "person": name or (o["user__username"] or "— unnamed account"),
                    "hours": round(to_float(o["minutes"]) / 60.0, 1),
                    "blocks": o["blocks"],
                })
            children.append(DataTablePayload(
                id="queue_owners",
                title="Whose queue it is",
                subtitle="Last 30 days · the people who can clear it fastest",
                columns=[
                    column("person", "Person", "text"),
                    column("hours", "Hours waiting", "hours_1dp"),
                    column("blocks", "Blocks", "integer"),
                ],
                rows=rows,
                default_sort={"key": "hours", "direction": "desc"},
                state=MetricState.READY,
            ))

        return Section(
            id="queue", type="section", title="What's Waiting On You",
            collapsible=False, children=children,
        )

    # ── 5. stated boundaries ────────────────────────────────────────────────
    def _boundaries_section(self, org, time) -> Section:
        """What these numbers are NOT — driven by the org's real configuration.

        Each card appears only while it is true of this firm, so the page stops
        making the admission once the gap is closed.
        """
        from ..permissions import firm_invoices_here

        cards: list[InsightCardPayload] = []

        if not firm_invoices_here(org):
            cards.append(InsightCardPayload(
                id="bound_no_invoices",
                severity="info",
                headline="These are hours, not invoices",
                body=("No invoices have been imported, so nothing here is billed or "
                      "collected revenue — your ledger remains the authority on "
                      "that. What this page claims is narrower and not available "
                      "anywhere else: where the hours went, and how reliably."),
                source="rule", dismissible=False,
            ))

        samp = acc.sampled_precision(org.id, time.start, time.end)
        if samp.get("drawn"):
            cards.append(InsightCardPayload(
                id="bound_sample",
                severity="info",
                headline="Precision is a sample estimate, not a guarantee",
                body=(f"It is measured on {samp['drawn']} blocks drawn at random, "
                      f"not on every block filed. The confidence interval is the "
                      f"honest width of that claim; a bigger sample narrows it and "
                      f"nothing else does."),
                source="rule", dismissible=False,
            ))

        cards.append(InsightCardPayload(
            id="bound_coverage",
            severity="info",
            headline="This is desk work, not the whole week",
            body=("Time at the machine is what can be observed. Meetings away from "
                  "the desk, phone calls and site visits are not in these totals, "
                  "so read every figure as 'of the work we can see'."),
            source="rule", dismissible=False,
        ))

        return Section(
            id="boundaries", type="section",
            title="What These Numbers Are Not", collapsible=False,
            children=cards,
        )

    # ── shared ──────────────────────────────────────────────────────────────
    def _apply_scope_qs(self, qs, scope):
        if scope.type == "client":
            return qs.filter(client_id__in=scope.ids)
        if scope.type == "staff":
            return qs.filter(user_id__in=scope.ids)
        if scope.type == "service":
            return qs.filter(task_type_id__in=scope.ids)
        if scope.type == "engagement":
            return qs.filter(project_id__in=scope.ids)
        return qs
