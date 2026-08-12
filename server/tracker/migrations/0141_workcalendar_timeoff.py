import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('tracker', '0140_costtier_target_utilization'),
    ]

    operations = [
        migrations.CreateModel(
            name='WorkCalendar',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('hours_per_day', models.DecimalField(decimal_places=2, default=8, max_digits=4, help_text='Standard working hours in a full working day.')),
                ('working_weekdays', models.JSONField(default=list, help_text='Weekday ints that are working days (Mon=0 … Sun=6). Default [0,1,2,3,4].')),
                ('summer_fridays_off', models.BooleanField(default=False, help_text='If set, Fridays in the summer month range are non-working.')),
                ('summer_start_month', models.PositiveSmallIntegerField(default=6)),
                ('summer_end_month', models.PositiveSmallIntegerField(default=8)),
                ('holidays', models.JSONField(blank=True, default=list, help_text='Firm holiday dates as ["YYYY-MM-DD", ...] — non-working for everyone.')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('org', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='work_calendar', to='tracker.organization')),
            ],
        ),
        migrations.CreateModel(
            name='TimeOff',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('start_date', models.DateField()),
                ('end_date', models.DateField()),
                ('kind', models.CharField(choices=[('pto', 'PTO / Vacation'), ('sick', 'Sick'), ('holiday', 'Holiday'), ('other', 'Other')], default='pto', max_length=16)),
                ('source', models.CharField(choices=[('manual', 'Manual'), ('calendar', 'Calendar-derived')], default='manual', max_length=16)),
                ('external_id', models.CharField(blank=True, db_index=True, default='', max_length=255)),
                ('note', models.CharField(blank=True, default='', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('org', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='time_off', to='tracker.organization')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='time_off', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddIndex(
            model_name='timeoff',
            index=models.Index(fields=['org', 'user', 'start_date', 'end_date'], name='tracker_tim_org_id_user_idx'),
        ),
    ]
