"""
Add Client.alias_sources (provenance map for aliases) and backfill it.

alias_sources maps {alias_lower: 'derived'|'manual'} in parallel to the flat
`aliases` list. It lets heal_ambiguous_aliases remove ONLY auto-derived
aliases that later collide with a sibling client, while never touching
hand-entered ones.

Backfill heuristic for existing aliases (which predate provenance): an alias
is marked 'derived' if the deriver would generate it from the client's name
or email; otherwise 'manual'. This is deliberately conservative — anything
the algorithm couldn't have produced is treated as manual and thus protected.
"""

from django.db import migrations, models


def backfill_alias_sources(apps, schema_editor):
    Client = apps.get_model("tracker", "Client")
    # Pure, DB-free helpers — safe to import in a migration.
    from tracker.services.alias_derivation import _candidates, _email_candidates

    to_update = []
    for client in Client.objects.exclude(aliases=[]).iterator():
        aliases = client.aliases or []
        if not aliases:
            continue
        name = client.name or ""
        email = getattr(client, "email", "") or ""
        derivable = {a.lower() for a, _ in _candidates(name)}
        derivable |= {a.lower() for a, _ in _email_candidates(email)}

        sources = {}
        for a in aliases:
            if not isinstance(a, str):
                continue
            key = a.lower()
            sources[key] = "derived" if key in derivable else "manual"

        client.alias_sources = sources
        to_update.append(client)

    Client.objects.bulk_update(to_update, ["alias_sources"], batch_size=500)


def noop_reverse(apps, schema_editor):
    # Field is dropped on reverse; nothing else to undo.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0125_organization_auto_confirm_name_matches"),
    ]

    operations = [
        migrations.AddField(
            model_name="client",
            name="alias_sources",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "Provenance map {alias_lower: 'derived'|'manual'} paralleling "
                    "`aliases`. Lets the ambiguity self-heal remove only auto-derived "
                    "aliases that later collide with a sibling client — manual and "
                    "unmarked (legacy) aliases are never auto-removed. Not read by the "
                    "classifier; `aliases` remains the flat string list Stage 3 uses."
                ),
            ),
        ),
        migrations.RunPython(backfill_alias_sources, noop_reverse),
    ]
