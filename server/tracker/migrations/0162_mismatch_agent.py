# Generated for the mismatch resolution agent.
#
# Adds the draft the agent writes onto a flag, plus the field that says who
# closed one. Additive only: every column is nullable or defaulted, so the
# backend can deploy before this is applied without 500ing the review tab.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0161_qb_company_client'),
    ]

    operations = [
        # The opt-in. Ships OFF: the agent drafts for everyone from day one,
        # but acts only where a human has decided its drafts have earned it.
        migrations.AddField(
            model_name='organization',
            name='mismatch_agent_autoresolve',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'When True, the mismatch resolution agent may ACT on its own '
                    'drafts for this org — re-filing a flagged block, or closing a '
                    'flag as a false alarm — but only above its confidence bar, only '
                    'with evidence independent of the window title, and never on a '
                    'same-family pair, an invoiced block, or a block a person set. '
                    'When False (default) the agent still drafts every flag with its '
                    'evidence; the drafts just wait for a human to approve them. Ship '
                    'it off, watch the drafts against what your reviewers actually '
                    'decide, and turn it on for a firm once its drafts have stopped '
                    'surprising you.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='mismatchflag',
            name='resolved_by',
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name='mismatchflag',
            name='agent_verdict',
            field=models.CharField(blank=True, max_length=24),
        ),
        migrations.AddField(
            model_name='mismatchflag',
            name='agent_target_client',
            field=models.ForeignKey(blank=True, null=True,
                                    on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='+', to='tracker.client'),
        ),
        migrations.AddField(
            model_name='mismatchflag',
            name='agent_confidence',
            field=models.FloatField(default=0.0),
        ),
        migrations.AddField(
            model_name='mismatchflag',
            name='agent_evidence',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='mismatchflag',
            name='agent_summary',
            field=models.CharField(blank=True, max_length=512),
        ),
        migrations.AddField(
            model_name='mismatchflag',
            name='agent_drafted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        # Choices-only changes. No SQL, but Django tracks them, and leaving
        # them out means the next `makemigrations` anyone runs emits a stray
        # migration for fields nobody touched.
        migrations.AlterField(
            model_name='block',
            name='categorized_by',
            field=models.CharField(
                blank=True, choices=[
                    ('ai', 'AI Auto-Categorized'), ('manual', 'User Manual Entry'),
                    ('correction', 'User Corrected AI'), ('import', 'Imported Data'),
                    ('pattern', 'Learned Pattern'), ('mismatch_agent', 'Mismatch Agent'),
                ], db_index=True,
                help_text='Source of the categorization', max_length=20, null=True),
        ),
        migrations.AlterField(
            model_name='block',
            name='state_changed_by',
            field=models.CharField(
                blank=True, choices=[
                    ('classifier', 'Auto-classified by ClassificationService'),
                    ('user', 'User confirmed via UI'),
                    ('user_edit', 'User edited and committed'),
                    ('admin_bulk', 'Admin bulk operation'),
                    ('auto_commit_eod', 'End-of-day auto-commit'),
                    ('rule', 'Org routing rule'),
                    ('correction', 'User corrected after commit'),
                    ('mismatch_agent', 'Mismatch resolution agent re-filed it'),
                ], max_length=30, null=True),
        ),
    ]
