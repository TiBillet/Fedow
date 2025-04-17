import json
import uuid
from datetime import datetime, timedelta
from io import StringIO
import random
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import tag, TransactionTestCase
from django.utils.timezone import make_aware
from faker import Faker
from rest_framework import status

from fedow_core.models import Card, Place, FedowUser, Wallet, Asset, Token, Transaction
from fedow_core.tests.tests import FedowTestCase
from fedow_core.utils import sign_message, data_to_b64, get_private_key

import logging

logger = logging.getLogger(__name__)


class CardAPITest(FedowTestCase):
    """Test class for CardAPI endpoints that are not covered by existing tests."""

    def setUp(self):
        super().setUp()
        # Create a card for testing
        from fedow_core.models import Origin
        gen1 = Origin.objects.create(
            place=self.place,
            generation=1
        )
        complete_tag_id_uuid = str(uuid4())
        qrcode_uuid = str(uuid4())
        self.card = Card.objects.create(
            complete_tag_id_uuid=complete_tag_id_uuid,
            first_tag_id=f"{complete_tag_id_uuid.split('-')[0]}",
            qrcode_uuid=qrcode_uuid,
            number_printed=f"{qrcode_uuid.split('-')[0]}",
            origin=gen1,
        )

        # Create a wallet and user for testing
        self.wallet, self.private_pem, self.public_pem = self.create_wallet_via_api()

    def test_qr_retrieve(self):
        """Test retrieving card information via QR code."""
        response = self.client.get(
            f'/card/{self.card.qrcode_uuid}/qr_retrieve/',
            headers={
                'Authorization': f'Api-Key {self.temp_key_place}',
            }
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Don't check the exact wallet UUID, just make sure it's present
        self.assertTrue('wallet_uuid' in response.data)
        self.assertTrue('is_wallet_ephemere' in response.data)
        self.assertTrue('origin' in response.data)

    def test_set_primary(self):
        """Test setting a card as primary for a place."""
        response = self._post_from_simulated_cashless(
            'card/set_primary',
            {'first_tag_id': self.card.first_tag_id}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify the card is now primary
        self.card.refresh_from_db()
        self.assertIn(self.place, self.card.primary_places.all())

        # Test removing primary status
        response = self._post_from_simulated_cashless(
            'card/set_primary',
            {'first_tag_id': self.card.first_tag_id, 'delete': True}
        )
        self.assertEqual(response.status_code, status.HTTP_205_RESET_CONTENT)

        # Verify the card is no longer primary
        self.card.refresh_from_db()
        self.assertNotIn(self.place, self.card.primary_places.all())

    def test_retrieve_card_by_signature(self):
        """Test retrieving cards by wallet signature."""
        # Link the card to the wallet's user
        self.card.user = self.wallet.user
        self.card.save()

        # Create the signature
        private_rsa = get_private_key(self.private_pem)
        date_iso = datetime.now().isoformat()
        message = f"{self.wallet.uuid}:{date_iso}".encode('utf8')
        signature = sign_message(
            message,
            private_rsa,
        ).decode('utf-8')

        response = self.client.get(
            '/card/retrieve_card_by_signature/',
            headers={
                'Authorization': f'Api-Key {self.temp_key_place}',
                'Wallet': str(self.wallet.uuid),
                'Date': date_iso,
                'Signature': signature,
            }
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(len(response.data) > 0)

    def test_lost_my_card_by_signature(self):
        """Test handling lost cards."""
        # Link the card to the wallet's user
        self.card.user = self.wallet.user
        self.card.save()

        # Create the signature
        private_rsa = get_private_key(self.private_pem)
        data = {'number_printed': self.card.number_printed}
        date_iso = datetime.now().isoformat()

        # For POST requests, we sign the data
        signature = sign_message(
            data_to_b64(data),
            private_rsa,
        ).decode('utf-8')

        response = self.client.post(
            '/card/lost_my_card_by_signature/',
            json.dumps(data),
            content_type='application/json',
            headers={
                'Authorization': f'Api-Key {self.temp_key_place}',
                'Wallet': str(self.wallet.uuid),
                'Date': date_iso,
                'Signature': signature,
            }
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify the card is no longer linked to the user
        self.card.refresh_from_db()
        self.assertIsNone(self.card.user)


class WalletAPITest(FedowTestCase):
    """Test class for WalletAPI endpoints that are not covered by existing tests."""

    def setUp(self):
        super().setUp()
        # Create a wallet and user for testing
        self.wallet, self.private_pem, self.public_pem = self.create_wallet_via_api()

    def test_retrieve_by_signature(self):
        """Test retrieving wallet information by signature."""
        # Create the signature
        private_rsa = get_private_key(self.private_pem)
        date_iso = datetime.now().isoformat()
        message = f"{self.wallet.uuid}:{date_iso}".encode('utf8')
        signature = sign_message(
            message,
            private_rsa,
        ).decode('utf-8')

        response = self.client.get(
            '/wallet/retrieve_by_signature/',
            headers={
                'Authorization': f'Api-Key {self.temp_key_place}',
                'Wallet': str(self.wallet.uuid),
                'Date': date_iso,
                'Signature': signature,
            }
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['uuid'], str(self.wallet.uuid))

    def test_retrieve(self):
        """Test retrieving wallet information."""
        # Add trailing slash to avoid 301 redirect
        response = self._get_from_simulated_cashless(
            f'wallet/{self.wallet.uuid}/'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['uuid'], str(self.wallet.uuid))


class FederationAPITest(FedowTestCase):
    """Test class for FederationAPI endpoints that are not covered by existing tests."""

    def test_list(self):
        """Test listing federations."""
        response = self._get_from_simulated_cashless('federation/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(isinstance(response.data, list))


class TransactionAPITest(FedowTestCase):
    """Test class for TransactionAPI endpoints that are not covered by existing tests."""

    def setUp(self):
        super().setUp()
        # Create a wallet and user for testing
        self.wallet, self.private_pem, self.public_pem = self.create_wallet_via_api()

        # Create an asset for testing
        faker = Faker()
        name = faker.currency_name()
        currency_code = faker.currency_code()
        self.asset = Asset.objects.create(
            name=name,
            currency_code=currency_code,
            category=Asset.TOKEN_LOCAL_FIAT,
            wallet_origin=self.place.wallet
        )

        # Create a primary card for the place
        from fedow_core.models import Origin
        gen1 = Origin.objects.get_or_create(
            place=self.place,
            generation=1
        )[0]
        complete_tag_id_uuid = str(uuid4())
        qrcode_uuid = str(uuid4())
        self.primary_card = Card.objects.create(
            complete_tag_id_uuid=complete_tag_id_uuid,
            first_tag_id=f"{complete_tag_id_uuid.split('-')[0]}",
            qrcode_uuid=qrcode_uuid,
            number_printed=f"{qrcode_uuid.split('-')[0]}",
            origin=gen1,
        )
        # Make it a primary card for the place
        self.primary_card.primary_places.add(self.place)

        # Create tokens for sender and receiver
        Token.objects.get_or_create(wallet=self.place.wallet, asset=self.asset)
        Token.objects.get_or_create(wallet=self.wallet, asset=self.asset)

        # Create a CREATION transaction first (required for REFILL)
        creation_transaction = Transaction.objects.create(
            sender=self.place.wallet,
            receiver=self.place.wallet,  # For CREATION, sender and receiver must be the same
            asset=self.asset,
            amount=10000,  # Create enough tokens for the REFILL
            action=Transaction.CREATION,
            ip="127.0.0.1",  # Required field
            primary_card=self.primary_card  # Required for non-stripe primary assets
        )

        # Create a REFILL transaction for testing
        self.transaction = Transaction.objects.create(
            sender=self.place.wallet,
            receiver=self.wallet,
            asset=self.asset,
            amount=1000,
            action=Transaction.REFILL,
            ip="127.0.0.1"  # Required field
        )

    def test_list(self):
        """Test listing transactions."""
        response = self._get_from_simulated_cashless('transaction/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(isinstance(response.data, list))

    def test_retrieve(self):
        """Test retrieving a transaction."""
        response = self._get_from_simulated_cashless(f'transaction/{self.transaction.uuid}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['uuid'], str(self.transaction.uuid))

    def test_get_from_hash(self):
        """Test retrieving a transaction by hash."""
        response = self._get_from_simulated_cashless(f'transaction/{self.transaction.hash}/get_from_hash/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['uuid'], str(self.transaction.uuid))

    def test_refill_requires_creation(self):
        """Test that a REFILL transaction requires a prior CREATION transaction."""
        # Create a new asset for testing
        faker = Faker()
        name = faker.currency_name()
        currency_code = faker.currency_code()
        new_asset = Asset.objects.create(
            name=name,
            currency_code=currency_code,
            category=Asset.TOKEN_LOCAL_FIAT,
            wallet_origin=self.place.wallet
        )

        # Create tokens for sender and receiver
        Token.objects.get_or_create(wallet=self.place.wallet, asset=new_asset)
        Token.objects.get_or_create(wallet=self.wallet, asset=new_asset)

        # Try to create a REFILL transaction without a prior CREATION transaction
        with self.assertRaises(AssertionError) as context:
            Transaction.objects.create(
                sender=self.place.wallet,
                receiver=self.wallet,
                asset=new_asset,
                amount=1000,
                action=Transaction.REFILL,
                ip="127.0.0.1"
            )

        # Verify the error message
        self.assertIn("Previous transaction of Refill must be a creation money", str(context.exception))

        # Now create a CREATION transaction
        creation_transaction = Transaction.objects.create(
            sender=self.place.wallet,
            receiver=self.place.wallet,  # For CREATION, sender and receiver must be the same
            asset=new_asset,
            amount=10000,  # Create enough tokens for the REFILL
            action=Transaction.CREATION,
            ip="127.0.0.1",
            primary_card=self.primary_card  # Required for non-stripe primary assets
        )

        # Now the REFILL transaction should work
        refill_transaction = Transaction.objects.create(
            sender=self.place.wallet,
            receiver=self.wallet,
            asset=new_asset,
            amount=1000,
            action=Transaction.REFILL,
            ip="127.0.0.1"
        )

        # Verify the REFILL transaction was created
        self.assertEqual(refill_transaction.action, Transaction.REFILL)
        self.assertEqual(refill_transaction.asset, new_asset)
        self.assertEqual(refill_transaction.sender, self.place.wallet)
        self.assertEqual(refill_transaction.receiver, self.wallet)
        self.assertEqual(refill_transaction.amount, 1000)
