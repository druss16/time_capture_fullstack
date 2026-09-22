"""Put handshake_secret back. 0174 was wrong and broke webhook delivery.

WHAT HAPPENED
-------------
0174 dropped this column on the reasoning that Clio signs callbacks with the
`shared_secret` we supply at creation, so the secret Clio hands over in the
X-Hook-Secret handshake was dead weight.

That reasoning was wrong, and the evidence for it was misread. The one real
callback we had seen arrived AFTER the handshake had already stored Clio's
secret, at a point where verify_signature accepted either key. rejected_count
staying at zero proved one of them matched — not which one. It was treated as
proof of the shared_secret, which it never was.

The next real callback settled it properly: rejected_count went to 1 with
"signature did not match either stored secret". Clio signs with the HANDSHAKE
secret.

WHY THIS MIGRATION IS NOT ENOUGH ON ITS OWN
-------------------------------------------
Re-adding the column gives back an EMPTY field. The secret Clio issued is gone
— it was dropped with the column and Clio does not re-send it on request. The
subscription therefore cannot be verified again until a FRESH handshake runs,
which only happens when a subscription is created (or its URL changes).

So after this deploys, the firm's Clio connection must be disconnected and
reconnected. That deregisters the old subscriptions, creates new ones, and
Clio issues a new handshake secret — which we will now keep.

The hourly sweep covers the gap in the meantime: nothing is lost, new clients
just arrive within the hour instead of within seconds.
"""
from django.db import migrations

import tracker.crypto_fields


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0174_drop_cliowebhook_handshake_secret'),
    ]

    operations = [
        migrations.AddField(
            model_name='cliowebhook',
            name='handshake_secret',
            field=tracker.crypto_fields.EncryptedTextField(blank=True, default=''),
        ),
    ]
