from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0072_client_xero_tenant_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='block',
            name='needs_review',
            field=models.BooleanField(
                default=False,
                db_index=True,
                help_text='Flagged for manual review — timer vs calendar discrepancy or unusual duration',
            ),
        ),
        migrations.AddField(
            model_name='block',
            name='review_reason',
            field=models.CharField(
                max_length=500,
                blank=True,
                default='',
                help_text='Human-readable reason why this entry was flagged for review',
            ),
        ),
    ]