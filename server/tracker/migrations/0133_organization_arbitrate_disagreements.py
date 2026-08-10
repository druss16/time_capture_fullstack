from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0132_organization_target_utilization'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='arbitrate_disagreements',
            field=models.BooleanField(
                default=False,
                help_text=(
                    "When True, and the backend classifier disagrees with the agent's "
                    "attribution, resolve by evidence in the block's own window title "
                    "instead of always keeping the agent's pick: if exactly one side's "
                    "client name literally appears in the title, that side wins; if "
                    "neither is evidenced by the title, the block is left 'proposed' "
                    "(not auto-committed) so it goes to Daily Review rather than billing "
                    "a no-evidence guess. Same-family (church/cemetery) ties still keep "
                    "the agent's pick + disagreement flag. Default off; enable per-org "
                    "after validating against ai_disagrees_with_agent history."
                ),
            ),
        ),
    ]
