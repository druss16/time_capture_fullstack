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

    from tracker.models import Block
    rows = []
    for b in Block.objects.filter(id__in=chosen_ids).only('id', 'client_id', 'minutes', 'org_id'):
        rows.append(AccuracySample(
            org_id=org_id, block_id=b.id,
            period_start=start, period_end=end,
            booked_client_id=b.client_id,
            minutes=b.minutes or 0,
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


def sampled_precision(org_id: int, start: date, end: date) -> dict:
    """The headline: what the random sample says, with its uncertainty."""
    from tracker.models import AccuracySample

    samples = list(
        AccuracySample.objects
        .filter(org_id=org_id, period_start=start, period_end=end)
        .values('verdict', 'minutes')
    )
    counts = {'pending': 0, 'correct': 0, 'wrong': 0, 'unverifiable': 0}
    wrong_minutes = 0
    for s in samples:
        counts[s['verdict']] = counts.get(s['verdict'], 0) + 1
        if s['verdict'] == 'wrong':
            wrong_minutes += s['minutes'] or 0

    decided = counts['correct'] + counts['wrong']
    lo, hi = wilson_interval(counts['correct'], decided)

    # Two readings, because "unverifiable" must not quietly count as correct.
    # The optimistic one ignores them; the floor assumes every one is wrong.
    # The gap between the two IS the cost of blocks that carry no evidence.
    adjudicated = decided + counts['unverifiable']
    return {
        'drawn': len(samples),
        'pending': counts['pending'],
        'correct': counts['correct'],
        'wrong': counts['wrong'],
        'unverifiable': counts['unverifiable'],
        'precision': (counts['correct'] / decided) if decided else None,
        'ci_low': lo if decided else None,
        'ci_high': hi if decided else None,
        'worst_case': (counts['correct'] / adjudicated) if adjudicated else None,
        'wrong_minutes': wrong_minutes,
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
