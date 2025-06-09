import unittest
from django.test import tag
from fedow_core.models import Asset, Place, Wallet, Transaction, Token, Card, Origin
from fedow_core.tests.tests import FedowTestCase


class AssetTotalByPlaceTest(FedowTestCase):
    """Test class for the Asset.total_by_place() method."""

    def setUp(self):
        super().setUp()

        # Create a second place for testing
        from fedow_core.validators import PlaceValidator
        from fedow_core.utils import rsa_generator

        # Generate a valid RSA public key for the second place admin
        second_place_private_pem, second_place_public_pem = rsa_generator()
        second_place_admin_email = 'admin_second_place@admin.admin'
        data = {
            'place_domain': 'secondplace.tibillet.localhost',
            'place_name': 'SecondPlace',
            'admin_email': second_place_admin_email,
            'admin_pub_pem': second_place_public_pem,
        }
        validator = PlaceValidator(data=data)
        if validator.is_valid():
            validator.create_place()

        self.second_place = Place.objects.get(name='SecondPlace')

        # Create an origin for cards
        self.origin = Origin.objects.create(
            place=self.place,
            generation=1
        )

        # Create a card for testing
        from uuid import uuid4
        complete_tag_id_uuid = str(uuid4())
        qrcode_uuid = str(uuid4())
        self.card = Card.objects.create(
            complete_tag_id_uuid=complete_tag_id_uuid,
            first_tag_id=f"{complete_tag_id_uuid.split('-')[0]}",
            qrcode_uuid=qrcode_uuid,
            number_printed=f"{qrcode_uuid.split('-')[0]}",
            origin=self.origin,
        )

        # Create primary cards for both places
        # Primary card for first place
        complete_tag_id_uuid = str(uuid4())
        qrcode_uuid = str(uuid4())
        self.primary_card1 = Card.objects.create(
            complete_tag_id_uuid=complete_tag_id_uuid,
            first_tag_id=f"{complete_tag_id_uuid.split('-')[0]}",
            qrcode_uuid=qrcode_uuid,
            number_printed=f"{qrcode_uuid.split('-')[0]}",
            origin=self.origin,
        )
        self.primary_card1.primary_places.add(self.place)

        # Primary card for second place
        complete_tag_id_uuid = str(uuid4())
        qrcode_uuid = str(uuid4())
        self.primary_card2 = Card.objects.create(
            complete_tag_id_uuid=complete_tag_id_uuid,
            first_tag_id=f"{complete_tag_id_uuid.split('-')[0]}",
            qrcode_uuid=qrcode_uuid,
            number_printed=f"{qrcode_uuid.split('-')[0]}",
            origin=self.origin,
        )
        self.primary_card2.primary_places.add(self.second_place)

        # Get the primary stripe asset
        self.primary_asset = Asset.objects.get(category=Asset.STRIPE_FED_FIAT)

    @tag("total_by_place")
    def test_total_by_place(self):
        """Test the total_by_place method of the Asset model."""
        # Get the wallet for the card
        wallet_card = self.card.get_wallet()

        # Transfer to the wallet with the primary asset
        transfer_amount = 10000  # 100 euros (in cents)

        # Create tokens for both wallets
        place_token, created = Token.objects.get_or_create(
            wallet=self.place.wallet,
            asset=self.primary_asset,
            defaults={'value': transfer_amount}
        )
        if not created:
            place_token.value = transfer_amount
            place_token.save()

        wallet_token, created = Token.objects.get_or_create(
            wallet=wallet_card,
            asset=self.primary_asset,
            defaults={'value': 0}
        )

        # Create a transfer transaction
        transaction_transfer = Transaction.objects.create(
            ip="127.0.0.1",
            sender=self.place.wallet,
            receiver=wallet_card,
            asset=self.primary_asset,
            amount=transfer_amount,
            datetime=self.primary_asset.created_at,
            action=Transaction.TRANSFER,
            card=self.card,
            previous_transaction=Transaction.objects.filter(asset=self.primary_asset).order_by('datetime').last()
        )

        # Update token values after transfer
        place_token.value -= transfer_amount
        place_token.save()

        wallet_token.value += transfer_amount
        wallet_token.save()

        # Spend in the first place
        spend_amount_place1 = 3000  # 30 euros (in cents)
        transaction_spend1 = Transaction.objects.create(
            ip="127.0.0.1",
            sender=wallet_card,
            receiver=self.place.wallet,
            asset=self.primary_asset,
            amount=spend_amount_place1,
            datetime=self.primary_asset.created_at,
            action=Transaction.SALE,
            card=self.card,
            primary_card=self.primary_card1,
            previous_transaction=transaction_transfer
        )

        # Update token values
        wallet_token = Token.objects.get(wallet=wallet_card, asset=self.primary_asset)
        wallet_token.value -= spend_amount_place1
        wallet_token.save()

        # Get the existing token for the first place
        place_token.value += spend_amount_place1
        place_token.save()

        # Spend in the second place
        spend_amount_place2 = 2000  # 20 euros (in cents)

        # Create a token for the second place's wallet before the transaction
        place2_token, created = Token.objects.get_or_create(
            wallet=self.second_place.wallet,
            asset=self.primary_asset,
            defaults={'value': 0}
        )

        transaction_spend2 = Transaction.objects.create(
            ip="127.0.0.1",
            sender=wallet_card,
            receiver=self.second_place.wallet,
            asset=self.primary_asset,
            amount=spend_amount_place2,
            datetime=self.primary_asset.created_at,
            action=Transaction.SALE,
            card=self.card,
            primary_card=self.primary_card2,
            previous_transaction=transaction_spend1
        )

        # Update token values
        wallet_token.value -= spend_amount_place2
        wallet_token.save()

        place2_token.value += spend_amount_place2
        place2_token.save()

        # Get the total by place
        place_totals = self.primary_asset.total_by_place()

        # Verify that both places exist in the result
        self.assertIn(self.place.name, place_totals)
        self.assertIn(self.second_place.name, place_totals)

        # Verify that the amounts are correct
        self.assertEqual(place_totals[self.place.name], spend_amount_place1)
        self.assertEqual(place_totals[self.second_place.name], spend_amount_place2)

        # Verify that the total in place wallets is correct
        total_in_place = self.primary_asset.total_in_place()
        self.assertEqual(total_in_place, spend_amount_place1 + spend_amount_place2)
