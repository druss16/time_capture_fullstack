from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0200_asana_qbt_ref'),
    ]

    operations = [
        migrations.AddField(
            model_name='agentdevice',
            name='ax_switch',
            field=models.CharField(blank=True, default='', max_length=3),
        ),
        migrations.AddField(
            model_name='agentdevice',
            name='ax_switch_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
