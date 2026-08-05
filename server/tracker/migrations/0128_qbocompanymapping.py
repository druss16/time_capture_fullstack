from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0127_organization_auto_confirm_client_attributions'),
    ]

    operations = [
        migrations.CreateModel(
            name='QboCompanyMapping',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('realm_id', models.CharField(db_index=True, help_text='QBO company id (realmId) from the qbo.currentcompanyid cookie', max_length=50)),
                ('suggested_name', models.CharField(blank=True, default='', help_text='Advisory best-guess company/client name shown in the mapping UI', max_length=255)),
                ('times_seen', models.PositiveIntegerField(default=0)),
                ('last_seen_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('client', models.ForeignKey(blank=True, help_text='Mapped client; null = unmapped / queued for review', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='qbo_company_mappings', to='tracker.client')),
                ('org', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='qbo_company_mappings', to='tracker.organization')),
            ],
        ),
        migrations.AddIndex(
            model_name='qbocompanymapping',
            index=models.Index(fields=['org', 'client'], name='tracker_qbo_org_id_client_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='qbocompanymapping',
            unique_together={('org', 'realm_id')},
        ),
    ]
