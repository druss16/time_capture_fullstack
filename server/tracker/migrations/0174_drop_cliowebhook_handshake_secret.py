"""Drop ClioWebhook.handshake_secret — the question it hedged against is answered.

The field existed because Clio's documentation describes TWO secrets — one you
supply when creating a subscription, and one Clio generates during the
X-Hook-Secret handshake — without stating which actually signs the callbacks.
Guessing wrong meant every delivery failing its signature check, which is
indistinguishable from an attack in the logs, so both were stored and either
was accepted.

The first real callback settled it: it verified against the secret WE supplied,
first try, with rejected_count at zero. The second key was never used.

The handshake itself is untouched and still required — echoing X-Hook-Secret
back is what activates the subscription. Only the storing of that value as a
signing key goes.

Dropping a column of encrypted secrets is not reversible in any meaningful
sense, and should not be: the values were never used to verify anything, and
re-adding the column would give back an empty field rather than the old
secrets. A new subscription mints a fresh secret anyway.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0173_cliowebhook_rejected'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='cliowebhook',
            name='handshake_secret',
        ),
    ]
