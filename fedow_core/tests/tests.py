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
from django.test import TestCase, tag, TransactionTestCase
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


class FedowTestCase(TransactionTestCase):
    def setUp(self):
        call_command('install' )

        primary_federation = Federation.objects.all()[0]
        User: FedowUser = get_user_model()
        email_admin = 'admin@admin.admin'
        self.email_admin = email_admin
        self.uuid_test = uuid4()

        out = StringIO()
        call_command('places', '--create',
                     '--name', 'Billetistan',
                     '--email', f'{email_admin}',
                     stdout=out)

        self.last_line = out.getvalue().split('\n')[-2]
        decoded_data = utf8_b64_to_dict(self.last_line)
        self.temp_key_place = decoded_data.get('temp_key')

        self.place = Place.objects.get(pk=decoded_data.get('uuid'))
        self.admin = User.objects.get(email=f'{email_admin}')

        # Création de la Place 'Lespass' via PlaceValidator
        from fedow_core.validators import PlaceValidator
        # Génère une clé publique RSA valide pour l'admin Lespass
        lespass_private_pem, lespass_public_pem = rsa_generator()
        lespass_admin_email = 'admin_lespass@admin.admin'
        data = {
            'place_domain': 'lespass.tibillet.localhost',
            'place_name': 'Lespass',
            'admin_email': lespass_admin_email,
            'admin_pub_pem': lespass_public_pem,
        }
        validator = PlaceValidator(data=data)
        if validator.is_valid():
            validator.create_place()
        else:
            # En mode test, on tolère la présence de la place
            pass

        # On simule une paire de clé générée par le serveur cashless
        private_cashless_pem, public_cashless_pem = rsa_generator()
        self.private_cashless_pem = private_cashless_pem
        self.private_cashless_rsa = get_private_key(private_cashless_pem)
        self.public_cashless_pem = public_cashless_pem

    def create_wallet_via_api(self, email=None):
        """
        Crée un wallet utilisateur en respectant la logique du serializer et du view.
        Retourne (wallet, private_pem, public_pem)
        """
        from faker import Faker
        from fedow_core.utils import rsa_generator, sign_message, data_to_b64, get_private_key
        from fedow_core.models import Wallet
        import json
        faker = Faker()
        if not email:
            email = faker.email()
        # Génère une paire de clés pour le wallet
        private_pem, public_pem = rsa_generator()
        private_rsa = get_private_key(private_pem)
        data = {'email': email, 'public_pem': public_pem}
        # Signature de la requête avec la clé privée correspondante
        signature = sign_message(
            data_to_b64(data),
            private_rsa,
        ).decode('utf-8')
        response = self.client.post(
            '/wallet/get_or_create/',
            json.dumps(data),
            content_type='application/json',
            headers={
                'Authorization': f'Api-Key {self.temp_key_place}',
                'Signature': signature,
            }
        )
        assert response.status_code in (200, 201), response.content
        wallet_uuid = response.data
        wallet = Wallet.objects.get(pk=wallet_uuid)
        return wallet, private_pem, public_pem

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
            wallet_origin=self.place.wallet
        )
        self.assertTrue(Asset.objects.filter(name=name).exists())
        self.assertTrue(Transaction.objects.filter(asset__name=name, action=Transaction.FIRST).exists())

        try:
            asset_creator(
                name=name,
                currency_code=currency_code,
                category=random.choice([Asset.TOKEN_LOCAL_FIAT, Asset.TOKEN_LOCAL_NOT_FIAT]),
                wallet_origin=self.place.wallet
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
            wallet_origin=self.place.wallet,
            original_uuid=asset_uuid,
            created_at=created_at,
        )

        self.assertTrue(Asset.objects.filter(name=name).exists())
        self.assertEqual(str(Asset.objects.get(name=name).uuid), asset_uuid)
        self.assertEqual(Asset.objects.get(name=name).created_at.isoformat(), created_at.isoformat())
        self.assertTrue(Transaction.objects.filter(asset__name=name, action=Transaction.FIRST).exists())
        self.assertEqual(Transaction.objects.get(asset__name=name, action=Transaction.FIRST).datetime.isoformat(),
                         created_at.isoformat())

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
        # Une liste de plusieurs monnaie uniques
        set_list = set((faker.currency_name(),faker.currency_code()) for x in range(10))

        name, currency_code = set_list.pop()
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
        name, currency_code = set_list.pop()
        message = {
            "uuid": str(uuid4()),
            "name": name,
            "currency_code": currency_code,
            "category": Asset.TOKEN_LOCAL_FIAT,
            "created_at": make_aware(faker.date_time_this_year()).isoformat()
        }
        response = self._post_from_simulated_cashless('asset', message)
        self.assertEqual(response.status_code, 201)

        # LOCAL NON FIAT (monnaie temps, cadeau, bénévoles, june)
        name, currency_code = set_list.pop()
        message = {
            "uuid": str(uuid4()),
            "name": name,
            "currency_code": currency_code,
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
        self.assertEqual(serialized_response['place_origin']['wallet'], str(self.place.wallet.uuid))

        return Asset.objects.all()


    @tag("create_token")
    def send_new_tokens_to_wallet(self):
        # Création de 3 assets différents pour simuler un asset € et deux monnaies temps/bénévoles
        place: Place = self.place

        # Ensure we have primary cards
        if not self.place.primary_cards.exists():
            self.create_multiple_card()
        primary_card = self.place.primary_cards.all().first()

        # Ensure we have enough assets of different categories
        from faker import Faker
        faker = Faker()

        # Create assets if they don't exist
        required_categories = [
            Asset.TOKEN_LOCAL_FIAT,
            Asset.TOKEN_LOCAL_NOT_FIAT,
            Asset.SUBSCRIPTION
        ]

        for category in required_categories:
            if not Asset.objects.filter(category=category).exists():
                name = faker.currency_name()
                currency_code = faker.currency_code()
                asset_creator(
                    name=name,
                    currency_code=currency_code,
                    category=category,
                    wallet_origin=self.place.wallet
                )

        assets = Asset.objects.all()

        total_par_assets = {f"{asset.uuid}": 0 for asset in assets}

        # On charge les cartes sans users (wallet temporaires)
        for card in Card.objects.filter(user__isnull=True)[:5]:
            # Création aléatoire de portefeuille
            # De 1 à 3 assets différents (ou moins si pas assez d'assets disponibles)
            available_assets = list(assets.exclude(category__in=[Asset.STRIPE_FED_FIAT, Asset.SUBSCRIPTION]))
            k = min(len(available_assets), random.randint(1, 3))
            r_assets = random.sample(available_assets, k) if k > 0 else []

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
                    "primary_card_fisrtTagId": f"{primary_card.first_tag_id}",
                }
                response = self._post_from_simulated_cashless('transaction', transaction_refill)

                # if response.status_code != 201:
                #     import ipdb; ipdb.set_trace()
                self.assertEqual(response.status_code, 201)
                transaction = Transaction.objects.get(pk=response.json().get('uuid'))
                self.assertEqual(transaction.action, Transaction.REFILL)
                self.assertEqual(transaction.asset, asset)
                self.assertEqual(transaction.sender, place.wallet)
                self.assertEqual(transaction.receiver, wallet_card)
                self.assertEqual(transaction.amount, amount)
                self.assertEqual(transaction.card, card)
                self.assertEqual(transaction.primary_card, primary_card)

                self.assertEqual(Token.objects.get(asset=asset, wallet=wallet_card).value, amount)

        # Calcul de la somme de chaque wallet avec aggregate :
        for asset_uuid, total in total_par_assets.items():
            self.assertEqual(Token.objects.filter(asset__uuid=asset_uuid).aggregate(Sum('value')).get('value__sum'),
                             total)


        # SUBSCRIPTION : Il faut un wallet avec un user
        # On crée un wallet utilisateur via l'API
        wallet, private_pem, public_pem = self.create_wallet_via_api()
        # Vérification explicite que le wallet existe bien en base
        # Forcer un refresh du cache ORM
        Wallet.objects.all().iterator()
        print("WALLETS EN BASE après refresh:", list(Wallet.objects.values_list('uuid', flat=True)))
        print("UUID attendu:", wallet.uuid)
        # Affiche tous les wallets avec détails
        for w in Wallet.objects.all():
            try:
                user = w.user
            except Wallet.user.RelatedObjectDoesNotExist:
                user = None
            created = getattr(w, 'created_at', None)
            print("Wallet:", w.uuid, user, created)
        import json
        # On prend une carte vierge
        card = Card.objects.filter(user__isnull=True).first()
        self.assertIsNotNone(card)
        # On associe la carte au wallet via l'API linkwallet_cardqrcode
        link_data = {
            'wallet': str(wallet.uuid),
            'card_qrcode_uuid': str(card.qrcode_uuid),
        }
        print("Payload envoyé à l'API linkwallet_cardqrcode:", link_data)
        from fedow_core.utils import sign_message, data_to_b64, get_private_key
        private_rsa = get_private_key(private_pem)
        signature = sign_message(
            data_to_b64(link_data),
            private_rsa,
        ).decode('utf-8')
        response = self.client.post(
            '/wallet/linkwallet_cardqrcode/',
            json.dumps(link_data),
            content_type='application/json',
            headers={
                'Authorization': f'Api-Key {self.temp_key_place}',
                'Wallet': str(wallet.uuid),
                'Date': datetime.now().isoformat(),
                'Signature': signature,
            }
        )
        self.assertEqual(response.status_code, 200)
        # On récupère la carte associée à l'user
        card = Card.objects.filter(user=wallet.user).first()
        self.assertIsNotNone(card)
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
    def get_stripe_checkout_in_charge_primary_asset_api(self):
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
        # self.create_wallet_with_API()
        card = Card.objects.filter(user__isnull=False).first()
        email = card.user.email
        response = self._post_from_simulated_cashless('checkout_stripe_for_charge_primary_asset',
                                                      {'email': email, 'card_qrcode_uuid': f"{card.qrcode_uuid}"})

        self.assertEqual(response.status_code, 202)
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
        # TODO: Tout classer et lister ici proprement
        self.create_multiple_card()
        self.create_asset_with_API()
        self.send_new_tokens_to_wallet()
        # TODO: Stripe
        # self.get_stripe_checkout_in_charge_primary_asset_api()

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
        response = self.client.post('/place/handshake/', data,
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
        response = self.client.post('/place/handshake/', data,
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
class StripeTest(FedowTestCase):

    @tag("stripe")
    def xtest_create_checkout_and_REFILL(self):
        # Déplacé dans les test cahsless fedow.
        pass
"""


#TODO: Tester link avec wallet sans user -> False
