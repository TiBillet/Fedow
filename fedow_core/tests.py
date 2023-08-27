import base64
import json
from datetime import datetime
from io import StringIO
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from rest_framework import viewsets, status
from rest_framework.permissions import AllowAny
from rest_framework_api_key.models import APIKey
from rest_framework.test import APIClient

from fedow_core.models import Configuration, Card, Place, FedowUser, Wallet
from fedow_core.serializers import WalletCreateSerializer
from fedow_core.utils import utf8_b64_to_dict, rsa_generator, dict_to_b64, sign_message, get_private_key, b64_to_dict, \
    validate_format_rsa_pub_key, fernet_decrypt, verify_signature
from fedow_core.views import HelloWorld

import logging
logger = logging.getLogger(__name__)

# Create your tests here.


class APITestHelloWorld(TestCase):
    def setUp(self):
        call_command('install', '--test')
        api_key, self.key = APIKey.objects.create_key(name="test_helloworld")

    def test_helloworld(self):
        start = datetime.now()

        response = self.client.get('/helloworld/')
        logger.warning(f"durée requete sans APIKey : {datetime.now() - start}")

        assert response.status_code == 200
        assert response.data == {'message': 'Hello world!'}
        assert issubclass(HelloWorld, viewsets.ViewSet)

        hello_world = HelloWorld()
        permissions = hello_world.get_permissions()
        assert len(permissions) == 1
        assert isinstance(hello_world.get_permissions()[0], AllowAny)

    def test_hasapi_key_helloworld(self):
        # Sans clé api
        start = datetime.now()

        response = self.client.get('/helloworld_apikey/')
        self.assertEqual(response.status_code, 403)

        # Avec une clé api
        response = self.client.get('/helloworld_apikey/',
                                   headers={'Authorization': f'Api-Key {self.key}'}
                                   )

        logger.warning(f"durée requete avec APIKey : {datetime.now() - start}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'message': 'Hello world ApiKey!'})

    def test_api_and_signed_message(self):
        out = StringIO()
        call_command('new_place',
                     '--name', 'Billetistan',
                     '--email', f'admin@admin.admin',
                     stdout=out)

        decoded_data = utf8_b64_to_dict(out.getvalue().split('\n')[-2])
        key = decoded_data.get('temp_key')
        place = Place.objects.get(pk=decoded_data.get('uuid'))
        wallet = place.wallet
        user = get_user_model().objects.get(email='admin@admin.admin')
        self.assertEqual(user.key, APIKey.objects.get_from_key(key))

        start = datetime.now()

        message = {
            'sender': f'{wallet.uuid}',
            'receiver': f'{wallet.uuid}',
            'amount': '1500',
        }
        signature = sign_message(dict_to_b64(message), wallet.private_key())
        public_key = wallet.public_key()
        enc_message = dict_to_b64(message)
        string_signature = signature.decode('utf-8')

        logger.warning(f"durée signature : {datetime.now() - start}")
        start = datetime.now()

        self.assertTrue(verify_signature(public_key, enc_message, string_signature))

        logger.warning(f"durée verif signature : {datetime.now() - start}")
        start = datetime.now()

        # APi + Wallet + Good Signature
        response = self.client.post('/helloworld_apikey/', message,
                                    headers={
                                        'Authorization': f'Api-Key {key}',
                                        'Signature': signature,
                                    }, format='json')

        self.assertEqual(response.status_code, 200)
        logger.warning(f"durée requete avec signature et api et wallet : {datetime.now() - start}")

        # Sans signature
        response = self.client.post('/helloworld_apikey/', message,
                                    headers={
                                        'Authorization': f'Api-Key {key}',
                                    }, format='json')
        self.assertEqual(response.status_code, 403)

        # sans API
        response = self.client.post('/helloworld_apikey/', message,
                                    headers={
                                        'Signature': signature,
                                    }, format='json')
        self.assertEqual(response.status_code, 403)

        # sans wallet
        message_no_wallet = {
            'receiver': f'{wallet.uuid}',
            'amount': 1500,
        }
        response = self.client.post('/helloworld_apikey/', message_no_wallet,
                                    headers={
                                        'Authorization': f'Api-Key {key}',
                                        'Signature': signature,
                                    }, format='json')
        self.assertEqual(response.status_code, 403)

        # APi + Wallet + Bad Signature
        response = self.client.post('/helloworld_apikey/', message,
                                    headers={
                                        'Authorization': f'Api-Key {key}',
                                        'Signature': b'bad signature',
                                    }, format='json')
        self.assertEqual(response.status_code, 403)


class ModelsTest(TestCase):
    def setUp(self):
        call_command('install', '--test')

        User: FedowUser = get_user_model()

        email_admin = 'admin@admin.admin'
        self.email_admin = email_admin

        # Création d'une clé lambda
        api_key, self.key = APIKey.objects.create_key(name="test_helloworld")
        self.uuid_test = uuid4()

        # Initialise la création d'un nouveau lieu
        # par la procédure manuelle
        out = StringIO()
        call_command('new_place',
                     '--name', 'Billetistan',
                     '--email', f'{email_admin}',
                     stdout=out)

        # Récupération du dictionnaire encodé en b64 qui contient la clé API de l'admin du lieu nouvellement créé
        # Le dernier element de la liste est un retour chariot.
        # Sélection de l'avant-dernier qui contient la clé
        self.last_line = out.getvalue().split('\n')[-2]
        decoded_data = utf8_b64_to_dict(self.last_line)
        self.place_uuid = decoded_data.get('uuid')

        # Données pour simuler un cashless.
        self.cashless_rsa_key, pub_rsa_key = rsa_generator()
        cashless_admin_api_key, cashless_admin_key = APIKey.objects.create_key(name="cashless_admin")
        self.data_cashless = {
            'cashless_ip': '127.0.0.1',
            'cashless_url': 'https://cashless.tibillet.localhost',
            'cashless_rsa_pub_key': pub_rsa_key,
            'cashless_admin_apikey': cashless_admin_key,
        }

    def test_place_and_admin_created_(self):
        User: FedowUser = get_user_model()
        email_admin = self.email_admin

        # Vérification que le dictionnaire est bien encodé en b64
        decoded_data = utf8_b64_to_dict(self.last_line)
        self.assertIsInstance(decoded_data, dict)

        # Place exist et admin est admin dans place
        place = Place.objects.get(pk=decoded_data.get('uuid'))
        admin = User.objects.get(email=f'{email_admin}')
        self.assertIn(place, admin.admin_places.all())
        self.assertIn(admin, place.admins.all())

        api_key_from_decoded_data = APIKey.objects.get_from_key(decoded_data.get('temp_key'))
        self.assertEqual(api_key_from_decoded_data, admin.key)
        self.assertIn('temp_', admin.key.name)

    def xtest_integryty_validator(self):
        # TODO: vérifier l'intégrité du code global et lancer les tests avant le gunicorn en prod
        pass

    def test_simulate_cashless_handshake(self):
        # Simulation de l'objet handshake créé par le cashless
        place = Place.objects.get(pk=self.place_uuid)
        data = self.data_cashless.copy()
        data['fedow_place_uuid'] = f'{place.uuid}'

        private_key = get_private_key(self.cashless_rsa_key)
        signature: bytes = sign_message(message=dict_to_b64(data), private_key=private_key)

        # Test with bad key
        response = self.client.post('/place/', data,
                                    headers={
                                        'Authorization': f'Api-Key {self.key}',
                                        'Signature': signature,
                                    }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Place exist mais pas encore eu de handshake
        self.assertIsNone(place.cashless_server_url)
        self.assertIsNone(place.cashless_server_ip)
        self.assertIsNone(place.cashless_rsa_pub_key)
        self.assertIsNone(place.cashless_admin_apikey)

        # Test with good keycashless_server_ip
        decoded_data = utf8_b64_to_dict(self.last_line)
        admin_temp_key = decoded_data.get('temp_key')
        response = self.client.post('/place/', data,
                                    headers={
                                        'Authorization': f'Api-Key {admin_temp_key}',
                                        'Signature': signature,
                                    },
                                    format='json')

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        # Decodage du dictionnaire encodé en b64 qui contient la clé du wallet du lieu nouvellement créé
        # et le lien url onboard stripe
        place.refresh_from_db()
        decoded_data = b64_to_dict(response.content)
        self.assertIsInstance(decoded_data, dict)
        # Vérification que la clé est bien celui du wallet du lieu
        admin_key = APIKey.objects.get_from_key(decoded_data.get('admin_key'))
        self.assertIn(admin_key.fedow_user, place.admins.all())

        # Check si tout a bien été entré en base de donnée
        self.assertEqual(place.cashless_server_url, data.get('cashless_url'))
        self.assertEqual(place.cashless_server_ip, data.get('cashless_ip'))

        self.assertEqual(
            validate_format_rsa_pub_key(place.cashless_rsa_pub_key),
            validate_format_rsa_pub_key(data.get('cashless_rsa_pub_key'))
        )

        self.assertEqual(fernet_decrypt(place.cashless_admin_apikey), data.get('cashless_admin_apikey'))

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
