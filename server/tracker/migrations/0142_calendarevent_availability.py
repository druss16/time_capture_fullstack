from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0141_workcalendar_timeoff'),
    ]

    operations = [
        migrations.AddField(
            model_name='calendarevent',
            name='is_all_day',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='calendarevent',
            name='show_as',
            field=models.CharField(
                blank=True, default='', max_length=16,
                help_text='Graph showAs: free / tentative / busy / oof / workingElsewhere.',
            ),
        ),
    ]
