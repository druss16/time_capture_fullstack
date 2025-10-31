from django.db import migrations, models
import django.db.models.functions as dbf
from django.db.models.functions import Lower



class Migration(migrations.Migration):
    dependencies = [
        ('tracker', '0010_rawevent_ctx_alter_block_hints'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="client",
            constraint=models.UniqueConstraint(
                Lower("name"), "org",
                name="uniq_client_org_lowername",
            ),
        ),
        migrations.AddConstraint(
            model_name="project",
            constraint=models.UniqueConstraint(
                Lower("name"), "org", "client",
                name="uniq_project_org_client_lowername",
            ),
        ),
    ]
