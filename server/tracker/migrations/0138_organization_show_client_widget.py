from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0137_alter_costtier_bill_rate_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='show_client_widget',
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Vendor-controlled (MavOps staff only). When False (default), the "
                    "desktop agent hides the floating client ticker AND disables all "
                    "manual client-switching (widget click + tray Search/Switch Client), "
                    "so the client experience is fully hands-off — attribution runs "
                    "silently server-side. Flip on per-org (e.g. a demo org) to show the "
                    "file-open→client ticker for sales demos. Client owners/admins cannot "
                    "change this; it is not exposed in the client Settings UI."
                ),
            ),
        ),
    ]
