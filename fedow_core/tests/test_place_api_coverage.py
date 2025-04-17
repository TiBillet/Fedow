import json
from uuid import uuid4

from django.contrib.auth import get_user_model
from faker import Faker
from rest_framework import status

from fedow_core.models import Place, Wallet
from fedow_core.tests.tests import FedowTestCase
from fedow_core.utils import rsa_generator, sign_message, dict_to_b64, get_private_key


class PlaceAPITest(FedowTestCase):
    """Test class for PlaceAPI endpoints that are not covered by existing tests."""

    def test_create(self):
        """Test creating a place."""
        # Generate a key pair for the admin
        private_pem, public_pem = rsa_generator()

        # Create data for a new place
        faker = Faker()
        place_name = f"Test Place {faker.company()}"
        admin_email = faker.email()

        data = {
            'place_domain': f"{place_name.lower().replace(' ', '')}.tibillet.localhost",
            'place_name': place_name,
            'admin_email': admin_email,
            'admin_pub_pem': public_pem,
        }

        # Use the create place API key for this request
        from fedow_core.models import CreatePlaceAPIKey
        api_keys = CreatePlaceAPIKey.objects.all()
        if not api_keys.exists():
            self.skipTest("No CreatePlaceAPIKey available for testing")

        create_place_key = api_keys.first().key

        response = self.client.post(
            '/place/',
            json.dumps(data),
            content_type='application/json',
            headers={
                'Authorization': f'Api-Key {create_place_key}',
            }
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Verify the place was created
        self.assertTrue(Place.objects.filter(name=place_name).exists())
        place = Place.objects.get(name=place_name)

        # Verify the admin was created and associated with the place
        User = get_user_model()
        self.assertTrue(User.objects.filter(email=admin_email).exists())
        admin = User.objects.get(email=admin_email)
        self.assertIn(place, admin.admin_places.all())
        self.assertIn(admin, place.admins.all())

    def test_handshake(self):
        """Test the handshake process between a place and a cashless server."""
        # Generate keys for the cashless server
        cashless_private_pem, cashless_pub_pem = rsa_generator()
        cashless_private_key = get_private_key(cashless_private_pem)

        # Create data for the handshake
        data = {
            'cashless_ip': '127.0.0.2',  # Different from the one in the existing test
            'cashless_url': 'https://cashless-test.tibillet.localhost',
            'cashless_rsa_pub_key': cashless_pub_pem,
            'cashless_admin_apikey': 'a' * 41,  # Exactly 41 characters
            'fedow_place_uuid': str(self.place.uuid),
        }

        # Sign the data with the cashless private key
        signature = sign_message(
            message=dict_to_b64(data),
            private_key=cashless_private_key
        )

        # Make the handshake request
        response = self.client.post(
            '/place/handshake/',
            json.dumps(data),
            content_type='application/json',
            headers={
                'Authorization': f'Api-Key {self.temp_key_place}',
                'Signature': signature,
            }
        )

        # Print response content for debugging
        print(f"Response status: {response.status_code}")
        print(f"Response content: {response.content.decode()}")

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        # Verify the place was updated with the cashless information
        self.place.refresh_from_db()
        self.assertEqual(self.place.cashless_server_url, data['cashless_url'])
        self.assertEqual(self.place.cashless_server_ip, data['cashless_ip'])
        # Strip trailing newlines from both keys before comparing
        self.assertEqual(self.place.cashless_rsa_pub_key.strip(), data['cashless_rsa_pub_key'].strip())
