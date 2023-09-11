from datetime import datetime
from io import StringIO
from uuid import uuid4
import stripe
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from rest_framework import viewsets, status
from rest_framework.permissions import AllowAny
from rest_framework_api_key.models import APIKey

from fedow_core.models import Card, Place, FedowUser, OrganizationAPIKey, Origin, get_or_create_user, Wallet, \
    Configuration, Asset, Token, CheckoutStripe, Transaction
from fedow_core.utils import utf8_b64_to_dict, rsa_generator, dict_to_b64, sign_message, get_private_key, b64_to_dict, \
    get_public_key, fernet_decrypt, verify_signature
from fedow_core.views import HelloWorld
from django.core.signing import Signer

import logging

logger = logging.getLogger(__name__)


class FedowTestCase(TestCase):
    def setUp(self):
        call_command('install', '--test')

        User: FedowUser = get_user_model()
        email_admin = 'admin@admin.admin'
        self.email_admin = email_admin
        self.uuid_test = uuid4()

        out = StringIO()
        call_command('new_place',
                     '--name', 'Billetistan',
                     '--email', f'{email_admin}',
                     stdout=out)

        self.last_line = out.getvalue().split('\n')[-2]
        decoded_data = utf8_b64_to_dict(self.last_line)
        self.place = Place.objects.get(pk=decoded_data.get('uuid'))
        self.admin = User.objects.get(email=f'{email_admin}')

        # Création d'une clé lambda
        api_key, self.key = APIKey.objects.create_key(name="test_helloworld")

        # On simule une paire de clé générée par le serveur cashless
        private_cashless_pem, public_cashless_pem = rsa_generator()
        self.private_cashless_rsa = get_private_key(private_cashless_pem)
        self.public_cashless_pem = public_cashless_pem
        self.private_cashless_pem = private_cashless_pem
        # self.place.cashless_rsa_pub_key = public_cashless_pem
        # self.place.save()


class TransactionsTest(FedowTestCase):

    def setUp(self):
        super().setUp()

        # Création d'une carte NFC
        gen1 = Origin.objects.create(
            place=self.place,
            generation=1
        )

        nfc_uuid = uuid4()
        qrcode = uuid4()
        self.card = Card.objects.create(
            uuid=uuid4(),
            first_tag_id=f"{str(nfc_uuid).split('-')[0]}",
            nfc_uuid=nfc_uuid,
            qr_code_printed=qrcode,
            number=str(qrcode).split('-')[0],
            origin=gen1,
        )


    def testWallet(self):
        ### Création d'un wallet client avec un email et un uuid de carte
        User: FedowUser = get_user_model()
        email = 'lambda@lambda.com'
        new_wallet_data = {
            'email' : email,
            'uuid_card': f"{self.card.uuid}",
        }
        response = self.client.post('/wallet/', new_wallet_data)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data.get('email'), email)
        self.assertEqual(response.data.get('uuid_card'), str(self.card.uuid))

        wallet = Wallet.objects.get(pk=response.data.get('wallet'))
        user = User.objects.get(email=email)
        self.assertTrue(wallet)
        self.assertEqual(user.wallet, wallet)

    def test_REFILL(self):
        ### RECHARGE AVEC ASSET PRINCIPAL STRIPE
        ## Creation de monnaie. Reception d'un webhook stripe
        ## A faire a la main en attendant une automatisation du paiement checkout
        """
        Lancer stripe :
        stripe listen --forward-to http://127.0.0.1:8000/webhook_stripe/
        
        S'assurer que la clé de signature soit la même que dans le .env
        Créer un checkout et le payer : 
        ./manage.py create_test_checkout
        
        Vérifier les Transactions et les Assets
        """

        # Création d'un checkout stripe
        out = StringIO()
        call_command('create_test_checkout',
                     stdout=out)
        last_line = out.getvalue()
        # print(last_line)

        # Récupération du checkout stripe
        checkout = CheckoutStripe.objects.all().order_by('datetime').last()

        # amount_total est entré normalement par l'user sur stripe
        amount_total = "4200"

        # Récupération des metadonnée envoyées à Stripe
        signer = Signer()
        signed_data = utf8_b64_to_dict(signer.unsign(checkout.metadata))
        primary_token = Token.objects.get(uuid=signed_data.get('primary_token'))
        user_token = Token.objects.get(uuid=signed_data.get('user_token'))
        card = Card.objects.get(uuid=signed_data.get('card_uuid'))

        # L'asset est-il le même entre les deux tokens ?
        self.assertEqual(primary_token.asset, user_token.asset)
        # L'user du token est-il le même que celui de la carte ?
        self.assertEqual(card.user, user_token.wallet.user)

        # Création de la transaction de création de token
        token_creation = Transaction.objects.create(
            ip='0.0.0.0',
            checkout_stripe=checkout,
            sender=primary_token.wallet,
            receiver=primary_token.wallet,
            asset=primary_token.asset,
            amount=int(amount_total),
            action=Transaction.CREATION,
            card=card,
            primary_card_uuid=None,  # Création de monnaie
        )

        self.assertTrue(token_creation.verify_hash())
        primary_token.refresh_from_db()
        self.assertEqual(int(amount_total), primary_token.value)

        # virement vers le wallet de l'utilisateur
        virement = Transaction.objects.create(
            ip='0.0.0.0',
            checkout_stripe=checkout,
            sender=primary_token.wallet,
            receiver=user_token.wallet,
            asset=primary_token.asset,
            amount=int(amount_total),
            action=Transaction.REFILL,
            card=card,
            primary_card_uuid=None,  # Création de monnaie
        )

        self.assertTrue(virement.verify_hash())
        primary_token.refresh_from_db()
        user_token.refresh_from_db()
        self.assertEqual(int(amount_total), user_token.value)
        self.assertEqual(0, primary_token.value)


"""
class APITestHelloWorld(FedowTestCase):

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

        # Sans clé api
        start = datetime.now()
        response = self.client.get('/helloworld_apikey/')
        self.assertEqual(response.status_code, 403)

        # Avec une fausse clé api
        response = self.client.get('/helloworld_apikey/',
                                   headers={'Authorization': f'Api-Key {self.key}'}
                                   )

        logger.warning(f"durée requete avec APIKey : {datetime.now() - start}")
        self.assertEqual(response.status_code, 403)

    def test_api_and_signed_message(self):
        decoded_data = utf8_b64_to_dict(self.last_line)
        key = decoded_data.get('temp_key')
        api_key = OrganizationAPIKey.objects.get_from_key(key)
        place = Place.objects.get(pk=decoded_data.get('uuid'))

        # On simule une paire de clé généré par le serveur cashless
        private_cashless_pem, public_cashless_pem = rsa_generator()
        private_cashless_rsa = get_private_key(private_cashless_pem)
        place.cashless_rsa_pub_key = public_cashless_pem
        place.save()

        wallet = place.wallet
        user = get_user_model().objects.get(email='admin@admin.admin')
        self.assertEqual(user, api_key.user)
        self.assertEqual(place, api_key.place)

        start = datetime.now()

        message = {
            'sender': f'{wallet.uuid}',
            'receiver': f'{wallet.uuid}',
            'amount': '1500',
        }
        signature = sign_message(dict_to_b64(message), private_cashless_rsa)
        public_key = place.cashless_public_key()
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


class ModelsTest(FedowTestCase):

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

        api_key_from_decoded_data = OrganizationAPIKey.objects.get_from_key(decoded_data.get('temp_key'))
        self.assertEqual(api_key_from_decoded_data.user, admin)
        self.assertIn('temp_', api_key_from_decoded_data.name)

    def test_simulate_cashless_handshake(self):
        # Données pour simuler un cashless.
        cashless_private_rsa_key, cashless_pub_rsa_key = rsa_generator()
        # Simulation d'une clé générée par le serveur cashless
        cashless_admin_api_key, cashless_admin_key = APIKey.objects.create_key(name="cashless_admin")
        data = {
            'cashless_ip': '127.0.0.1',
            'cashless_url': 'https://cashless.tibillet.localhost',
            'cashless_rsa_pub_key': cashless_pub_rsa_key,
            'cashless_admin_apikey': cashless_admin_key,
        }
        # Ajout de l'uuid place et de la clé API "temp" récupérée dans la string
        # encodée par la création manuelle de new_place
        decoded_data = utf8_b64_to_dict(self.last_line)
        temp_key = decoded_data.get('temp_key')
        data['fedow_place_uuid'] = decoded_data.get('uuid')
        place = Place.objects.get(pk=data['fedow_place_uuid'])
        self.assertIsInstance(place, Place)
        # Le serveur cashless signe ses requetes avec sa clé privée :
        signature: bytes = sign_message(message=dict_to_b64(data),
                                        private_key=get_private_key(cashless_private_rsa_key))

        # Test with bad key
        response = self.client.post('/place/', data,
                                    headers={
                                        'Authorization': f'Api-Key {self.key}',
                                        'Signature': signature,
                                    }, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Place exist mais pas encore eu de handshake
        self.assertIsNone(place.cashless_server_url)
        self.assertIsNone(place.cashless_server_ip)
        self.assertIsNone(place.cashless_rsa_pub_key)
        self.assertIsNone(place.cashless_admin_apikey)

        # Test with good keycashless_server_ip
        response = self.client.post('/place/', data,
                                    headers={
                                        'Authorization': f'Api-Key {temp_key}',
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
        admin_key = OrganizationAPIKey.objects.get_from_key(decoded_data.get('admin_key'))
        self.assertIn(admin_key.user, place.admins.all())

        # Check si tout a bien été entré en base de donnée
        self.assertEqual(place.cashless_server_url, data.get('cashless_url'))
        self.assertEqual(place.cashless_server_ip, data.get('cashless_ip'))

        self.assertEqual(
            get_public_key(place.cashless_rsa_pub_key),
            get_public_key(data.get('cashless_rsa_pub_key'))
        )

        self.assertEqual(fernet_decrypt(place.cashless_admin_apikey), data.get('cashless_admin_apikey'))


"""
