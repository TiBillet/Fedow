import json
from datetime import datetime
from uuid import uuid4

from faker import Faker
from rest_framework import status

from fedow_core.models import Asset, Token, Transaction, Card, Origin
from fedow_core.tests.tests import FedowTestCase
from fedow_core.utils import sign_message, data_to_b64, get_private_key


class TransactionAPITest(FedowTestCase):
    """Test class for TransactionAPI endpoints that are not covered by existing tests."""

    def setUp(self):
        super().setUp()
        # Create a wallet and user for testing
        self.wallet, self.private_pem, self.public_pem = self.create_wallet_via_api()
        
        # Create a card and link it to the wallet
        gen1 = Origin.objects.get_or_create(
            place=self.place,
            generation=1
        )[0]
        complete_tag_id_uuid = str(uuid4())
        qrcode_uuid = str(uuid4())
        self.card = Card.objects.create(
            complete_tag_id_uuid=complete_tag_id_uuid,
            first_tag_id=f"{complete_tag_id_uuid.split('-')[0]}",
            qrcode_uuid=qrcode_uuid,
            number_printed=f"{qrcode_uuid.split('-')[0]}",
            origin=gen1,
            user=self.wallet.user
        )
        
        # Create a membership asset
        faker = Faker()
        name = faker.currency_name()
        currency_code = faker.currency_code()
        self.membership_asset = Asset.objects.create(
            name=name,
            currency_code=currency_code,
            category=Asset.SUBSCRIPTION,
            wallet_origin=self.place.wallet
        )
        
        # Create tokens for the wallet and place
        Token.objects.get_or_create(wallet=self.wallet, asset=self.membership_asset)
        Token.objects.get_or_create(wallet=self.place.wallet, asset=self.membership_asset)

    def test_create_membership(self):
        """Test creating a membership transaction."""
        # Create the signature
        private_rsa = get_private_key(self.private_pem)
        data = {
            'asset': str(self.membership_asset.uuid),
            'amount': 1000,
            'sender': str(self.place.wallet.uuid),
            'receiver': str(self.wallet.uuid),
            'user_card_firstTagId': self.card.first_tag_id
        }
        date_iso = datetime.now().isoformat()
        
        # For POST requests, we sign the data
        signature = sign_message(
            data_to_b64(data),
            private_rsa,
        ).decode('utf-8')
        
        response = self.client.post(
            '/transaction/create_membership/',
            json.dumps(data),
            content_type='application/json',
            headers={
                'Authorization': f'Api-Key {self.temp_key_place}',
                'Wallet': str(self.wallet.uuid),
                'Date': date_iso,
                'Signature': signature,
            }
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify the transaction was created
        transaction_uuid = response.data['uuid']
        transaction = Transaction.objects.get(uuid=transaction_uuid)
        self.assertEqual(transaction.action, Transaction.SUBSCRIBE)
        self.assertEqual(transaction.asset, self.membership_asset)
        self.assertEqual(transaction.sender, self.place.wallet)
        self.assertEqual(transaction.receiver, self.wallet)
        self.assertEqual(transaction.amount, 1000)
        
        # Verify the token value was updated
        token = Token.objects.get(wallet=self.wallet, asset=self.membership_asset)
        self.assertEqual(token.value, 1000)

    def test_paginated_list_by_wallet_signature(self):
        """Test getting a paginated list of transactions by wallet signature."""
        # Create a transaction first
        transaction = Transaction.objects.create(
            sender=self.place.wallet,
            receiver=self.wallet,
            asset=self.membership_asset,
            amount=1000,
            action=Transaction.SUBSCRIBE,
            ip="127.0.0.1",
            card=self.card
        )
        
        # Create the signature
        private_rsa = get_private_key(self.private_pem)
        date_iso = datetime.now().isoformat()
        message = f"{self.wallet.uuid}:{date_iso}".encode('utf8')
        signature = sign_message(
            message,
            private_rsa,
        ).decode('utf-8')
        
        response = self.client.get(
            '/transaction/paginated_list_by_wallet_signature/',
            headers={
                'Authorization': f'Api-Key {self.temp_key_place}',
                'Wallet': str(self.wallet.uuid),
                'Date': date_iso,
                'Signature': signature,
            }
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue('results' in response.data)
        self.assertTrue(len(response.data['results']) > 0)
        
        # Check if our transaction is in the results
        transaction_uuids = [t['uuid'] for t in response.data['results']]
        self.assertIn(str(transaction.uuid), transaction_uuids)