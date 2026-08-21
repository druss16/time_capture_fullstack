# Hand-written: the local container bind-mounts the MAIN checkout's server/,
# so `makemigrations` there reads main's models and writes into main. It also
# currently wants to emit unrelated ExternalMatterMapping index renames, which
# must not ride along in this migration.
from django.db import migrations, models


def backfill(apps, schema_editor):
    """Fill the new columns for samples drawn before they existed.

    Without this the work list puts every already-drawn block in one blank
    bucket, which is the exact opposite of the point — and a real sample was
    already drawn and half-judged before this migration was written.

    filed_by_signal is recovered from each block's classification audit, the
    same source the draw path now reads. Category and billable are read off the
    block as it stands today: they are context for a judge, not verdicts, and
    today's value is far better than blank.
    """
    AccuracySample = apps.get_model('tracker', 'AccuracySample')
    ClassificationAudit = apps.get_model('tracker', 'ClassificationAudit')
    Block = apps.get_model('tracker', 'Block')

    from tracker.services.accuracy import CLIENT_SIGNAL_PRIORITY, _signals_of

    pending = list(AccuracySample.objects.filter(filed_by_signal='')
                   .values_list('id', 'block_id'))
    if not pending:
        return

    block_ids = [b for _, b in pending]

    audits = {}
    for bid, src, ms in (ClassificationAudit.objects
                         .filter(block_id__in=block_ids)
                         .order_by('-created_at')
                         .values_list('block_id', 'source', 'matched_signals')):
        audits.setdefault(bid, []).append((src, ms))

    blocks = {b.id: b for b in Block.objects.filter(id__in=block_ids)
              .only('id', 'is_billable', 'category_hours')}

    for sample_id, block_id in pending:
        present, source = set(), ''
        for src, ms in audits.get(block_id, []):
            source = source or (src or '')
            for e in _signals_of(ms):
                if e.get('type'):
                    present.add(e['type'])
        signal = next((n for n in CLIENT_SIGNAL_PRIORITY if n in present),
                      f'source:{source}' if source else 'unknown')

        b = blocks.get(block_id)
        # Dominant category, inlined: the service helper is not importable
        # against a historical model.
        category = ''
        if b is not None and isinstance(getattr(b, 'category_hours', None), dict) and b.category_hours:
            category = max(b.category_hours.items(), key=lambda kv: kv[1] or 0)[0] or ''

        AccuracySample.objects.filter(id=sample_id).update(
            filed_by_signal=signal,
            booked_category=category[:64],
            booked_is_billable=(b.is_billable if b is not None else None),
        )


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0152_accuracy_sample'),
    ]

    operations = [
        migrations.AddField(
            model_name='accuracysample',
            name='verdict_category',
            field=models.CharField(
                choices=[('pending', 'Not yet adjudicated'),
                         ('correct', 'Filed to the right client'),
                         ('wrong', 'Filed to the wrong client'),
                         ('unverifiable', 'No evidence either way')],
                default='pending', max_length=14),
        ),
        migrations.AddField(
            model_name='accuracysample',
            name='verdict_billable',
            field=models.CharField(
                choices=[('pending', 'Not yet adjudicated'),
                         ('correct', 'Filed to the right client'),
                         ('wrong', 'Filed to the wrong client'),
                         ('unverifiable', 'No evidence either way')],
                default='pending', max_length=14),
        ),
        migrations.AddField(
            model_name='accuracysample',
            name='filed_by_signal',
            field=models.CharField(blank=True, db_index=True, default='', max_length=48),
        ),
        migrations.AddField(
            model_name='accuracysample',
            name='booked_category',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='accuracysample',
            name='booked_is_billable',
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
