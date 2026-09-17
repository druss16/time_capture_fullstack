"""Encryption of the OAuth token columns.

Pure functions and a field class — no database, so this runs under
SimpleTestCase.

The properties worth protecting are not "it encrypts". They are the ones that
decide whether a deploy is safe: rows written before encryption existed must
still be readable, a missing key must degrade rather than disconnect every
firm, and a value that cannot be decrypted must never be handed to a provider
as if it were a credential.
"""
from cryptography.fernet import Fernet
from django.test import SimpleTestCase, override_settings

from tracker import crypto_fields as cf

KEY_A = Fernet.generate_key().decode()
KEY_B = Fernet.generate_key().decode()
TOKEN = 'M.C123_BAY.0.U.-ClNYQ_a_real_looking_refresh_token'


class CryptoTestCase(SimpleTestCase):
    def setUp(self):
        cf._cipher_cache.clear()

    def tearDown(self):
        cf._cipher_cache.clear()


@override_settings(TOKEN_ENCRYPTION_KEYS=[KEY_A])
class RoundTripTests(CryptoTestCase):
    def test_ciphertext_does_not_contain_the_token(self):
        self.assertNotIn(TOKEN, cf.encrypt(TOKEN))

    def test_decrypt_recovers_the_original(self):
        self.assertEqual(cf.decrypt(cf.encrypt(TOKEN)), TOKEN)

    def test_encrypting_twice_does_not_double_wrap(self):
        once = cf.encrypt(TOKEN)
        self.assertEqual(cf.encrypt(once), once)

    def test_empty_and_none_are_left_alone(self):
        for value in ('', None):
            self.assertEqual(cf.encrypt(value), value)
            self.assertEqual(cf.decrypt(value), value)


@override_settings(TOKEN_ENCRYPTION_KEYS=[KEY_A])
class LegacyPlaintextTests(CryptoTestCase):
    def test_rows_written_before_encryption_still_read(self):
        # The deploy-safety property: without this, shipping the field would
        # disconnect every integration in the fleet at once.
        self.assertEqual(cf.decrypt(TOKEN), TOKEN)


class KeyRotationTests(CryptoTestCase):
    def test_old_ciphertext_survives_a_new_primary_key(self):
        with override_settings(TOKEN_ENCRYPTION_KEYS=[KEY_A]):
            old = cf.encrypt(TOKEN)
        cf._cipher_cache.clear()
        with override_settings(TOKEN_ENCRYPTION_KEYS=[KEY_B, KEY_A]):
            self.assertEqual(cf.decrypt(old), TOKEN)

    def test_dropping_the_old_key_breaks_only_unconverted_rows(self):
        with override_settings(TOKEN_ENCRYPTION_KEYS=[KEY_A]):
            old = cf.encrypt(TOKEN)
        cf._cipher_cache.clear()
        with override_settings(TOKEN_ENCRYPTION_KEYS=[KEY_B]):
            # Empty, never the raw ciphertext: the integration reconnects
            # instead of sending gibberish as a bearer token.
            self.assertEqual(cf.decrypt(old), '')


class MissingKeyTests(CryptoTestCase):
    @override_settings(TOKEN_ENCRYPTION_KEYS=[])
    def test_writes_degrade_to_plaintext_rather_than_failing(self):
        # A deploy that loses the env var must not take every integration
        # offline — that is a worse outcome than the plaintext it replaces.
        self.assertEqual(cf.encrypt(TOKEN), TOKEN)

    def test_encrypted_rows_read_empty_without_a_key(self):
        with override_settings(TOKEN_ENCRYPTION_KEYS=[KEY_A]):
            encrypted = cf.encrypt(TOKEN)
        cf._cipher_cache.clear()
        with override_settings(TOKEN_ENCRYPTION_KEYS=[]):
            self.assertEqual(cf.decrypt(encrypted), '')


@override_settings(TOKEN_ENCRYPTION_KEYS=[KEY_A])
class FieldTests(CryptoTestCase):
    def setUp(self):
        super().setUp()
        self.field = cf.EncryptedTextField()

    def test_value_is_encrypted_on_the_way_to_the_database(self):
        self.assertTrue(self.field.get_prep_value(TOKEN).startswith(cf.FERNET_PREFIX))

    def test_value_is_decrypted_on_the_way_back(self):
        stored = self.field.get_prep_value(TOKEN)
        self.assertEqual(self.field.from_db_value(stored, None, None), TOKEN)

    def test_legacy_plaintext_column_reads_through_the_field(self):
        self.assertEqual(self.field.from_db_value(TOKEN, None, None), TOKEN)
