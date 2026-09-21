"""Drop OrgInstallToken, the install token no endpoint accepted.

The model minted a `tt_org_...` value at signup and Settings offered a tab to
view and regenerate it, describing it as the token that links devices to the
organization. Nothing on the server ever validated one. Its only reader was
POST /agent/register/, which raised TypeError on `user.groups.add(org)`
before it got as far as the lookup, and 0168 removed that view along with the
table it wrote to.

Bulk enrollment is OrgDeploymentToken, a separate namespace: the
`ODT-XXXX-XXXX` the MSI takes as /org_token=, that mdm_deploy.py redeems at
/api/deploy/auto-pair/ -> claim -> confirm-user, and that Settings -> MDM
Deploy issues, meters and revokes. That path is untouched here.

Checked read-only against the live database before writing this: one row, on
the vendor's own org (17, 'mavops'), created 2026-02-03 and never redeemed by
anything. The two orgs with live machines have 65 devices between them, none
of them paired by this table. Dropping it destroys that single inert string;
the firm loses no way of pairing a machine, because it never had one here.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0168_drop_agent_registration'),
    ]

    operations = [
        migrations.DeleteModel(name='OrgInstallToken'),
    ]
