"""Rejoin two migration branches that both forked off 0167.

WHAT HAPPENED
-------------
Two PRs were open at once. Each added a migration on top of 0167_clio_webhook,
neither could see the other, and both merged. The graph ended up with two
leaves:

    0167_clio_webhook
    ├── 0168_client_created_at              (PR #560)
    └── 0168_drop_agent_registration
        └── 0169_drop_org_install_token     (the other branch)

Django refuses to migrate at all in that state:

    CommandError: Conflicting migrations detected; multiple leaf nodes in the
    migration graph: (0168_client_created_at, 0169_drop_org_install_token)

Note what that means — it is not "the new migration fails". EVERY migrate
fails, including one a deploy runs for something unrelated. So this is not
cosmetic tidying; main could not migrate until this landed.

WHY AN EMPTY MIGRATION FIXES IT
-------------------------------
Nothing needs undoing. The two branches touch unrelated tables (a column on
client; two dropped models), so they commute — applying them in either order
gives the same schema. The only problem was that Django had no single node to
call "latest". This provides one by depending on both. It runs no SQL.

Safe to apply in any state: the other branch is already applied in production
and 0168_client_created_at is not, and a merge migration does not care.

AVOIDING THE NEXT ONE
---------------------
Two concurrent PRs each adding a migration will collide again — the numbering
is a shared namespace and neither branch can see the other. Before opening a
PR with a migration, rebase on main and check nothing has taken the number.
The other branch had already renumbered once for exactly this reason (commit
90825aca, "Renumber to 0168: main landed its own 0167").
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0168_client_created_at'),
        ('tracker', '0169_drop_org_install_token'),
    ]

    operations = []
