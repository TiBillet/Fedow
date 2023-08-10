from uuid import uuid4

from django.test import TestCase
from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from rest_framework_api_key.models import APIKey
from rest_framework.test import APIClient

from fedow_core.models import Configuration, Card
from fedow_core.serializers import WalletCreateSerializer
from fedow_core.views import HelloWorld


# Create your tests here.


class APITestHelloWorld(TestCase):
    def setUp(self):
        api_key, self.key = APIKey.objects.create_key(name="test_helloworld")

    #     Animal.objects.create(name="lion", sound="roar")
    #     Animal.objects.create(name="cat", sound="meow")

    def test_helloworld(self):
        response = self.client.get('/helloworld/')
        assert response.status_code == 200
        assert response.data == {'message': 'Hello world!'}
        assert issubclass(HelloWorld, viewsets.ViewSet)

        hello_world = HelloWorld()
        permissions = hello_world.get_permissions()
        assert len(permissions) == 1
        assert isinstance(hello_world.get_permissions()[0], AllowAny)

    def test_hasapi_key_helloworld_403(self):
        response = self.client.get('/helloworld_apikey/')
        self.assertEqual(response.status_code, 403)

    def test_hasapi_key_helloworld(self):
        response = self.client.get('/helloworld_apikey/',
                                   headers={'Authorization': f'Api-Key {self.key}'}
                                   )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'message': 'Hello world!'})


class ModelsTest(TestCase):
    def setUp(self):
        # Création des variables nécéssaires à plusieurs tests
        api_key, self.key = APIKey.objects.create_key(name="test_helloworld")
        self.uuid_test = uuid4()

    def test_card_create(self):
        # Create card
        self.card = Card.objects.create(
            uuid=str(self.uuid_test),
            nfc_tag_id=str(self.uuid_test).split('-')[0])

    def test_wallet_create(self):
        response = self.client.post('/wallet/', {
            'email': 'test@example.com',
            'uuid_card': f'{self.uuid_test}'
        }, headers={'Authorization': f'Api-Key {self.key}'}, format='json')

        print(response)
        assert response.status_code == 200
