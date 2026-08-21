# Hand-written: the local container bind-mounts the MAIN checkout's server/,
# so `makemigrations` there would read main's models and write into main.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('tracker', '0151_clio_push_trigger'),
    ]

    operations = [
        migrations.CreateModel(
            name='AccuracySample',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('period_start', models.DateField()),
                ('period_end', models.DateField()),
                ('drawn_at', models.DateTimeField(auto_now_add=True)),
                ('minutes', models.IntegerField(default=0)),
                ('verdict', models.CharField(
                    choices=[('pending', 'Not yet adjudicated'),
                             ('correct', 'Filed to the right client'),
                             ('wrong', 'Filed to the wrong client'),
                             ('unverifiable', 'No evidence either way')],
                    db_index=True, default='pending', max_length=14)),
                ('note', models.TextField(blank=True, default='')),
                ('adjudicated_at', models.DateTimeField(blank=True, null=True)),
                ('adjudicated_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='accuracy_adjudications', to=settings.AUTH_USER_MODEL)),
                ('block', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='accuracy_samples', to='tracker.block')),
                ('booked_client', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='accuracy_samples_booked', to='tracker.client')),
                ('correct_client', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    help_text='Where it should have gone, when the verdict is "wrong".',
                    related_name='accuracy_samples_corrected', to='tracker.client')),
                ('org', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='accuracy_samples', to='tracker.organization')),
            ],
            options={'ordering': ['verdict', 'drawn_at']},
        ),
        migrations.AddIndex(
            model_name='accuracysample',
            index=models.Index(fields=['org', 'period_start', 'verdict'],
                               name='accsample_org_period_idx'),
        ),
        migrations.AddIndex(
            model_name='accuracysample',
            index=models.Index(fields=['org', 'drawn_at'], name='accsample_org_drawn_idx'),
        ),
        migrations.AddConstraint(
            model_name='accuracysample',
            constraint=models.UniqueConstraint(
                fields=('block', 'period_start', 'period_end'),
                name='uniq_accuracy_sample_block_period'),
        ),
    ]
