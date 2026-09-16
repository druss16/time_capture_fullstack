# BillingDecision, removed the day after it landed.
#
# It stored what the firm decided to charge a client for a period. The intent
# was that the Fees page would become a worklist a partner works through — and
# the partner does not work a list. He opens QuickBooks, looks up what went
# into one account, arrives at a number and invoices it there. Recording that
# number back here was data entry that made the product feel complete and made
# him slower, so the page went back to being a reference and this went with it.
#
# Nothing to preserve: the table never held a row outside a test database.
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [("tracker", "0164_billing_decision")]

    operations = [
        migrations.RemoveConstraint(
            model_name="billingdecision",
            name="uniq_billing_decision_client_period",
        ),
        migrations.RemoveIndex(
            model_name="billingdecision",
            name="tracker_bil_org_id_2c0bca_idx",
        ),
        migrations.DeleteModel(name="BillingDecision"),
    ]
