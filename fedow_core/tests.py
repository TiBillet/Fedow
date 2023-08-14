import base64
import json
from io import StringIO
from uuid import uuid4

from django.core.management import call_command
from django.test import TestCase
from rest_framework import viewsets, status
from rest_framework.permissions import AllowAny
from rest_framework_api_key.models import APIKey
from rest_framework.test import APIClient

from fedow_core.models import Configuration, Card, Place
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
        call_command('install')

        # Création d'une clé lambda
        api_key, self.key = APIKey.objects.create_key(name="test_helloworld")
        self.uuid_test = uuid4()

        # Initialise la création d'un nouveau lieu
        # par la procédure manuelle
        out = StringIO()
        call_command('new_place', 'Billetistan', stdout=out)

        # Récupération du dictionnaire encodé en b64 qui contient la clé du wallet du lieu nouvellement créé
        # Le dernier element de la liste est un retour chariot.
        # Sélection de l'avant-dernier qui contient la clé
        last_line = out.getvalue().split('\n')[-2]
        decoded_data = json.loads(base64.b64decode(last_line).decode('utf-8'))
        self.assertIsInstance(decoded_data, dict)

        self.place = Place.objects.get(pk=decoded_data.get('uuid'))
        self.assertIn('temp_', self.place.wallet.key.name)
        self.billetistan_temp_key = decoded_data.get('temp_key')

    def test_place_create(self):
        # Simulation d'une requete depuis le serveur cashless une fois le dictionnaire
        # créé par la procédure manuelle commands : 'new_place' reçu et décodé
        data = {
            'uuid': f'{self.place.uuid}',
            'ip': '127.0.0.1',
            'url': 'https://cashless.billetistan.com',
            'apikey': '8JheL9iC.9zeoWy1ETlqVBIorpAgUGldqsZOF2ASF',
        }

        # Test with bad key
        response = self.client.post('/place/', data, headers={'Authorization': f'Api-Key {self.key}'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.place.refresh_from_db()
        self.assertIsNone(self.place.cashless_server_url)
        self.assertIsNone(self.place.cashless_server_ip)
        self.assertIsNone(self.place.cashless_server_key)

        # test with key from the place creation
        response = self.client.post('/place/', data, headers={'Authorization': f'Api-Key {self.billetistan_temp_key}'},
                                    format='json')
        self.place.refresh_from_db()

        # Decodage du dictionnaire encodé en b64 qui contient la clé du wallet du lieu nouvellement créé
        # et le lien url onboard stripe
        decoded_data = json.loads(base64.b64decode(response.content).decode('utf-8'))
        self.assertIsInstance(decoded_data, dict)

        # Vérification que la clé est bien celui du wallet du lieu
        key = decoded_data.get('key')
        self.assertTrue(APIKey.objects.is_valid(key))
        api_key = APIKey.objects.get_from_key(key)
        self.assertEqual(api_key.name, f'{self.place.name}')
        self.assertEqual(self.place.wallet.key, api_key)

        # Check si tout a bien été entré en base de donnée
        self.assertEqual(self.place.cashless_server_url, data.get('url'))
        self.assertEqual(self.place.cashless_server_ip, data.get('ip'))
        self.assertEqual(self.place.cashless_server_key, data.get('apikey'))
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

    def xtest_card_create(self):
        # Create card
        self.card = Card.objects.create(
            uuid=str(self.uuid_test),
            nfc_tag_id=str(self.uuid_test).split('-')[0])

    def xtest_wallet_create(self):
        response = self.client.post('/wallet/', {
            'email': 'test@example.com',
            'uuid_card': f'{self.uuid_test}'
        }, headers={'Authorization': f'Api-Key {self.key}'}, format='json')

        print(response)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # TODO : vérifier que l'user est lié au wallet
