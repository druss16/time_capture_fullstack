from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0124_organization_sandwich_correlation_enabled'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='auto_confirm_name_matches',
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Auto-confirm (commit) a proposed block when the block's own "
                    "text literally names the client — a window-title alias, file "
                    "path, or domain match — and no other client competes. Converts "
                    "the 'almost a literal match' proposal pile (e.g. 'Sacred Heart "
                    "Basilica - QuickBooks…') into committed billable time with zero "
                    "clicks. Only name-bearing evidence qualifies: email/calendar/"
                    "temporal/AI-only guesses (e.g. a shared inbox routed by subject) "
                    "still surface for human review. Same-family collisions never "
                    "reach here — Stage 3 abstains on ties. Enable per-org once "
                    "attribution accuracy is trusted."
                ),
            ),
        ),
    ]
