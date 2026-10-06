from django.db import migrations, models


class Migration(migrations.Migration):
    """
    New table only, no foreign keys — safe in the gap between Render deploying
    and migrating. Until this runs, emails to a company are held (the outbox
    cannot tell whether the company has its own setting, so it does not send).
    """

    dependencies = [
        ('tracker', '0192_email_outbox'),
    ]

    operations = [
        migrations.CreateModel(
            name='OrgEmailSetting',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('org_id', models.IntegerField(unique=True)),
                ('mode', models.CharField(choices=[('hold', 'Hold everything'), ('redirect', 'Send everything to me instead'), ('live', 'Live — send to real recipients')], max_length=16)),
                ('updated_by_id', models.IntegerField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'tracker_orgemailsetting',
            },
        ),
    ]
