from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0129_organization_mavops_archived'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='seat_grace_deadline',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='agentdevice',
            name='deactivated_reason',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
    ]
