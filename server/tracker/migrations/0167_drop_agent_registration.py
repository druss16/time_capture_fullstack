"""Drop AgentRegistration, the second "installed agent" table.

It duplicated AgentDevice — its own agent_key, is_active and machine_name —
and nothing ever read any of them. AgentKeyAuthentication has always
authenticated agents against AgentDevice, so a key issued here authenticated
nothing and clearing is_active here stopped no machine.

Its only writer was POST /agent/register/, which raised TypeError on
`user.groups.add(org)` (Organization is not a Group) before reaching its own
write. The table therefore held zero rows in production for its entire life,
which is what makes this a plain DeleteModel with no data step: verified
against the live database before writing this migration, and the reverse is
an empty table either way.

Its one consumer was the onboarding `agent_installed` step, which now reads
AgentDevice — so that step stops reporting False for firms whose machines
have been running all along.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0166_encrypt_oauth_tokens'),
    ]

    operations = [
        migrations.DeleteModel(name='AgentRegistration'),
    ]
