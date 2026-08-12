from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0142_calendarevent_availability'),
    ]

    operations = [
        migrations.AddField(
            model_name='workcalendar',
            name='avg_pto_days_per_year',
            field=models.DecimalField(
                max_digits=5, decimal_places=1, default=0,
                help_text='Average PTO/vacation days per person per year '
                          '(estimate). Pro-rated into capacity for people without '
                          'explicit TimeOff.',
            ),
        ),
    ]
