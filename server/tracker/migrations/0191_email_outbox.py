from django.db import migrations, models


class Migration(migrations.Migration):
    """
    New tables only, no foreign keys — safe in the gap between Render deploying
    and migrating. Until this runs, the outbox cannot record anything, so
    email_service sends nothing (it fails closed).
    """

    dependencies = [
        ('tracker', '0190_qbt_timesheet_push'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailSendSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mode', models.CharField(choices=[('hold', 'Hold everything'), ('redirect', 'Send everything to me instead'), ('live', 'Live — send to real recipients')], default='hold', max_length=16)),
                ('redirect_to', models.EmailField(blank=True, default='', max_length=254)),
                ('live_types', models.JSONField(blank=True, default=list)),
                ('updated_by_id', models.IntegerField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'tracker_emailsendsettings',
            },
        ),
        migrations.CreateModel(
            name='OutboundEmail',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email_type', models.CharField(db_index=True, max_length=40)),
                ('to_email', models.CharField(max_length=254)),
                ('from_email', models.CharField(max_length=254)),
                ('from_name', models.CharField(blank=True, default='', max_length=120)),
                ('reply_to', models.CharField(blank=True, default='', max_length=254)),
                ('subject', models.CharField(max_length=500)),
                ('html_content', models.TextField()),
                ('plain_content', models.TextField(blank=True, default='')),
                ('categories', models.JSONField(blank=True, default=list)),
                ('org_id', models.IntegerField(blank=True, db_index=True, null=True)),
                ('org_name', models.CharField(blank=True, default='', max_length=255)),
                ('status', models.CharField(choices=[('held', 'Held'), ('sent', 'Sent'), ('redirected', 'Sent to test inbox'), ('failed', 'Failed'), ('discarded', 'Discarded')], db_index=True, default='held', max_length=16)),
                ('sent_to', models.CharField(blank=True, default='', max_length=254)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('sendgrid_status', models.IntegerField(blank=True, null=True)),
                ('error', models.TextField(blank=True, default='')),
                ('acted_by_id', models.IntegerField(blank=True, null=True)),
                ('dedupe_key', models.CharField(blank=True, max_length=80, null=True, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                'db_table': 'tracker_outboundemail',
                'ordering': ['-created_at'],
            },
        ),
    ]
