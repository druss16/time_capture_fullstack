"""
Migration 0150 — fields that tell two same-named matters apart.

Two matters for one client routinely share a description; "Estate Planning"
twice for the same family is ordinary practice. The matter picker was offering
two identical-looking rows, which makes choosing a guess rather than a decision.

open_date, responsible_attorney and practice_area are what a lawyer actually
uses to tell them apart. All three verified against the live Clio API before
being added — Clio 400s on an unknown field, so a wrong name here would have
broken matter sync entirely rather than degrading it.

Additive and defaulted, on a table only the Clio integration writes. Safe to
apply before the code deploys, same ordering as 0147 and 0148.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0149_qb_vendor_client'),
    ]

    operations = [
        migrations.AddField(
            model_name='externalmattermapping',
            name='open_date',
            field=models.DateField(
                blank=True, null=True,
                help_text='When the matter was opened. Usually the fastest way to tell '
                          'two same-named matters apart.',
            ),
        ),
        migrations.AddField(
            model_name='externalmattermapping',
            name='responsible_attorney',
            field=models.CharField(
                blank=True, default='', max_length=255,
                help_text='Name of the attorney responsible for the matter in Clio.',
            ),
        ),
        migrations.AddField(
            model_name='externalmattermapping',
            name='practice_area',
            field=models.CharField(
                blank=True, default='', max_length=128,
                help_text='Clio practice area, when the firm uses them.',
            ),
        ),
    ]
