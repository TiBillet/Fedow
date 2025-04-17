import json
from uuid import uuid4

from django.utils.timezone import make_aware
from faker import Faker
from rest_framework import status

from fedow_core.models import Asset
from fedow_core.tests.tests import FedowTestCase


class AssetAPITest(FedowTestCase):
    """Test class for AssetAPI endpoints that are not covered by existing tests."""

    def setUp(self):
        super().setUp()
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

    def test_list(self):
        """Test listing assets."""
        response = self._get_from_simulated_cashless('asset/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(isinstance(response.data, list))
        # Check if our created asset is in the list
        asset_uuids = [asset['uuid'] for asset in response.data]
        self.assertIn(str(self.asset.uuid), asset_uuids)

    def test_retrieve(self):
        """Test retrieving an asset."""
        response = self._get_from_simulated_cashless(f'asset/{self.asset.uuid}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['uuid'], str(self.asset.uuid))
        self.assertEqual(response.data['name'], self.asset.name)
        self.assertEqual(response.data['currency_code'], self.asset.currency_code)
        self.assertEqual(response.data['category'], self.asset.category)

    def test_create(self):
        """Test creating an asset."""
        faker = Faker()
        name = faker.currency_name()
        currency_code = faker.currency_code()
        data = {
            "name": name,
            "currency_code": currency_code,
            "category": Asset.TOKEN_LOCAL_FIAT
        }
        response = self._post_from_simulated_cashless('asset', data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Asset.objects.filter(name=name).exists())

        # Test with UUID and datetime
        name = faker.currency_name()
        currency_code = faker.currency_code()
        asset_uuid = str(uuid4())
        created_at = make_aware(faker.date_time_this_year())
        data = {
            "uuid": asset_uuid,
            "name": name,
            "currency_code": currency_code,
            "category": Asset.TOKEN_LOCAL_NOT_FIAT,
            "created_at": created_at.isoformat()
        }
        response = self._post_from_simulated_cashless('asset', data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Asset.objects.filter(uuid=asset_uuid).exists())
        self.assertEqual(Asset.objects.get(uuid=asset_uuid).name, name)

    def test_retrieve_membership_asset(self):
        """Test retrieving membership assets."""
        # Create a membership asset
        faker = Faker()
        name = faker.currency_name()
        currency_code = faker.currency_code()
        membership_asset = Asset.objects.create(
            name=name,
            currency_code=currency_code,
            category=Asset.SUBSCRIPTION,
            wallet_origin=self.place.wallet
        )

        response = self._get_from_simulated_cashless(f'asset/{membership_asset.uuid}/retrieve_membership_asset/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['uuid'], str(membership_asset.uuid))
        self.assertEqual(response.data['category'], Asset.SUBSCRIPTION)

    def test_archive_asset(self):
        """Test archiving an asset."""
        self.assertFalse(self.asset.archive)  # Initially not archived

        response = self._get_from_simulated_cashless(f'asset/{self.asset.uuid}/archive_asset/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Refresh from database
        self.asset.refresh_from_db()
        self.assertTrue(self.asset.archive)  # Now archived
