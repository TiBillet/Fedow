"""
Tests de non-régression : objets Stripe réels (stripe >= 12)
/ Regression tests: real Stripe objects (stripe >= 12)

LOCALISATION : fedow_core/tests/test_stripe_refill_regression.py

POURQUOI CE FICHIER :
Le 11/06/2026, le passage de stripe 7 à stripe 15 a cassé les recharges
de wallet en production (issue Sentry FEDOW-DJANGO-2G).
Depuis stripe 12, StripeObject n'hérite plus de dict.
La méthode .get() n'existe plus sur les objets Stripe.

Un MagicMock ne peut pas détecter ce bug.
Sur un MagicMock, .get() "marche" et renvoie un autre mock.
Le test passe, mais la production crashe.

Ces tests mockent donc les appels réseau Stripe avec de VRAIS StripeObject
construits par StripeObject.construct_from().
C'est la classe réelle de la lib stripe installée.
Si la lib stripe change encore de comportement, ces tests casseront ici,
pas en production.

FLUX TESTÉS :
1. Recharge en ligne : validate_stripe_checkout_and_make_transaction
   (appelé par le webhook POST et par le GET retrieve_from_refill_checkout)
2. Recharge par TPE : validate_stripe_reader_wise_pose_and_make_transaction
   (appelé par le webhook terminal.reader.action_succeeded)
"""
import hashlib
import hmac
import json
import time
from uuid import uuid4
from unittest.mock import patch

from django.core.signing import Signer
from django.db import IntegrityError
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIRequestFactory
from stripe import StripeObject

from fedow_core.models import (
    Asset,
    Card,
    CheckoutStripe,
    Configuration,
    Origin,
    Token,
    Transaction,
)
from fedow_core.tests.tests import FedowTestCase
from fedow_core.utils import data_to_b64, dict_to_b64_utf8, sign_message
from fedow_core.views import StripeAPI


class StripeRefillRegressionTest(FedowTestCase):
    """
    Vérifie les flux de recharge Stripe avec de vrais StripeObject.
    / Checks the Stripe refill flows with real StripeObject instances.
    """

    def setUp(self):
        super().setUp()
        # Récupère la configuration créée par la commande install
        # / Gets the configuration created by the install command
        self.config = Configuration.get_solo()
        self.primary_wallet = self.config.primary_wallet
        self.stripe_asset = Asset.objects.get(
            wallet_origin=self.primary_wallet,
            category=Asset.STRIPE_FED_FIAT,
        )

        # Crée un utilisateur avec son wallet, comme le ferait Lespass
        # / Creates a user and a wallet, like Lespass would
        wallet_utilisateur, _private_pem, _public_pem = self.create_wallet_via_api()
        self.wallet_utilisateur = wallet_utilisateur
        self.utilisateur = wallet_utilisateur.user

    def _construire_checkout_paye_avec_vrai_stripe_object(self, montant_en_centimes):
        """
        Prépare un CheckoutStripe en base et le StripeObject correspondant.
        / Builds a CheckoutStripe row and the matching real StripeObject.

        Reproduit ce que fait create_stripe_checkout_for_federated_refill :
        les uuid des tokens sont signés avec le Signer de Django
        et placés dans les metadata du checkout Stripe.
        """
        token_primaire, _created = Token.objects.get_or_create(
            wallet=self.primary_wallet,
            asset=self.stripe_asset,
        )
        token_utilisateur, _created = Token.objects.get_or_create(
            wallet=self.wallet_utilisateur,
            asset=self.stripe_asset,
        )

        metadata_a_signer = {
            'primary_token': str(token_primaire.uuid),
            'user_token': str(token_utilisateur.uuid),
        }
        signed_data = Signer().sign(dict_to_b64_utf8(metadata_a_signer))

        checkout_en_base = CheckoutStripe.objects.create(
            checkout_session_id_stripe=f'cs_test_{uuid4().hex}',
            asset=self.stripe_asset,
            user=self.utilisateur,
            metadata=signed_data,
            status=CheckoutStripe.OPEN,
        )

        # construct_from convertit récursivement les dict imbriqués.
        # checkout.metadata sera donc lui aussi un StripeObject sans .get()
        # / construct_from converts nested dicts recursively:
        # checkout.metadata is also a StripeObject without .get()
        objet_stripe_reel = StripeObject.construct_from(
            {
                'id': checkout_en_base.checkout_session_id_stripe,
                'payment_status': 'paid',
                'amount_total': montant_en_centimes,
                'metadata': {'signed_data': signed_data},
            },
            'sk_test_fake',
        )
        return checkout_en_base, objet_stripe_reel

    def test_stripe_object_n_a_plus_de_methode_get(self):
        """
        Test canari : documente le comportement de la lib stripe installée.
        / Canary test: documents the behavior of the installed stripe lib.

        Si ce test casse après un bump de stripe, c'est que le comportement
        de StripeObject a encore changé : vérifier tout le code qui
        manipule des objets Stripe avant de déployer.
        """
        objet_stripe = StripeObject.construct_from({'cle': 'valeur'}, 'sk_test_fake')

        # .get() n'existe plus depuis stripe 12 : AttributeError attendu
        # / .get() is gone since stripe 12: AttributeError expected
        with self.assertRaises(AttributeError):
            objet_stripe.get('cle')

        # Les remplacements utilisés dans views.py fonctionnent
        # / The replacements used in views.py do work
        self.assertEqual(getattr(objet_stripe, 'cle', None), 'valeur')
        self.assertIsNone(getattr(objet_stripe, 'cle_absente', None))
        self.assertEqual(objet_stripe['cle'], 'valeur')
        self.assertEqual(objet_stripe.cle, 'valeur')

    @patch('fedow_core.views.stripe.checkout.Session.retrieve')
    def test_recharge_en_ligne_credite_le_wallet(self, mock_session_retrieve):
        """
        Une recharge en ligne payée crédite le wallet de l'utilisateur.
        / A paid online refill credits the user wallet.

        FLUX :
        1. Le checkout est en base, le paiement est validé chez Stripe
        2. Session.retrieve renvoie un VRAI StripeObject (mocké, sans réseau)
        3. validate_stripe_checkout_and_make_transaction lit les metadata
        4. Une transaction CREATION puis une REFILL sont écrites dans la chaîne
        5. Le token de l'utilisateur est crédité du montant payé
        """
        montant_paye_en_centimes = 4242
        checkout_en_base, objet_stripe_reel = \
            self._construire_checkout_paye_avec_vrai_stripe_object(montant_paye_en_centimes)
        mock_session_retrieve.return_value = objet_stripe_reel

        # Requête nue : le webhook Stripe n'a pas de place authentifiée
        # / Bare request: the Stripe webhook has no authenticated place
        requete_webhook = APIRequestFactory().get('/webhook_stripe/')

        checkout_en_base = StripeAPI.validate_stripe_checkout_and_make_transaction(
            checkout_en_base, requete_webhook)

        # Le checkout est passé en PAID
        # / The checkout switched to PAID
        self.assertEqual(checkout_en_base.status, CheckoutStripe.PAID)

        # La monnaie a d'abord été créée (CREATION), puis transférée (REFILL)
        # / Money was minted (CREATION) then transferred (REFILL)
        transaction_creation = Transaction.objects.get(
            action=Transaction.CREATION,
            checkout_stripe=checkout_en_base,
        )
        self.assertEqual(transaction_creation.amount, montant_paye_en_centimes)

        transaction_refill = Transaction.objects.get(
            action=Transaction.REFILL,
            checkout_stripe=checkout_en_base,
        )
        self.assertEqual(transaction_refill.amount, montant_paye_en_centimes)
        self.assertEqual(transaction_refill.sender, self.primary_wallet)
        self.assertEqual(transaction_refill.receiver, self.wallet_utilisateur)

        # La chaîne de hash reste valide
        # / The hash chain stays valid
        self.assertTrue(transaction_creation.verify_hash())
        self.assertTrue(transaction_refill.verify_hash())

        # Le solde de l'utilisateur est crédité du montant exact
        # / The user balance is credited with the exact amount
        token_utilisateur = Token.objects.get(
            wallet=self.wallet_utilisateur,
            asset=self.stripe_asset,
        )
        self.assertEqual(token_utilisateur.value, montant_paye_en_centimes)

    @patch('fedow_core.views.stripe.checkout.Session.retrieve')
    def test_rejouer_le_meme_checkout_ne_credite_pas_deux_fois(self, mock_session_retrieve):
        """
        Rejouer la validation du même checkout ne crédite pas deux fois.
        / Replaying the same checkout validation does not credit twice.

        Simule la course entre le webhook POST et le GET de retour,
        ou un renvoi manuel du webhook depuis le dashboard Stripe.
        Le serializer TransactionW2W refuse une deuxième CREATION
        avec le même checkout stripe.
        """
        montant_paye_en_centimes = 4242
        checkout_en_base, objet_stripe_reel = \
            self._construire_checkout_paye_avec_vrai_stripe_object(montant_paye_en_centimes)
        mock_session_retrieve.return_value = objet_stripe_reel
        requete_webhook = APIRequestFactory().get('/webhook_stripe/')

        # Première validation : crédit normal
        # / First validation: normal credit
        StripeAPI.validate_stripe_checkout_and_make_transaction(
            checkout_en_base, requete_webhook)

        # Deuxième validation forcée sur le même checkout : refusée
        # / Forced second validation on the same checkout: rejected
        with self.assertRaises(ValidationError):
            StripeAPI.validate_stripe_checkout_and_make_transaction(
                checkout_en_base, requete_webhook)

        # Le solde n'a pas bougé, une seule REFILL existe
        # / Balance unchanged, only one REFILL exists
        token_utilisateur = Token.objects.get(
            wallet=self.wallet_utilisateur,
            asset=self.stripe_asset,
        )
        self.assertEqual(token_utilisateur.value, montant_paye_en_centimes)
        self.assertEqual(
            Transaction.objects.filter(
                action=Transaction.REFILL,
                checkout_stripe=checkout_en_base,
            ).count(),
            1,
        )

    @patch('fedow_core.views.stripe.PaymentIntent.retrieve')
    def test_recharge_par_tpe_credite_le_wallet_de_la_carte(self, mock_payment_intent_retrieve):
        """
        Un paiement TPE (Wise POS) crédite le wallet de la carte NFC.
        / A Stripe terminal payment credits the NFC card wallet.

        FLUX :
        1. Le serveur cashless signe {fedow_place_uuid, tag_id} avec sa clé RSA
        2. Ces données signées sont dans les metadata du PaymentIntent
        3. PaymentIntent.retrieve renvoie un VRAI StripeObject (mocké)
        4. La signature est vérifiée avec la clé publique cashless de la place
        5. Le wallet de la carte est crédité de amount_received

        Couvre la régression stripe_payment.get('created') -> .created
        """
        # La place connaît la clé publique du serveur cashless simulé
        # / The place knows the simulated cashless server public key
        self.place.cashless_rsa_pub_key = self.public_cashless_pem
        self.place.save()

        # Création d'une carte NFC sans utilisateur, comme en caisse
        # / Creates an NFC card without user, like at the POS
        generation_origine = Origin.objects.create(place=self.place, generation=1)
        complete_tag_id_uuid = str(uuid4())
        qrcode_uuid = str(uuid4())
        carte_nfc = Card.objects.create(
            complete_tag_id_uuid=complete_tag_id_uuid,
            first_tag_id=f"{complete_tag_id_uuid.split('-')[0]}",
            qrcode_uuid=qrcode_uuid,
            number_printed=f"{qrcode_uuid.split('-')[0]}",
            origin=generation_origine,
        )

        # Le serveur cashless signe les données du paiement
        # / The cashless server signs the payment data
        donnees_signees_par_cashless = {
            'fedow_place_uuid': str(self.place.uuid),
            'tag_id': carte_nfc.first_tag_id,
        }
        signature = sign_message(
            data_to_b64(donnees_signees_par_cashless),
            self.private_cashless_rsa,
        ).decode('utf-8')

        montant_recu_en_centimes = 2121
        horodatage_paiement = int(timezone.now().timestamp())
        payment_intent_id = f'pi_test_{uuid4().hex}'

        objet_stripe_reel = StripeObject.construct_from(
            {
                'id': payment_intent_id,
                'created': horodatage_paiement,
                'amount_received': montant_recu_en_centimes,
                'metadata': {
                    'data': json.dumps(donnees_signees_par_cashless),
                    'signature': signature,
                },
            },
            'sk_test_fake',
        )
        mock_payment_intent_retrieve.return_value = objet_stripe_reel

        requete_webhook = APIRequestFactory().post('/webhook_stripe/')

        checkout_en_base = StripeAPI.validate_stripe_reader_wise_pose_and_make_transaction(
            payment_intent_id, requete_webhook)

        # Le checkout créé trace bien le paiement TPE
        # / The created checkout records the terminal payment
        self.assertEqual(checkout_en_base.status, CheckoutStripe.WALLET_USER_OK)
        self.assertEqual(
            checkout_en_base.checkout_session_id_stripe,
            payment_intent_id,
        )

        # Le wallet de la carte est crédité du montant exact.
        # refresh_from_db obligatoire : la vue a créé le wallet éphémère
        # de la carte, notre instance Python ne le connaît pas encore
        # / The card wallet is credited with the exact amount.
        # refresh_from_db required: the view created the card ephemeral
        # wallet, our stale Python instance does not know it yet
        carte_nfc.refresh_from_db()
        wallet_de_la_carte = carte_nfc.get_wallet()
        token_de_la_carte = Token.objects.get(
            wallet=wallet_de_la_carte,
            asset=self.stripe_asset,
        )
        self.assertEqual(token_de_la_carte.value, montant_recu_en_centimes)

        # La REFILL est liée à la carte et la chaîne reste valide
        # / The REFILL is linked to the card and the chain stays valid
        transaction_refill = Transaction.objects.get(
            action=Transaction.REFILL,
            checkout_stripe=checkout_en_base,
        )
        self.assertEqual(transaction_refill.card, carte_nfc)
        self.assertEqual(transaction_refill.receiver, wallet_de_la_carte)
        self.assertTrue(transaction_refill.verify_hash())

    @patch('fedow_core.views.stripe.PaymentIntent.retrieve')
    def test_recharge_par_tpe_place_lespass_credite_sans_signature(self, mock_payment_intent_retrieve):
        """
        CHANTIER-04 (04A) : une place Lespass (lespass_domain renseigné, pas de
        cashless_rsa_pub_key) crédite la carte SANS signature de place.
        / A Lespass place (lespass_domain set, no cashless_rsa_pub_key) credits
        the card WITHOUT a place signature (mirror of the S6 extension).

        Le PaymentIntent Stripe sur le compte Root suffit : les metadata ne
        contiennent volontairement PAS de clé 'signature'. Si la lecture de
        metadata['signature'] n'était pas passée dans le else, ceci lèverait
        un KeyError (piège relevé en relecture Fable 5).
        """
        # Place Lespass de confiance : lespass_domain posé, pas de clé cashless
        # / Trusted Lespass place: lespass_domain set, no cashless key
        self.place.lespass_domain = 'kiosk-test.tibillet.localhost'
        self.place.cashless_rsa_pub_key = None
        self.place.save()

        generation_origine = Origin.objects.create(place=self.place, generation=1)
        complete_tag_id_uuid = str(uuid4())
        qrcode_uuid = str(uuid4())
        carte_nfc = Card.objects.create(
            complete_tag_id_uuid=complete_tag_id_uuid,
            first_tag_id=f"{complete_tag_id_uuid.split('-')[0]}",
            qrcode_uuid=qrcode_uuid,
            number_printed=f"{qrcode_uuid.split('-')[0]}",
            origin=generation_origine,
        )

        donnees_non_signees = {
            'fedow_place_uuid': str(self.place.uuid),
            'tag_id': carte_nfc.first_tag_id,
        }
        montant_recu_en_centimes = 1000
        payment_intent_id = f'pi_test_{uuid4().hex}'

        objet_stripe_reel = StripeObject.construct_from(
            {
                'id': payment_intent_id,
                'created': int(timezone.now().timestamp()),
                'amount_received': montant_recu_en_centimes,
                # Pas de clé 'signature' : c'est le point testé
                # / No 'signature' key: that is exactly what is tested
                'metadata': {
                    'data': json.dumps(donnees_non_signees),
                },
            },
            'sk_test_fake',
        )
        mock_payment_intent_retrieve.return_value = objet_stripe_reel

        requete_webhook = APIRequestFactory().post('/webhook_stripe/')

        checkout_en_base = StripeAPI.validate_stripe_reader_wise_pose_and_make_transaction(
            payment_intent_id, requete_webhook)

        self.assertEqual(checkout_en_base.status, CheckoutStripe.WALLET_USER_OK)

        carte_nfc.refresh_from_db()
        token_de_la_carte = Token.objects.get(
            wallet=carte_nfc.get_wallet(),
            asset=self.stripe_asset,
        )
        self.assertEqual(token_de_la_carte.value, montant_recu_en_centimes)

    @patch('fedow_core.views.stripe.PaymentIntent.retrieve')
    def test_recharge_par_tpe_place_cashless_signature_toujours_exigee(self, mock_payment_intent_retrieve):
        """
        Non-régression : une place LaBoutik (cashless_rsa_pub_key renseigné)
        exige toujours une signature de place valide.
        / Non-regression: a LaBoutik place (cashless_rsa_pub_key set) still
        requires a valid place signature.
        """
        self.place.cashless_rsa_pub_key = self.public_cashless_pem
        self.place.save()

        generation_origine = Origin.objects.create(place=self.place, generation=1)
        complete_tag_id_uuid = str(uuid4())
        qrcode_uuid = str(uuid4())
        carte_nfc = Card.objects.create(
            complete_tag_id_uuid=complete_tag_id_uuid,
            first_tag_id=f"{complete_tag_id_uuid.split('-')[0]}",
            qrcode_uuid=qrcode_uuid,
            number_printed=f"{qrcode_uuid.split('-')[0]}",
            origin=generation_origine,
        )

        donnees = {
            'fedow_place_uuid': str(self.place.uuid),
            'tag_id': carte_nfc.first_tag_id,
        }
        payment_intent_id = f'pi_test_{uuid4().hex}'

        # Signature RSA réelle mais calculée sur d'AUTRES données : verify_signature
        # renvoie False et la fonction lève son Exception explicite. Une chaîne
        # non-base64 lèverait un binascii.Error AVANT la vérification RSA, et le
        # test ne prouverait plus le bon chemin.
        # / Genuine RSA signature computed over DIFFERENT data: verify_signature
        # returns False and the function raises its explicit Exception. A
        # non-base64 string would raise binascii.Error BEFORE the RSA check,
        # and the test would no longer prove the right path.
        signature_sur_autres_donnees = sign_message(
            data_to_b64({'fedow_place_uuid': str(uuid4()), 'tag_id': 'autre_carte'}),
            self.private_cashless_rsa,
        ).decode('utf-8')

        objet_stripe_reel = StripeObject.construct_from(
            {
                'id': payment_intent_id,
                'created': int(timezone.now().timestamp()),
                'amount_received': 1000,
                'metadata': {
                    'data': json.dumps(donnees),
                    # Signature présente mais invalide : ne correspond pas aux données
                    # / Signature present but invalid: does not match the data
                    'signature': signature_sur_autres_donnees,
                },
            },
            'sk_test_fake',
        )
        mock_payment_intent_retrieve.return_value = objet_stripe_reel

        requete_webhook = APIRequestFactory().post('/webhook_stripe/')

        with self.assertRaisesRegex(Exception, 'Signature verification failed'):
            StripeAPI.validate_stripe_reader_wise_pose_and_make_transaction(
                payment_intent_id, requete_webhook)

        # Aucun crédit n'a eu lieu
        # / No credit happened
        self.assertFalse(
            CheckoutStripe.objects.filter(checkout_session_id_stripe=payment_intent_id).exists())

    @patch('fedow_core.views.stripe.PaymentIntent.retrieve')
    def test_recharge_par_tpe_rejoue_leve_integrity_error(self, mock_payment_intent_retrieve):
        """
        CHANTIER-04 (04B) : rejouer le même payment_intent_stripe_id lève une
        IntegrityError (contrainte unique sur checkout_session_id_stripe), au
        lieu de créditer deux fois.
        / Replaying the same payment_intent_stripe_id raises an IntegrityError
        (unique constraint on checkout_session_id_stripe) instead of a double
        credit.

        C'est le garde-fou dont dépend la décision « pas de signature côté
        Lespass » (§8bis) : sans lui, une redélivrance concurrente pourrait
        doublement créditer une place de confiance sans facteur de sécurité
        additionnel.
        """
        self.place.lespass_domain = 'kiosk-test.tibillet.localhost'
        self.place.cashless_rsa_pub_key = None
        self.place.save()

        generation_origine = Origin.objects.create(place=self.place, generation=1)
        complete_tag_id_uuid = str(uuid4())
        qrcode_uuid = str(uuid4())
        carte_nfc = Card.objects.create(
            complete_tag_id_uuid=complete_tag_id_uuid,
            first_tag_id=f"{complete_tag_id_uuid.split('-')[0]}",
            qrcode_uuid=qrcode_uuid,
            number_printed=f"{qrcode_uuid.split('-')[0]}",
            origin=generation_origine,
        )

        donnees_non_signees = {
            'fedow_place_uuid': str(self.place.uuid),
            'tag_id': carte_nfc.first_tag_id,
        }
        payment_intent_id = f'pi_test_{uuid4().hex}'

        objet_stripe_reel = StripeObject.construct_from(
            {
                'id': payment_intent_id,
                'created': int(timezone.now().timestamp()),
                'amount_received': 1000,
                'metadata': {'data': json.dumps(donnees_non_signees)},
            },
            'sk_test_fake',
        )
        mock_payment_intent_retrieve.return_value = objet_stripe_reel

        requete_webhook = APIRequestFactory().post('/webhook_stripe/')

        # Premier passage : crédit normal
        # / First pass: normal credit
        StripeAPI.validate_stripe_reader_wise_pose_and_make_transaction(
            payment_intent_id, requete_webhook)

        # Deuxième passage sur le même payment_intent_stripe_id : la contrainte
        # unique sur checkout_session_id_stripe bloque le doublon
        # / Second pass on the same payment_intent_stripe_id: the unique
        # constraint on checkout_session_id_stripe blocks the duplicate
        with self.assertRaises(IntegrityError):
            StripeAPI.validate_stripe_reader_wise_pose_and_make_transaction(
                payment_intent_id, requete_webhook)

        # Une seule REFILL a été créée
        # / Only one REFILL was created
        self.assertEqual(
            Transaction.objects.filter(
                action=Transaction.REFILL,
                checkout_stripe__checkout_session_id_stripe=payment_intent_id,
            ).count(),
            1,
        )


# Secret de webhook utilisé uniquement par les tests, jamais en prod
# / Webhook secret used by tests only, never in production
SECRET_ENDPOINT_STRIPE_DE_TEST = 'whsec_test_fedow_regression'


class WebhookStripeEndToEndTest(FedowTestCase):
    """
    Teste la vue POST /webhook_stripe/ de bout en bout.
    / End-to-end tests of the POST /webhook_stripe/ view.

    FLUX TESTÉ :
    1. Stripe envoie un POST signé (en-tête Stripe-Signature, HMAC-SHA256)
    2. La permission IsStripe vérifie la signature avec construct_event
       (vrai code de la lib stripe, pas de mock sur la vérification)
    3. La vue route selon le type d'événement
    4. Seul l'appel réseau Session.retrieve / PaymentIntent.retrieve est
       mocké, avec un VRAI StripeObject (voir StripeRefillRegressionTest)

    Le secret du endpoint est injecté en patchant
    Configuration.get_stripe_endpoint_secret : la signature calculée par
    le test est donc vérifiée par la vraie mécanique Stripe.
    """

    def setUp(self):
        super().setUp()
        self.config = Configuration.get_solo()
        self.primary_wallet = self.config.primary_wallet
        self.stripe_asset = Asset.objects.get(
            wallet_origin=self.primary_wallet,
            category=Asset.STRIPE_FED_FIAT,
        )
        wallet_utilisateur, _private_pem, _public_pem = self.create_wallet_via_api()
        self.wallet_utilisateur = wallet_utilisateur
        self.utilisateur = wallet_utilisateur.user

        # Toute la classe vérifie les signatures avec le secret de test
        # / The whole class checks signatures against the test secret
        patcher_secret = patch.object(
            Configuration,
            'get_stripe_endpoint_secret',
            return_value=SECRET_ENDPOINT_STRIPE_DE_TEST,
        )
        patcher_secret.start()
        self.addCleanup(patcher_secret.stop)

    def _construire_checkout_paye(self, montant_en_centimes):
        """
        Prépare un CheckoutStripe en base et le StripeObject correspondant.
        / Builds a CheckoutStripe row and the matching real StripeObject.
        """
        token_primaire, _created = Token.objects.get_or_create(
            wallet=self.primary_wallet,
            asset=self.stripe_asset,
        )
        token_utilisateur, _created = Token.objects.get_or_create(
            wallet=self.wallet_utilisateur,
            asset=self.stripe_asset,
        )
        metadata_a_signer = {
            'primary_token': str(token_primaire.uuid),
            'user_token': str(token_utilisateur.uuid),
        }
        signed_data = Signer().sign(dict_to_b64_utf8(metadata_a_signer))
        checkout_en_base = CheckoutStripe.objects.create(
            checkout_session_id_stripe=f'cs_test_{uuid4().hex}',
            asset=self.stripe_asset,
            user=self.utilisateur,
            metadata=signed_data,
            status=CheckoutStripe.OPEN,
        )
        objet_stripe_reel = StripeObject.construct_from(
            {
                'id': checkout_en_base.checkout_session_id_stripe,
                'payment_status': 'paid',
                'amount_total': montant_en_centimes,
                'metadata': {'signed_data': signed_data},
            },
            'sk_test_fake',
        )
        return checkout_en_base, signed_data, objet_stripe_reel

    def _entete_signature_stripe(self, corps_json: str) -> str:
        """
        Calcule l'en-tête Stripe-Signature comme le ferait Stripe.
        / Computes the Stripe-Signature header like Stripe does.

        Format documenté : "t=<horodatage>,v1=<hmac_sha256>"
        où le HMAC signe "<horodatage>.<corps_brut>" avec le secret
        du endpoint. C'est exactement ce que construct_event vérifie.
        """
        horodatage = int(time.time())
        message_a_signer = f"{horodatage}.{corps_json}".encode('utf-8')
        empreinte_v1 = hmac.new(
            SECRET_ENDPOINT_STRIPE_DE_TEST.encode('utf-8'),
            message_a_signer,
            hashlib.sha256,
        ).hexdigest()
        return f"t={horodatage},v1={empreinte_v1}"

    def _poster_webhook_signe(self, payload: dict):
        """
        POST le payload sur /webhook_stripe/ avec une signature valide.
        / POSTs the payload to /webhook_stripe/ with a valid signature.
        """
        # stripe 15 exige la clé 'object': 'event' : construct_event lit
        # event.object après la vérification de signature et crashe sinon
        # / stripe 15 requires 'object': 'event' in the payload:
        # construct_event reads event.object after signature verification
        payload.setdefault('object', 'event')
        corps_json = json.dumps(payload)
        return self.client.post(
            '/webhook_stripe/',
            corps_json,
            content_type='application/json',
            headers={'Stripe-Signature': self._entete_signature_stripe(corps_json)},
        )

    @patch('fedow_core.views.stripe.checkout.Session.retrieve')
    def test_webhook_paiement_valide_credite_et_repond_200(self, mock_session_retrieve):
        """
        Un webhook checkout.session.completed signé crédite et répond 200.
        / A signed checkout.session.completed webhook credits and returns 200.
        """
        montant_paye_en_centimes = 4242
        checkout_en_base, signed_data, objet_stripe_reel = \
            self._construire_checkout_paye(montant_paye_en_centimes)
        mock_session_retrieve.return_value = objet_stripe_reel

        payload_stripe = {
            'type': 'checkout.session.completed',
            'data': {'object': {
                'id': checkout_en_base.checkout_session_id_stripe,
                'metadata': {'signed_data': signed_data},
            }},
        }
        reponse = self._poster_webhook_signe(payload_stripe)

        self.assertEqual(reponse.status_code, 200)

        checkout_en_base.refresh_from_db()
        self.assertEqual(checkout_en_base.status, CheckoutStripe.PAID)

        token_utilisateur = Token.objects.get(
            wallet=self.wallet_utilisateur,
            asset=self.stripe_asset,
        )
        self.assertEqual(token_utilisateur.value, montant_paye_en_centimes)

    @patch('fedow_core.views.stripe.checkout.Session.retrieve')
    def test_webhook_rejoue_repond_208_sans_double_credit(self, mock_session_retrieve):
        """
        Rejouer le même webhook répond 208 et ne crédite pas deux fois.
        / Replaying the same webhook returns 208 without double credit.

        C'est le scénario du renvoi manuel depuis le dashboard Stripe
        ou du retry automatique de Stripe après un timeout.
        """
        montant_paye_en_centimes = 4242
        checkout_en_base, signed_data, objet_stripe_reel = \
            self._construire_checkout_paye(montant_paye_en_centimes)
        mock_session_retrieve.return_value = objet_stripe_reel

        payload_stripe = {
            'type': 'checkout.session.completed',
            'data': {'object': {
                'id': checkout_en_base.checkout_session_id_stripe,
                'metadata': {'signed_data': signed_data},
            }},
        }

        premiere_reponse = self._poster_webhook_signe(payload_stripe)
        self.assertEqual(premiere_reponse.status_code, 200)

        deuxieme_reponse = self._poster_webhook_signe(payload_stripe)
        self.assertEqual(deuxieme_reponse.status_code, 208)

        # Le solde n'a pas bougé, une seule REFILL existe
        # / Balance unchanged, only one REFILL exists
        token_utilisateur = Token.objects.get(
            wallet=self.wallet_utilisateur,
            asset=self.stripe_asset,
        )
        self.assertEqual(token_utilisateur.value, montant_paye_en_centimes)
        self.assertEqual(
            Transaction.objects.filter(
                action=Transaction.REFILL,
                checkout_stripe=checkout_en_base,
            ).count(),
            1,
        )

    def test_webhook_type_etranger_repond_204(self):
        """
        Un événement Stripe d'un autre type est ignoré avec un 204.
        / A Stripe event of another type is ignored with a 204.
        """
        payload_stripe = {
            'type': 'invoice.paid',
            'data': {'object': {'id': f'in_test_{uuid4().hex}'}},
        }
        reponse = self._poster_webhook_signe(payload_stripe)
        self.assertEqual(reponse.status_code, 204)

    def test_webhook_sans_signed_data_repond_203(self):
        """
        Un checkout.session.completed sans signed_data est rejeté en 203.
        / A checkout.session.completed without signed_data is rejected (203).
        """
        payload_stripe = {
            'type': 'checkout.session.completed',
            'data': {'object': {
                'id': f'cs_test_{uuid4().hex}',
                'metadata': {},
            }},
        }
        reponse = self._poster_webhook_signe(payload_stripe)
        self.assertEqual(reponse.status_code, 203)

    def test_webhook_signature_invalide_est_refuse(self):
        """
        Un POST avec une mauvaise signature Stripe est refusé.
        / A POST with a wrong Stripe signature is denied.
        """
        corps_json = json.dumps({
            'type': 'checkout.session.completed',
            'data': {'object': {'id': 'cs_test_pirate'}},
        })
        reponse = self.client.post(
            '/webhook_stripe/',
            corps_json,
            content_type='application/json',
            headers={'Stripe-Signature': 't=12345,v1=signature_falsifiee'},
        )
        # DRF renvoie 401 ou 403 selon la classe d'authentification active
        # / DRF returns 401 or 403 depending on the active auth class
        self.assertIn(reponse.status_code, (401, 403))

        # Aucune transaction n'a été créée par l'intrus
        # / No transaction was created by the intruder
        self.assertFalse(
            Transaction.objects.filter(action=Transaction.REFILL).exists())

    @patch('fedow_core.views.stripe.PaymentIntent.retrieve')
    def test_webhook_tpe_wise_pos_credite_et_repond_200(self, mock_payment_intent_retrieve):
        """
        Un webhook terminal.reader.action_succeeded crédite la carte (200),
        et son rejeu répond 208 sans double crédit.
        / A terminal.reader.action_succeeded webhook credits the card (200),
        replaying it returns 208 without double credit.
        """
        # La place connaît la clé publique du serveur cashless simulé
        # / The place knows the simulated cashless server public key
        self.place.cashless_rsa_pub_key = self.public_cashless_pem
        self.place.save()

        # Carte NFC anonyme, comme en caisse
        # / Anonymous NFC card, like at the POS
        generation_origine = Origin.objects.create(place=self.place, generation=1)
        complete_tag_id_uuid = str(uuid4())
        qrcode_uuid = str(uuid4())
        carte_nfc = Card.objects.create(
            complete_tag_id_uuid=complete_tag_id_uuid,
            first_tag_id=f"{complete_tag_id_uuid.split('-')[0]}",
            qrcode_uuid=qrcode_uuid,
            number_printed=f"{qrcode_uuid.split('-')[0]}",
            origin=generation_origine,
        )

        donnees_signees_par_cashless = {
            'fedow_place_uuid': str(self.place.uuid),
            'tag_id': carte_nfc.first_tag_id,
        }
        signature_cashless = sign_message(
            data_to_b64(donnees_signees_par_cashless),
            self.private_cashless_rsa,
        ).decode('utf-8')

        montant_recu_en_centimes = 2121
        payment_intent_id = f'pi_test_{uuid4().hex}'
        mock_payment_intent_retrieve.return_value = StripeObject.construct_from(
            {
                'id': payment_intent_id,
                'created': int(timezone.now().timestamp()),
                'amount_received': montant_recu_en_centimes,
                'metadata': {
                    'data': json.dumps(donnees_signees_par_cashless),
                    'signature': signature_cashless,
                },
            },
            'sk_test_fake',
        )

        payload_stripe = {
            'type': 'terminal.reader.action_succeeded',
            'data': {'object': {'action': {'process_payment_intent': {
                'payment_intent': payment_intent_id,
            }}}},
        }

        reponse = self._poster_webhook_signe(payload_stripe)
        self.assertEqual(reponse.status_code, 200)

        # Le wallet éphémère de la carte est crédité
        # / The card ephemeral wallet is credited
        carte_nfc.refresh_from_db()
        token_de_la_carte = Token.objects.get(
            wallet=carte_nfc.get_wallet(),
            asset=self.stripe_asset,
        )
        self.assertEqual(token_de_la_carte.value, montant_recu_en_centimes)

        # Rejeu du même payment intent : 208, pas de double crédit
        # / Replay of the same payment intent: 208, no double credit
        reponse_rejeu = self._poster_webhook_signe(payload_stripe)
        self.assertEqual(reponse_rejeu.status_code, 208)
        token_de_la_carte.refresh_from_db()
        self.assertEqual(token_de_la_carte.value, montant_recu_en_centimes)

    @patch('fedow_core.views.stripe.PaymentIntent.retrieve')
    def test_webhook_tpe_rejeu_concurrent_repond_208_via_integrity_error(
            self, mock_payment_intent_retrieve):
        """
        CHANTIER-04 (04B) : si le rejeu passe le pré-filtre exists() (fenêtre
        TOCTOU d'une redélivrance vraiment concurrente), la contrainte unique
        sur checkout_session_id_stripe lève une IntegrityError que la vue
        capte pour répondre 208 au lieu de planter en 500.
        / If the replay slips past the exists() pre-filter (TOCTOU window of a
        truly concurrent redelivery), the unique constraint on
        checkout_session_id_stripe raises an IntegrityError that the view
        catches to answer 208 instead of crashing with a 500.
        """
        self.place.lespass_domain = 'kiosk-test.tibillet.localhost'
        self.place.cashless_rsa_pub_key = None
        self.place.save()

        generation_origine = Origin.objects.create(place=self.place, generation=1)
        complete_tag_id_uuid = str(uuid4())
        qrcode_uuid = str(uuid4())
        carte_nfc = Card.objects.create(
            complete_tag_id_uuid=complete_tag_id_uuid,
            first_tag_id=f"{complete_tag_id_uuid.split('-')[0]}",
            qrcode_uuid=qrcode_uuid,
            number_printed=f"{qrcode_uuid.split('-')[0]}",
            origin=generation_origine,
        )

        donnees_non_signees = {
            'fedow_place_uuid': str(self.place.uuid),
            'tag_id': carte_nfc.first_tag_id,
        }
        montant_recu_en_centimes = 1500
        payment_intent_id = f'pi_test_{uuid4().hex}'
        mock_payment_intent_retrieve.return_value = StripeObject.construct_from(
            {
                'id': payment_intent_id,
                'created': int(timezone.now().timestamp()),
                'amount_received': montant_recu_en_centimes,
                'metadata': {'data': json.dumps(donnees_non_signees)},
            },
            'sk_test_fake',
        )

        payload_stripe = {
            'type': 'terminal.reader.action_succeeded',
            'data': {'object': {'action': {'process_payment_intent': {
                'payment_intent': payment_intent_id,
            }}}},
        }

        reponse = self._poster_webhook_signe(payload_stripe)
        self.assertEqual(reponse.status_code, 200)

        # Simule la fenêtre TOCTOU : le pré-filtre exists() ne voit pas encore
        # le CheckoutStripe créé par le premier passage (redélivrance vraiment
        # concurrente). Seule la contrainte unique en base protège alors.
        # / Simulates the TOCTOU window: the exists() pre-filter does not see
        # the CheckoutStripe created by the first pass yet (a truly concurrent
        # redelivery). Only the DB unique constraint protects at that point.
        with patch('fedow_core.views.CheckoutStripe.objects.filter') as mock_filter:
            mock_filter.return_value.exists.return_value = False
            reponse_rejeu = self._poster_webhook_signe(payload_stripe)

        self.assertEqual(reponse_rejeu.status_code, 208)

        # Pas de double crédit. refresh_from_db obligatoire : la vue a créé le
        # wallet éphémère de la carte au premier passage, notre instance
        # Python ne le connaît pas encore.
        # / No double credit. refresh_from_db required: the view created the
        # card ephemeral wallet on the first pass, our stale Python instance
        # does not know it yet.
        carte_nfc.refresh_from_db()
        token_de_la_carte = Token.objects.get(
            wallet=carte_nfc.get_wallet(),
            asset=self.stripe_asset,
        )
        self.assertEqual(token_de_la_carte.value, montant_recu_en_centimes)
