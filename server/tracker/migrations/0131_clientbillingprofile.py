from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('tracker', '0130_seat_overage_grace'),
    ]

    operations = [
        migrations.CreateModel(
            name='ClientBillingProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('billing_type', models.CharField(choices=[('hourly', 'Hourly'), ('flat_fee', 'Flat fee / retainer'), ('non_billable', 'Non-billable')], default='hourly', help_text='How this client is billed. Drives whether the export carries hours×rate, a flat fee, or nothing.', max_length=20)),
                ('flat_amount', models.DecimalField(blank=True, decimal_places=2, help_text='Fee amount when billing_type is flat_fee.', max_digits=12, null=True)),
                ('flat_period', models.CharField(blank=True, choices=[('monthly', 'Monthly'), ('quarterly', 'Quarterly'), ('annual', 'Annual'), ('per_project', 'Per project')], default='', help_text='Billing cadence for the flat fee.', max_length=20)),
                ('billing_system', models.CharField(choices=[('qb_desktop', 'QuickBooks Desktop'), ('qbo', 'QuickBooks Online'), ('xero', 'Xero'), ('csv_other', 'CSV / other')], default='csv_other', max_length=20)),
                ('external_customer_id', models.CharField(blank=True, default='', help_text='Customer/Job ID in the billing system (e.g. QB "Customer:Job"). Falls back to Client.quickbooks_id.', max_length=100)),
                ('external_customer_name', models.CharField(blank=True, default='', help_text='Customer/Job display name in the billing system, for export readability.', max_length=255)),
                ('default_item_name', models.CharField(blank=True, default='', help_text='Default service/item on exported line items when a task type has no specific mapping.', max_length=255)),
                ('notes', models.TextField(blank=True, default='')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('client', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='billing_profile', to='tracker.client')),
                ('org', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='client_billing_profiles', to='tracker.organization')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
