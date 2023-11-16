import json
import uuid
from datetime import datetime, timedelta
from io import StringIO
import random
from uuid import uuid4
import stripe
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db.models import Sum
from django.test import TestCase, tag
from django.utils.timezone import make_aware
from faker import Faker
from rest_framework import viewsets, status
from rest_framework.permissions import AllowAny
from rest_framework_api_key.models import APIKey

from fedow_core.models import Card, Place, FedowUser, OrganizationAPIKey, Origin, get_or_create_user, Wallet, \
    Configuration, Asset, Token, CheckoutStripe, Transaction, Federation, asset_creator
from fedow_core.utils import utf8_b64_to_dict, rsa_generator, dict_to_b64, sign_message, get_private_key, b64_to_dict, \
    get_public_key, fernet_decrypt, verify_signature, data_to_b64
from fedow_core.views import HelloWorld
from django.core.signing import Signer

import logging

logger = logging.getLogger(__name__)


class FedowTestCase(TestCase):
    def setUp(self):
        call_command('install', '--test')

        primary_federation = Federation.objects.all()[0]
        User: FedowUser = get_user_model()
        email_admin = 'admin@admin.admin'
        self.email_admin = email_admin
        self.uuid_test = uuid4()

        out = StringIO()
        call_command('new_place',
                     '--name', 'Billetistan',
                     '--email', f'{email_admin}',
                     '--federation', f'{primary_federation.name}',
                     stdout=out)

        self.last_line = out.getvalue().split('\n')[-2]
        decoded_data = utf8_b64_to_dict(self.last_line)
        self.temp_key_place = decoded_data.get('temp_key')

        self.place = Place.objects.get(pk=decoded_data.get('uuid'))
        self.admin = User.objects.get(email=f'{email_admin}')

        # On simule une paire de clé générée par le serveur cashless
        private_cashless_pem, public_cashless_pem = rsa_generator()
        self.private_cashless_pem = private_cashless_pem
        self.private_cashless_rsa = get_private_key(private_cashless_pem)
        self.public_cashless_pem = public_cashless_pem

    def _post_from_simulated_cashless(self, path, data: dict or list):
        # TODO: Une clé temp ne devrait pas pouvoir acceder au lieu
        key = self.temp_key_place
        place: Place = self.place
        json_data = json.dumps(data)

        # On simule une paire de clé générée par le serveur cashless
        place.cashless_rsa_pub_key = self.public_cashless_pem
        place.save()
        public_key = place.cashless_public_key()

        # Signature de la requete
        signature = sign_message(
            data_to_b64(data),
            self.private_cashless_rsa,
        ).decode('utf-8')

        # Ici, on s'auto vérifie :
        self.assertTrue(verify_signature(public_key,
                                         data_to_b64(data),
                                         signature))

        response = self.client.post(f'/{path}/', json_data, content_type='application/json',
                                    headers={
                                        'Authorization': f'Api-Key {key}',
                                        'Signature': signature,
                                    })

        return response

    def _get_from_simulated_cashless(self, path):
        key = self.temp_key_place
        place: Place = self.place

        # Signature de la requete : on signe la clé
        signature = sign_message(
            key.encode('utf8'),
            self.private_cashless_rsa,
        ).decode('utf-8')

        # On simule une paire de clé générée par le serveur cashless
        place.cashless_rsa_pub_key = self.public_cashless_pem
        place.save()
        public_key = place.cashless_public_key()

        # Ici, on s'auto vérifie :
        self.assertTrue(verify_signature(public_key,
                                         key.encode('utf8'),
                                         signature))

        response = self.client.get(f"/{path}",
                                   headers={
                                       'Authorization': f'Api-Key {key}',
                                       'Signature': signature,
                                   })

        return response


class AssetCardTest(FedowTestCase):

    def setUp(self):
        super().setUp()

        # Création d'une carte NFC
        gen1 = Origin.objects.create(
            place=self.place,
            generation=1
        )
        # création de 100 cartes sans user
        for i in range(10):
            complete_tag_id_uuid = str(uuid4())
            qrcode_uuid = str(uuid4())
            Card.objects.create(
                complete_tag_id_uuid=complete_tag_id_uuid,
                first_tag_id=f"{complete_tag_id_uuid.split('-')[0]}",
                qrcode_uuid=qrcode_uuid,
                number_printed=f"{qrcode_uuid.split('-')[0]}",
                origin=gen1,
            )
        self.card = Card.objects.all()[0]

    def testCreateAssetWithoutAPI(self):
        # UUID et DATETIME géré par le modèle
        faker = Faker()
        name = faker.currency_name()
        currency_code = faker.currency_code()
        asset_creator(
            name=name,
            currency_code=currency_code,
            category=random.choice([Asset.TOKEN_LOCAL_FIAT, Asset.TOKEN_LOCAL_NOT_FIAT]),
            origin=self.place.wallet
        )
        self.assertTrue(Asset.objects.filter(name=name).exists())
        self.assertTrue(Transaction.objects.filter(asset__name=name, action=Transaction.FIRST).exists())

        try:
            asset_creator(
                name=name,
                currency_code=currency_code,
                category=random.choice([Asset.TOKEN_LOCAL_FIAT, Asset.TOKEN_LOCAL_NOT_FIAT]),
                origin=self.place.wallet
            )
            # Si on arrive ici, c'est que l'exception n'a pas été enclanchée, les asserts suivants sont donc faux
            self.assertEqual(Asset.objects.filter(name=name).count(), 1)
            self.assertTrue(Asset.objects.filter(name=name).exists())
        except ValueError as e:
            self.assertEqual(e.args[0], "Asset name already exist")

        # UUID et DATETIME donné en paramètre
        # Pour simuler la création d'un asset depuis un serveur cashless, par exemple
        faker = Faker()
        name = faker.currency_name()
        currency_code = faker.currency_code()
        asset_uuid = str(uuid4())
        created_at = make_aware(faker.date_time_this_year())

        currency_code = faker.currency_code()
        asset_creator(
            name=name,
            currency_code=currency_code,
            category=random.choice([Asset.TOKEN_LOCAL_FIAT, Asset.TOKEN_LOCAL_NOT_FIAT]),
            origin=self.place.wallet,
            original_uuid=asset_uuid,
            created_at=created_at,
        )

        self.assertTrue(Asset.objects.filter(name=name).exists())
        self.assertEqual(str(Asset.objects.get(name=name).uuid), asset_uuid)
        self.assertEqual(Asset.objects.get(name=name).created_at.isoformat(), created_at.isoformat())
        self.assertTrue(Transaction.objects.filter(asset__name=name, action=Transaction.FIRST).exists())
        self.assertEqual(Transaction.objects.get(asset__name=name, action=Transaction.FIRST).datetime.isoformat(),
                         created_at.isoformat())

    def create_wallet_with_API(self):
        ### Création d'un wallet client avec un email et un uuid de carte
        faker = Faker()
        card = Card.objects.all()[0]

        # Juste avec email :
        email = faker.email()
        response = self._post_from_simulated_cashless('wallet', {'email': email})
        self.assertEqual(response.status_code, 201)
        wallet = Wallet.objects.get(pk=response.data)
        self.assertEqual(wallet.user.email, email)
        self.assertEqual(wallet.user.cards.count(), 0)

        # Avec First Tag Id
        email = faker.email()
        data = {
            'email': email,
            'card_first_tag_id': f"{card.first_tag_id}",
        }
        response = self._post_from_simulated_cashless('wallet', data)
        self.assertEqual(response.status_code, 201)
        wallet = Wallet.objects.get(pk=response.data)
        self.assertEqual(wallet.user.email, email)
        self.assertIn(card, wallet.user.cards.all())

        # Avec le QRCode de la carte précédente :
        email = faker.email()
        data = {
            'email': email,
            'card_qrcode_uuid': f"{card.qrcode_uuid}",
        }
        response = self._post_from_simulated_cashless('wallet', data)
        self.assertEqual(response.status_code, 400)

        # Avec le QRCode d'une carte qui n'a pas encore d'user :
        email = faker.email()
        card = Card.objects.filter(user__isnull=True).first()
        data = {
            'email': email,
            'card_qrcode_uuid': f"{card.qrcode_uuid}",
        }
        response = self._post_from_simulated_cashless('wallet', data)
        self.assertEqual(response.status_code, 201)

        wallet = Wallet.objects.get(pk=response.data)
        self.assertEqual(wallet.user.email, email)
        self.assertIn(card, wallet.user.cards.all())

        return wallet

    def create_multiple_card(self):
        # création d'une liste de 10 sans uuid avec gen 1
        cards = []
        for i in range(10):
            complete_tag_id_uuid = str(uuid4())
            qrcode_uuid = str(uuid4())
            cards.append({
                "first_tag_id": complete_tag_id_uuid.split('-')[0],
                "complete_tag_id_uuid": complete_tag_id_uuid,
                "qrcode_uuid": qrcode_uuid,
                "number_printed": qrcode_uuid.split('-')[0],
                "generation": 1,
                "is_primary": False,
            })

        response = self._post_from_simulated_cashless('card', cards)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Card.objects.all().count(), 20)

        # création d'une liste de 10 cartes avec gen 2
        card_gen2 = []
        for i in range(10):
            uuid_nfc = str(uuid4())
            uuid_qrcode = str(uuid4())
            card_gen2.append({
                "uuid": str(uuid4()),
                "first_tag_id": uuid_nfc.split('-')[0],
                "complete_tag_id_uuid": uuid_nfc,
                "qrcode_uuid": uuid_qrcode,
                "number_printed": uuid_qrcode.split('-')[0],
                "generation": 2,
                "is_primary": False,
            })

        response = self._post_from_simulated_cashless('card', card_gen2)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Card.objects.all().count(), 30)
        self.assertEqual(Card.objects.filter(origin__generation=2).count(), 10)

        primary_card_gen3 = []
        for i in range(3):
            uuid_nfc = str(uuid4())
            uuid_qrcode = str(uuid4())
            primary_card_gen3.append({
                "uuid": str(uuid4()),
                "first_tag_id": uuid_nfc.split('-')[0],
                "complete_tag_id_uuid": uuid_nfc,
                "qrcode_uuid": uuid_qrcode,
                "number_printed": uuid_qrcode.split('-')[0],
                "generation": 3,
                "is_primary": True,
            })

        response = self._post_from_simulated_cashless('card', primary_card_gen3)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Card.objects.all().count(), 33)
        self.assertEqual(Card.objects.filter(origin__generation=3).count(), 3)
        self.assertEqual(self.place.primary_cards.all().count(), 3)

    @tag("create_asset")
    def create_asset_with_API(self):
        # Création d'un asset de lieu via API ( NON STRIPE FEDERE )

        # UUID et DATETIME géré par le modèle

        faker = Faker()
        name = faker.currency_name()
        currency_code = faker.currency_code()

        message = {
            "name": name,
            "currency_code": currency_code,
            "category": random.choice([Asset.TOKEN_LOCAL_FIAT, Asset.TOKEN_LOCAL_NOT_FIAT])
        }
        response = self._post_from_simulated_cashless('asset', message)

        self.assertEqual(response.status_code, 201)
        self.assertTrue(Asset.objects.filter(name=name).exists())
        self.assertTrue(Transaction.objects.filter(asset__name=name, action=Transaction.FIRST).exists())

        # avec UUID et DATETIME donné en paramètre

        # LOCAL FIAT (Monnaie EURO)
        message = {
            "uuid": str(uuid4()),
            "name": faker.currency_name(),
            "currency_code": faker.currency_code(),
            "category": Asset.TOKEN_LOCAL_FIAT,
            "created_at": make_aware(faker.date_time_this_year()).isoformat()
        }
        response = self._post_from_simulated_cashless('asset', message)
        self.assertEqual(response.status_code, 201)

        # LOCAL NON FIAT (monnaie temps, cadeau, bénévoles, june)
        message = {
            "uuid": str(uuid4()),
            "name": faker.currency_name(),
            "currency_code": faker.currency_code(),
            "category": Asset.TOKEN_LOCAL_NOT_FIAT,
            "created_at": make_aware(faker.date_time_this_year()).isoformat()
        }
        response = self._post_from_simulated_cashless('asset', message)
        if response.status_code != 201:
            import ipdb; ipdb.set_trace()
        self.assertEqual(response.status_code, 201)

        # Abonnement ou adhésion associatve

        # On garde les variables pour les asserts
        name = "Adhésion associative"
        currency_code = "ADH"
        asset_uuid = str(uuid4())
        created_at = make_aware(faker.date_time_this_year())

        message = {
            "name": name,
            "currency_code": currency_code,
            "category": Asset.SUBSCRIPTION,
            "uuid": asset_uuid,
            "created_at": created_at.isoformat()
        }
        response = self._post_from_simulated_cashless('asset', message)
        self.assertEqual(response.status_code, 201)

        self.assertTrue(Asset.objects.filter(name=name).exists())
        self.assertTrue(Transaction.objects.filter(asset__name=name, action=Transaction.FIRST).exists())

        self.assertEqual(str(Asset.objects.get(name=name).uuid), asset_uuid)
        self.assertEqual(Asset.objects.get(name=name).created_at.isoformat(), created_at.isoformat())
        self.assertEqual(Transaction.objects.get(asset__name=name, action=Transaction.FIRST).datetime.isoformat(),
                         created_at.isoformat())

        serialized_response = response.json()
        self.assertEqual(serialized_response.get('uuid'), asset_uuid)
        self.assertEqual(serialized_response.get('is_stripe_primary'), False)
        self.assertEqual(serialized_response.get('origin'), str(self.place.wallet.uuid))

        return Asset.objects.all()


    @tag("create_token")
    def test_send_new_tokens_to_wallet(self):
        # Création de 3 assets différents pour simuler un asset € et deux monnaies temps/bénévoles
        place: Place = self.place
        primary_card = self.place.primary_cards.all().first()
        assets = self.create_asset_with_API()

        total_par_assets = {f"{asset.uuid}": 0 for asset in assets}

        # On charge les cartes sans users (wallet temporaires)
        for card in Card.objects.filter(user__isnull=True)[:5]:
            # Création aléatoire de portefeuille
            # De 1 à 3 assets différents
            r_assets = random.sample(
                [asset for asset in assets.exclude(category__in=[Asset.STRIPE_FED_FIAT, Asset.SUBSCRIPTION])],
                k=random.randint(1, 3))

            for asset in r_assets:
                # entre 10 centimes et 100 euros
                amount = random.randint(10, 10000)
                total_par_assets[f"{asset.uuid}"] += amount

                # virement vers le portefeuille de la carte
                wallet_card = card.get_wallet()
                # ici on test avec le tagid de la carte
                transaction_refill = {
                    "amount": amount,
                    "sender": f"{place.wallet.uuid}",
                    "receiver": f"{wallet_card.uuid}",
                    "asset": f"{asset.uuid}",
                    "user_card_firstTagId": f"{card.first_tag_id}",
                }
                response = self._post_from_simulated_cashless('transaction', transaction_refill)

                #TODO: Gerer les cartes primaires
                import ipdb; ipdb.set_trace()

                self.assertEqual(response.status_code, 201)
                transaction = Transaction.objects.get(pk=response.json().get('uuid'))
                self.assertEqual(transaction.action, Transaction.REFILL)
                self.assertEqual(transaction.asset, asset)
                self.assertEqual(transaction.sender, place.wallet)
                self.assertEqual(transaction.receiver, wallet_card)
                self.assertEqual(transaction.amount, amount)
                self.assertEqual(transaction.card, card)
                self.assertEqual(transaction.primary_card, None)

                self.assertEqual(Token.objects.get(asset=asset, wallet=wallet_card).value, amount)

        # Calcul de la somme de chaque wallet avec aggregate :
        for asset_uuid, total in total_par_assets.items():
            self.assertEqual(Token.objects.filter(asset__uuid=asset_uuid).aggregate(Sum('value')).get('value__sum'),
                             total)


        # SUBSCRIPTION : Il faut un wallet avec un user
        self.create_wallet_with_API()
        card = Card.objects.filter(user__isnull=False).first()
        wallet_card = card.get_wallet()
        sub = assets.filter(category=Asset.SUBSCRIPTION).first()
        transaction_refill = {
            "amount": 1000,
            "sender": f"{place.wallet.uuid}",
            "receiver": f"{wallet_card.uuid}",
            "asset": f"{sub.uuid}",
            "user_card_firstTagId": f"{card.first_tag_id}",
        }

        response_abonnement = self._post_from_simulated_cashless('transaction', transaction_refill)
        if response_abonnement.status_code != 201:
            import ipdb; ipdb.set_trace()

        transaction = Transaction.objects.get(pk=response_abonnement.json().get('uuid'))
        self.assertEqual(transaction.action, Transaction.SUBSCRIBE)
        self.assertEqual(transaction.asset, sub)
        self.assertEqual(transaction.sender, place.wallet)
        self.assertEqual(transaction.receiver, wallet_card)
        self.assertEqual(transaction.amount, 1000)
        self.assertEqual(transaction.card, card)
        self.assertEqual(transaction.primary_card, None)


    @tag("stripe")
    def test_get_stripe_checkout_in_charge_primary_asset_api(self):
        # Test la création d'un lien stripe pour faire une recharge de monnaie
        ### Création d'un wallet client avec un email
        email = 'lambda@lambda.com'
        response = self._post_from_simulated_cashless('checkout_stripe_for_charge_primary_asset', {'email': email})

        self.assertEqual(response.status_code, 202)
        self.assertIn('https://checkout.stripe.com/c/pay/', response.json())

        # Récupération des metadonnée envoyées à Stripe
        checkout = CheckoutStripe.objects.all().order_by('datetime').last()
        signer = Signer()
        signed_data = utf8_b64_to_dict(signer.unsign(checkout.metadata))
        primary_token = Token.objects.get(uuid=signed_data.get('primary_token'))
        user_token = Token.objects.get(uuid=signed_data.get('user_token'))

        self.assertEqual(primary_token.asset, user_token.asset)
        self.assertTrue(primary_token.is_primary_stripe_token())

        ### Création d'un wallet client avec un email et un uuid de carte
        self.create_wallet_with_API()
        card = Card.objects.filter(user__isnull=False).first()
        email = card.user.email
        response = self._post_from_simulated_cashless('checkout_stripe_for_charge_primary_asset',
                                                      {'email': email, 'card_qrcode_uuid': f"{card.qrcode_uuid}"})

        # Récupération des metadonnée envoyées à Stripe
        checkout = CheckoutStripe.objects.all().order_by('datetime').last()
        signer = Signer()
        signed_data = utf8_b64_to_dict(signer.unsign(checkout.metadata))
        user_token = Token.objects.get(uuid=signed_data.get('user_token'))
        card_from_stripe = Card.objects.get(qrcode_uuid=signed_data.get('card_qrcode_uuid'))

        self.assertEqual(card_from_stripe.user.email, email)
        self.assertEqual(card_from_stripe.user, card.user)
        self.assertEqual(user_token.wallet, card.user.wallet)
        self.assertEqual(card_from_stripe.uuid, card.uuid)

    @tag("cards")
    def test_all(self):
        self.create_multiple_card()
        self.create_wallet_with_API()

        wallet = Wallet.objects.filter(user__isnull=False, user__cards__isnull=False).first()
        user = wallet.user

        place = self.place

        assets = self.create_asset_with_API()
        asset = assets.filter(category=Asset.TOKEN_LOCAL_NOT_FIAT).first()

        # REFILL = creation monnétaire en une seule requete
        data = {
            "amount": "10",
            "sender": f"{place.wallet.uuid}",
            "receiver": f"{user.wallet.uuid}",
            "asset": f"{asset.uuid}",
        }

        response = self._post_from_simulated_cashless('transaction', data)

        # Pas de carte primaire ni user :
        self.assertEqual(response.status_code, 400)

        data = {
            "amount": "10",
            "sender": f"{place.wallet.uuid}",
            "receiver": f"{user.wallet.uuid}",
            "asset": f"{asset.uuid}",
            "user_card_firstTagId": f"{wallet.user.cards.first().first_tag_id}",
        }

        response = self._post_from_simulated_cashless('transaction', data)

        #TODO : carte primaire
        import ipdb; ipdb.set_trace()
        self.assertEqual(response.status_code, 201)

        transaction = Transaction.objects.get(pk=response.json().get('uuid'))
        self.assertEqual(transaction.action, Transaction.REFILL)
        self.assertEqual(transaction.asset, asset)
        self.assertEqual(transaction.sender, place.wallet)
        self.assertEqual(transaction.receiver, user.wallet)
        self.assertEqual(transaction.amount, int(data['amount']))
        token = Token.objects.get(asset=asset, wallet=user.wallet)
        self.assertEqual(token.value, int(data['amount']))

    def xtest_vente(self):
        pass

class APITestHelloWorld(FedowTestCase):

    def test_helloworld_allow_any(self):
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
        # Création d'une clé lambda
        api_key, key = APIKey.objects.create_key(name="bad_test_helloworld")

        response = self.client.get('/helloworld_apikey/',
                                   headers={'Authorization': f'Api-Key {key}'}
                                   )

        logger.warning(f"durée requete avec APIKey : {datetime.now() - start}")
        self.assertEqual(response.status_code, 403)

    def test_api_and_handshake_signed_message(self):
        decoded_data = utf8_b64_to_dict(self.last_line)
        key = decoded_data.get('temp_key')
        api_key = OrganizationAPIKey.objects.get_from_key(key)
        place: Place = self.place

        # On simule une paire de clé générée par le serveur cashless
        private_cashless_pem, public_cashless_pem = rsa_generator()
        private_cashless_rsa = get_private_key(private_cashless_pem)
        place.cashless_rsa_pub_key = public_cashless_pem
        place.save()

        wallet = place.wallet
        user = get_user_model().objects.get(email='admin@admin.admin')
        self.assertEqual(user, api_key.user)
        self.assertEqual(place, api_key.place)

        message = {
            'sender': f'{wallet.uuid}',
            'receiver': f'{wallet.uuid}',
            'amount': '1500',
        }
        signature = sign_message(dict_to_b64(message), private_cashless_rsa)
        public_key = place.cashless_public_key()
        enc_message = dict_to_b64(message)
        string_signature = signature.decode('utf-8')

        self.assertTrue(verify_signature(public_key, enc_message, string_signature))

        # APi + Wallet + Good Signature
        response = self.client.post('/helloworld_apikey/', message,
                                    headers={
                                        'Authorization': f'Api-Key {key}',
                                        'Signature': signature,
                                    }, format='json')
        self.assertEqual(response.status_code, 200)

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


class HandshakeTest(FedowTestCase):

    def test_place_and_admin_created(self):
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

    # @tag("crash")
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
        apikey, key = APIKey.objects.create_key(name="bad_test")
        response = self.client.post('/place/', data,
                                    headers={
                                        'Authorization': f'Api-Key {key}',
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
        admin_key = OrganizationAPIKey.objects.get_from_key(decoded_data.get('place_admin_apikey'))
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
# @tag("only")
def test_create_checkout_and_REFILL(self):
    ### RECHARGE AVEC ASSET PRINCIPAL STRIPE
    ## Creation de monnaie. Reception d'un webhook stripe
    ## A faire a la main en attendant une automatisation du paiement checkout
    # Lancer stripe :
    # stripe listen --forward-to http://127.0.0.1:8000/webhook_stripe/
    # 
    # S'assurer que la clé de signature soit la même que dans le .env
    # Créer un checkout et le payer :
    # ./manage.py create_test_checkout
    # 
    # Vérifier les Transactions et les Assets

    # Création d'un checkout stripe
    out = StringIO()
    call_command('create_test_checkout',
                 '--no-stripe',
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
        primary_card=None,  # Création de monnaie
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
        primary_card=None,  # Création de monnaie
    )

    self.assertTrue(virement.verify_hash())
    primary_token.refresh_from_db()
    user_token.refresh_from_db()
    self.assertEqual(int(amount_total), user_token.value)
    self.assertEqual(0, primary_token.value)

    # Ajout d'une carte primaire
    admin_place_user, created = get_or_create_user('admin@admin.admin')
    primary_card = Card.objects.all()[10]
    primary_card.user = admin_place_user
    primary_card.save()

    # Simulation de la clé rsa du cashless
    self.place.cashless_rsa_pub_key = self.public_cashless_pem
    self.place.primary_cards_cashless.add(primary_card)
    self.place.save()

    # Pour les requetes GET, on signe le path
    response = self._get_from_simulated_cashless(f'/card/{card.first_tag_id}/')

    self.assertEqual(response.status_code, 200)

    data = response.json()
    fti = data['first_tag_id']
    resp_card = Card.objects.get(first_tag_id=fti)
    self.assertEqual(resp_card, card)
    user_id = data['user']['uuid']
    self.assertEqual(user_id, str(user_token.wallet.user.uuid))
    user_wallet_id = data['user']['wallet']['uuid']
    self.assertEqual(user_wallet_id, str(user_token.wallet.uuid))
    tokens = data['user']['wallet']['tokens']
    fedow_token_value = tokens[0]['value']
    self.assertEqual(fedow_token_value, 4200)

    print(response.json())


# @tag("only")
def test_transaction_from_card_to_place_without_API(self):
    charge42 = self.test_create_checkout_and_REFILL()
    last_transaction = Transaction.objects.order_by('datetime').last()
    self.assertTrue(last_transaction.verify_hash())
    card = last_transaction.card
    user = card.user
    user_wallet = user.wallet

    place_wallet = self.place.wallet
    config = Configuration.get_solo()
    # primary_asset = config.primary_wallet.primary_asset
    primary_asset = Asset.objects.get(origin=config.primary_wallet, category=Asset.STRIPE_FED_FIAT)
    self.assertEqual(Token.objects.get(wallet=user_wallet, asset=primary_asset).value, 4200)

    # On verfie que la transaction ne peux avoir lieux
    # ( montant trop élevé : )
    try:
        virement = Transaction.objects.create(
            ip='0.0.0.0',
            checkout_stripe=None,
            sender=user_wallet,
            receiver=place_wallet,
            asset=primary_asset,
            amount=int("9999"),
            action=Transaction.SALE,
            card=card,
            primary_card=None,  # Création de monnaie
        )
    except Exception as e:
        self.assertIsInstance(e, ValueError)
        self.assertEqual(str(e), "amount too high")

    # création d'une carte primaire
    admin_place_user, created = get_or_create_user('admin@admin.admin')
    primary_card = Card.objects.all()[10]
    primary_card.user = admin_place_user
    primary_card.save()

    self.place.primary_cards_cashless.add(primary_card)
    self.place.save()

    message = {
        "amount": "1000",
        "asset": f"{primary_asset.uuid}",
        "primary_card": f"{primary_card.uuid}",
        "user_card_uuid": f"{card.uuid}",
    }

    self.place.cashless_rsa_pub_key = self.public_cashless_pem
    self.place.save()

    private_cashless_rsa = get_private_key(self.private_cashless_pem)
    signature = sign_message(dict_to_b64(message), private_cashless_rsa)
    # creation de la requete nouvelle transaction par carte :
    response = self.client.post('/transaction/', message,
                                headers={
                                    'Authorization': f'Api-Key {self.temp_key_place}',
                                    'Signature': signature,
                                })

    self.assertEqual(response.status_code, 201)
    self.place.wallet.refresh_from_db()
    card.user.wallet.refresh_from_db()
    self.assertEqual(Token.objects.get(wallet=self.place.wallet, asset=primary_asset).value, 1000)
    self.assertEqual(Token.objects.get(wallet=card.user.wallet, asset=primary_asset).value, 3200)
    last_transaction = Transaction.objects.order_by('datetime').last()
    self.assertTrue(last_transaction.verify_hash())

"""
