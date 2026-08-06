from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0128_qbocompanymapping'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='mavops_archived',
            field=models.BooleanField(default=False),
        ),
    ]
