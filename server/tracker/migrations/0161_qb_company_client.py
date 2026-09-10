"""Which client a QuickBooks company name belongs to, stated by the firm.

Additive: one new table, no changes to existing columns, so applying it late
cannot break a running deploy. See tracker.models.QBCompanyClient for why this
is not stored in Client.aliases.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0160_wip_auto_relief_default_on'),
    ]

    operations = [
        migrations.CreateModel(
            name='QBCompanyClient',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('company_name', models.CharField(
                    help_text="Company Name exactly as QuickBooks Desktop shows it in "
                              "the title bar, before the ' - QuickBooks ...' chrome.",
                    max_length=255)),
                ('company_key', models.CharField(
                    help_text='Normalized company_name, for matching. Written by save().',
                    max_length=255)),
                ('source', models.CharField(
                    default='import',
                    help_text="import = the firm's Customer/Company list; confirmed = a "
                              "person picked this client for this company.",
                    max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('client', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='qb_companies', to='tracker.client')),
                ('org', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='qb_company_clients', to='tracker.organization')),
            ],
        ),
        migrations.AlterUniqueTogether(
            name='qbcompanyclient',
            unique_together={('org', 'company_key')},
        ),
    ]
