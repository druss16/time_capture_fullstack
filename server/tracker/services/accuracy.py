"""
How accurate are we, and how do we know?

Three signals, and they are NOT interchangeable:

  1. Human corrections  — free, continuous, and a LOWER BOUND. It only counts
     errors somebody happened to look at. Silence is not confirmation: blocks
     judged in their first seconds and then grown to an hour have sat committed
     and wrong for weeks without anyone touching them.

  2. The mismatch scan  — finds errors nobody corrected, also a LOWER BOUND. It
     sees exactly one kind of error, a title that disagrees with the booked
     client, and is blind to a generic-titled block on the wrong one.

  3. A random sample    — the only UNBIASED one, because the sample is drawn by
     us rather than selected by whatever a detector happens to notice. This is
     the number we quote.

(3) is the headline; (1) and (2) run continuously and get calibrated against
it — once the audit says 94% and the scan only found half of those errors, the
scan's blind-spot multiplier is a measured quantity instead of a guess.

Two numbers, never one. Precision alone is gamed by asking about everything;
coverage alone is gamed by guessing at everything. Reported together, neither
can improve without the other showing the cost.
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta

from django.db.models import F, Sum
from django.utils import timezone

# A block whose client a PERSON chose is not evidence about our accuracy — we
# would be grading their judgement, not ours. This is the same convention the
# heal/backfill commands use to leave human decisions alone.
HUMAN_SET_STATES = ('user', 'user_edit', 'correction')

DEFAULT_SAMPLE_SIZE = 50



# ── Which mechanism filed a block ───────────────────────────────────────────
# Ordered most-decisive first. A block's audit usually carries several signals
# at once (a client one, a category one, a fallback), so the first match down
# this list is taken as "what filed it".
#
# Drawn from the signal types actually present in production, not invented:
# anything not listed is category-or-billable only and must never be reported
# as the reason a CLIENT was chosen. fix6_default alone outnumbers every real
# client signal ~20:1 and means "no client identified" — attributing filings to
# it would make the busiest row in the table a non-answer.
CLIENT_SIGNAL_PRIORITY = (
    'org_rule',                        # deterministic firm routing rule
    'qb_company_file',                 # the QuickBooks company file itself
    'vendor_fingerprint',              # vendors inside the file identify the parish
    'title_match_title_alias',
    'title_match_file_path',
    'title_match_domain',
    'file_path_structure',             # the client folder the document lives in
    'co_open_office',
    'learned_pattern',
    'auto_confirm_name_match',
    'auto_confirm_client_attribution',
    'ai_client',
    'ai_client_batch',
    'agent_inference',
    'agent_current_client',
    'prior_block',                     # temporal: the block before it
    'sandwich_correlation',            # temporal: the blocks either side
    'internal_work',
    'internal_work_deferred',
    'auto_confirm_immaterial_noclient',
    'auto_confirm_immaterial',
)


def _signals_of(audit_signals):
    """matched_signals is a list of dicts, but arrives as a repr string on some rows."""
    ms = audit_signals
    if isinstance(ms, str):
        import ast
        try:
            ms = ast.literal_eval(ms)
        except (ValueError, SyntaxError):
            return []
    return [e for e in (ms or []) if isinstance(e, dict)]


def filed_by_signal(block_id: int, audits_by_block: dict | None = None) -> str:
    """Best available answer to "what put this block on this client?".

    Falls back to the audit's coarse `source` and finally to 'unknown' — an
    honest bucket is better than forcing every block into a named mechanism.
    """
    from tracker.models import ClassificationAudit

    if audits_by_block is not None:
        rows = audits_by_block.get(block_id) or []
    else:
        rows = list(
            ClassificationAudit.objects
            .filter(block_id=block_id)
            .order_by('-created_at')
            .values_list('source', 'matched_signals')[:5]
        )

    present, source = set(), ''
    for src, ms in rows:
        source = source or (src or '')
        for e in _signals_of(ms):
            if e.get('type'):
                present.add(e['type'])

    for name in CLIENT_SIGNAL_PRIORITY:
        if name in present:
            return name
    return f'source:{source}' if source else 'unknown'


def auditable_blocks(org_id: int, start: date, end: date):
    """The population an accuracy claim is actually about: blocks WE filed.

    "Certain" in the UI means committed with a client and no question asked, so
    that is what gets sampled — minus anything a person set, which belongs to
    their judgement rather than ours.
    """
    from tracker.models import Block

    return (
        Block.objects
        .filter(
            org_id=org_id,
            deleted_at__isnull=True,
            classification_state='committed',
            client_id__isnull=False,
            day__gte=start,
            day__lte=end,
        )
        .exclude(state_changed_by__in=HUMAN_SET_STATES)
        .exclude(categorized_by='manual')
    )


def draw_sample(org_id: int, start: date, end: date, n: int = DEFAULT_SAMPLE_SIZE,
                rng: random.Random | None = None) -> list:
    """Draw n blocks uniformly at random, skipping any already drawn for the period.

    Uniform, not weighted by minutes: a weighted draw would estimate the share
    of MINUTES filed correctly, which sounds better suited to billing but makes
    every long block near-certain to be picked and starves the estimate of the
    short ones where the misfiles concentrate. Minutes are reported separately,
    as the weight of the errors found.
    """
    from tracker.models import AccuracySample

    rng = rng or random.Random()

    already = set(
        AccuracySample.objects
        .filter(org_id=org_id, period_start=start, period_end=end)
        .values_list('block_id', flat=True)
    )
    pool = [
        b for b in auditable_blocks(org_id, start, end).values_list('id', flat=True)
        if b not in already
    ]
    if not pool:
        return []

    chosen_ids = rng.sample(pool, min(n, len(pool)))

    from tracker.models import Block, ClassificationAudit
    from tracker.services.classification_service import ClassificationService

    # One query for every drawn block's audits rather than one per block.
    audits_by_block = {}
    for bid, src, ms in (ClassificationAudit.objects
                         .filter(block_id__in=chosen_ids)
                         .order_by('-created_at')
                         .values_list('block_id', 'source', 'matched_signals')):
        audits_by_block.setdefault(bid, []).append((src, ms))

    rows = []
    for b in Block.objects.filter(id__in=chosen_ids):
        rows.append(AccuracySample(
            org_id=org_id, block_id=b.id,
            period_start=start, period_end=end,
            booked_client_id=b.client_id,
            minutes=b.minutes or 0,
            filed_by_signal=filed_by_signal(b.id, audits_by_block),
            booked_category=(ClassificationService._extract_dominant_category(b) or '')[:64],
            booked_is_billable=b.is_billable,
        ))
    AccuracySample.objects.bulk_create(rows, ignore_conflicts=True)
    return chosen_ids


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """95% confidence interval for a proportion.

    Wilson rather than the textbook normal approximation because we expect to
    live near the top of the range: at 47/50 the normal interval runs past
    100%, which would put an impossible number on screen.
    """
    if total <= 0:
        return (0.0, 0.0)
    p = successes / total
    d = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / d
    margin = (z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))) / d
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def _tally(rows, field):
    """Counts + precision + interval for one verdict dimension."""
    counts = {'pending': 0, 'correct': 0, 'wrong': 0, 'unverifiable': 0}
    wrong_minutes = 0
    for r in rows:
        v = r[field]
        counts[v] = counts.get(v, 0) + 1
        if v == 'wrong':
            wrong_minutes += r['minutes'] or 0
    decided = counts['correct'] + counts['wrong']
    lo, hi = wilson_interval(counts['correct'], decided)
    adjudicated = decided + counts['unverifiable']
    return {
        'correct': counts['correct'],
        'wrong': counts['wrong'],
        'unverifiable': counts['unverifiable'],
        'pending': counts['pending'],
        'precision': (counts['correct'] / decided) if decided else None,
        'ci_low': lo if decided else None,
        'ci_high': hi if decided else None,
        'worst_case': (counts['correct'] / adjudicated) if adjudicated else None,
        'wrong_minutes': wrong_minutes,
    }


def by_signal(org_id: int, start: date, end: date, min_decided: int = 3) -> list:
    """Precision split by the mechanism that filed each block.

    The point of the whole audit. A single score says an afternoon is needed
    somewhere; this says where. Rows below `min_decided` are still returned but
    flagged `thin`, because 1-of-1 is not evidence and should not be allowed to
    look like a 100% mechanism or a 0% one.
    """
    from tracker.models import AccuracySample

    rows = list(
        AccuracySample.objects
        .filter(org_id=org_id, period_start=start, period_end=end)
        .values('filed_by_signal', 'verdict', 'minutes')
    )
    grouped = {}
    for r in rows:
        grouped.setdefault(r['filed_by_signal'] or 'unknown', []).append(r)

    out = []
    for signal, group in grouped.items():
        t = _tally(group, 'verdict')
        decided = t['correct'] + t['wrong']
        out.append({
            'signal': signal,
            'drawn': len(group),
            'decided': decided,
            'correct': t['correct'],
            'wrong': t['wrong'],
            'precision': t['precision'],
            'wrong_minutes': t['wrong_minutes'],
            'thin': decided < min_decided,
        })
    # Worst real precision first — the work list, in order.
    out.sort(key=lambda r: (r['thin'], r['precision'] if r['precision'] is not None else 2, -r['wrong']))
    return out


def sampled_precision(org_id: int, start: date, end: date) -> dict:
    """The headline: what the random sample says, with its uncertainty."""
    from tracker.models import AccuracySample

    samples = list(
        AccuracySample.objects
        .filter(org_id=org_id, period_start=start, period_end=end)
        .values('verdict', 'verdict_category', 'verdict_billable', 'minutes')
    )
    # Client stays at the top level: it is the headline, and the shape the API
    # already returns. Category and billable ride alongside as their own
    # dimensions — same blocks, same human pass, three questions.
    client = _tally(samples, 'verdict')
    return {
        'drawn': len(samples),
        **client,
        'category': _tally(samples, 'verdict_category'),
        'billable': _tally(samples, 'verdict_billable'),
    }


def human_correction_rate(org_id: int, start: date, end: date) -> dict:
    """Estimator 1 — errors a person caught and fixed. A floor, not a rate.

    Counted from ClassificationAudit rows where the client actually CHANGED and
    a human made the change. Note what is deliberately not counted: a block
    stamped categorized_by='correction' is one a person COMMITTED after the AI
    proposed it, which is agreement, not a correction. Treating those as errors
    would have reported a ~13% error rate that was mostly confirmations.
    """
    from tracker.models import ClassificationAudit

    changed = (
        ClassificationAudit.objects
        .filter(
            block__org_id=org_id,
            block__day__gte=start,
            block__day__lte=end,
            client_before__isnull=False,
            client_after__isnull=False,
            source='manual',
        )
        .exclude(client_before=F('client_after'))
    )
    n = changed.count()
    filed = auditable_blocks(org_id, start, end).count()
    return {
        'corrected': n,
        'population': filed,
        'floor_error_rate': (n / filed) if filed else None,
    }


def self_correction_count(org_id: int, start: date, end: date) -> int:
    """Errors the system caught and fixed on its own — the trust-building line.

    Same shape as a human correction but machine-sourced (the vendor
    fingerprint re-reading a QuickBooks file, a learned pattern firing later).
    """
    from tracker.models import ClassificationAudit

    return (
        ClassificationAudit.objects
        .filter(
            block__org_id=org_id,
            block__day__gte=start,
            block__day__lte=end,
            client_before__isnull=False,
            client_after__isnull=False,
        )
        .exclude(source='manual')
        .exclude(client_before=F('client_after'))
        .count()
    )


def coverage(org_id: int, start: date, end: date) -> dict:
    """How much we filed without asking, against how much we asked about.

    In minutes, not blocks: a wrong six-minute block and a wrong three-hour
    block are not the same error, and this is a billing product.
    """
    from tracker.models import Block

    base = Block.objects.filter(
        org_id=org_id, deleted_at__isnull=True,
        day__gte=start, day__lte=end,
    )
    committed = base.filter(classification_state='committed')

    # Filing something as No-Client / non-billable is still a decision made
    # without asking, so coverage counts it. That makes this numerator WIDER
    # than the audit population below, which needs a client to have an opinion
    # about. The two are deliberately different sets, not a bug.
    filed = (committed.exclude(state_changed_by__in=HUMAN_SET_STATES)
                      .exclude(categorized_by='manual')
                      .aggregate(m=Sum('minutes'))['m'] or 0)
    human = (committed.filter(state_changed_by__in=HUMAN_SET_STATES)
                      .aggregate(m=Sum('minutes'))['m'] or 0)

    # Suppressed is NOT an ask. It is time judged not to be real activity —
    # discarded, never put in front of anyone — so it belongs on neither side
    # of the ratio. Counting it as "asked" charged us 233 hours of work we
    # never handed to a user.
    asked = (base.filter(classification_state__in=('proposed', 'captured'))
                 .aggregate(m=Sum('minutes'))['m'] or 0)
    discarded = (base.filter(classification_state='suppressed')
                     .aggregate(m=Sum('minutes'))['m'] or 0)

    total = filed + asked + human
    return {
        'filed_minutes': filed,
        'asked_minutes': asked,
        'human_filed_minutes': human,
        'discarded_minutes': discarded,
        'total_minutes': total,
        'autonomy': (filed / total) if total else None,
    }


def summary(org_id: int, start: date, end: date) -> dict:
    """Everything the Accuracy tab shows, plus the sentence it leads with."""
    cov = coverage(org_id, start, end)
    samp = sampled_precision(org_id, start, end)
    human = human_correction_rate(org_id, start, end)
    fixed = self_correction_count(org_id, start, end)

    return {
        'period': {'start': start.isoformat(), 'end': end.isoformat()},
        'coverage': cov,
        'sampled': samp,
        'by_signal': by_signal(org_id, start, end),
        'human_corrections': human,
        'self_corrections': fixed,
        'headline': _headline(cov, samp, fixed),
    }


def _fmt_hours(minutes: int) -> str:
    h, m = divmod(int(minutes or 0), 60)
    if h and m:
        return f'{h}h {m}m'
    return f'{h}h' if h else f'{m}m'


def _headline(cov: dict, samp: dict, fixed: int) -> str:
    """The sentence. Says what we don't know as plainly as what we do.

    A bare "94% accurate" invites exactly one question — if you can find the
    errors, why did you make them — so the count of self-caught errors is part
    of the claim rather than a footnote. It turns a number into a track record.
    """
    filed = _fmt_hours(cov['filed_minutes'])
    asked = _fmt_hours(cov['asked_minutes'])

    if samp['precision'] is None:
        checked = 'No spot-check yet for this period'
    else:
        pct = round(samp['precision'] * 100)
        checked = (f"Spot-check says {pct}% correct "
                   f"({samp['correct']} of {samp['correct'] + samp['wrong']} decided")
        if samp['unverifiable']:
            checked += f", {samp['unverifiable']} unverifiable"
        checked += ')'

    parts = [f'We filed {filed} without asking', checked, f'We asked you about {asked}']
    if fixed:
        parts.append(f"We caught and fixed {fixed} of our own mistake{'s' if fixed != 1 else ''}")
    return '. '.join(parts) + '.'
