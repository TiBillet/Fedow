"""
Appariement CREATION <-> REFILL sous concurrence.
/ CREATION <-> REFILL pairing under concurrency.

LOCALISATION : fedow_core/tests/test_refill_creation_pairing.py

POURQUOI CE FICHIER :
Les 28-29/08/2026, 24 recharges Stripe ont ete payees sans jamais etre creditees
(381,00 EUR bloques sur le wallet primaire). Issues Sentry FEDOW-DJANGO-4M
(l'AssertionError d'origine, 24 evenements) et 4N / 4P (les 118 + 102 retries
Stripe qui ont suivi).

Transaction.save() validait un REFILL avec :

    assert self.previous_transaction.action == Transaction.CREATION

or previous_transaction = _previous_asset_transaction() = la derniere transaction
de l'ASSET ENTIER, lue sans verrou. Une recharge ecrit CREATION puis REFILL sur un
asset partage par tout le reseau ; avec 5 workers gunicorn, deux recharges
simultanees s'entrelacent :

    CRE_A -> CRE_B -> REF_A (precedent = CRE_B, passe) -> REF_B (precedent = REF_A) 💥

et comme la paire n'etait pas atomique, la CREATION de B restait committee :
monnaie creee, jamais transferee, blocage definitif.

L'invariant metier correct est "il existe une creation monetaire qui adosse CE
refill", pas "la derniere transaction de l'asset est une creation".
Cf TECH_DEV/DRIFT/README.md §6.

CE QUI EST TESTE :
 1. L'entrelacement concurrent n'empeche plus les deux recharges d'aboutir.
 2. Une recharge Stripe peut etre rejouee des mois plus tard (rattrapage).
 3. Un REFILL sans aucune creation monetaire reste refuse.
 4. Une creation_associee incoherente est refusee.
"""
from unittest.mock import patch
from uuid import uuid4

from django.core.signing import Signer
from django.db import IntegrityError
from django.db.utils import OperationalError
from rest_framework.test import APIRequestFactory
from stripe import StripeObject

from fedow_core.models import (
    Asset, Card, CheckoutStripe, Configuration, Origin, Token, Transaction, Wallet,
)
from fedow_core.serializers import TransactionW2W
from fedow_core.tests.tests import FedowTestCase
from fedow_core.utils import dict_to_b64_utf8
from fedow_core.views import StripeAPI


class RefillCreationPairingTest(FedowTestCase):
    """
    Regression de l'incident du 28-29/08/2026 : appariement CREATION/REFILL.
    / Regression test for the 2026-08-28 lost refills incident.
    """

    def setUp(self):
        super().setUp()
        self.wallet_du_lieu = self.place.wallet
        self.wallet_client_a, _, _ = self.create_wallet_via_api(email='client.a@test.test')
        self.wallet_client_b, _, _ = self.create_wallet_via_api(email='client.b@test.test')

        # Une monnaie locale du lieu : le REFILL local est soumis a la meme course
        # que le federe, c'est le meme code dans Transaction.save().
        # / A local currency: local refills race exactly like the federated ones.
        self.asset_local = Asset.objects.create(
            name="Testoune",
            currency_code="TST",
            category=Asset.TOKEN_LOCAL_FIAT,
            wallet_origin=self.wallet_du_lieu,
        )
        for wallet in (self.wallet_du_lieu, self.wallet_client_a, self.wallet_client_b):
            Token.objects.get_or_create(wallet=wallet, asset=self.asset_local)

    def _creation_locale(self, montant):
        # Emission de monnaie par le lieu : sender == receiver == wallet du lieu.
        # / Local mint by the place.
        return Transaction.objects.create(
            ip="127.0.0.1",
            sender=self.wallet_du_lieu,
            receiver=self.wallet_du_lieu,
            asset=self.asset_local,
            amount=montant,
            action=Transaction.CREATION,
        )

    def _refill_local(self, montant, wallet_destinataire, creation_associee=None):
        transaction = Transaction(
            ip="127.0.0.1",
            sender=self.wallet_du_lieu,
            receiver=wallet_destinataire,
            asset=self.asset_local,
            amount=montant,
            action=Transaction.REFILL,
        )
        if creation_associee is not None:
            transaction.creation_associee = creation_associee
        transaction.save(force_insert=True)
        return transaction

    def test_deux_recharges_entrelacees_aboutissent_toutes_les_deux(self):
        """
        La sequence exacte que produisait la course entre deux workers.
        / The exact sequence the race between two workers produced.

        Avant le correctif, le second REFILL levait AssertionError
        "Previous transaction of Refill must be a creation money." parce que son
        previous_transaction etait le premier REFILL. Le test est deterministe :
        on rejoue la sequence, pas le parallelisme.
        """
        creation_a = self._creation_locale(1000)
        creation_b = self._creation_locale(2000)

        refill_a = self._refill_local(1000, self.wallet_client_a)
        # C'est CELUI-CI qui cassait : son precedent dans la chaine est refill_a.
        # / This is the one that used to blow up.
        refill_b = self._refill_local(2000, self.wallet_client_b)

        self.assertEqual(refill_b.previous_transaction, refill_a,
                         "La sequence entrelacee doit bien etre reproduite")

        token_a = Token.objects.get(wallet=self.wallet_client_a, asset=self.asset_local)
        token_b = Token.objects.get(wallet=self.wallet_client_b, asset=self.asset_local)
        self.assertEqual(token_a.value, 1000)
        self.assertEqual(token_b.value, 2000)

        # Le lieu a emis 3000 et transfere 3000 : son token retombe a zero.
        # / The place minted 3000 and moved 3000: back to zero.
        token_du_lieu = Token.objects.get(wallet=self.wallet_du_lieu, asset=self.asset_local)
        self.assertEqual(token_du_lieu.value, 0)

        for transaction in (creation_a, creation_b, refill_a, refill_b):
            self.assertTrue(transaction.verify_hash())

    def test_recharge_stripe_rejouee_apres_coup_est_acceptee(self):
        """
        Le scenario du rattrapage : creer aujourd'hui le REFILL d'une CREATION
        orpheline d'aout, alors que la chaine de l'asset a continue d'avancer.
        / Replaying a months-old orphan CREATION, chain having moved on since.
        """
        configuration = Configuration.get_solo()
        wallet_primaire = configuration.primary_wallet
        asset_federe = Asset.objects.get(
            wallet_origin=wallet_primaire, category=Asset.STRIPE_FED_FIAT)
        Token.objects.get_or_create(wallet=self.wallet_client_a, asset=asset_federe)
        Token.objects.get_or_create(wallet=self.wallet_client_b, asset=asset_federe)

        checkout_orphelin = CheckoutStripe.objects.create(
            checkout_session_id_stripe="cs_test_orpheline_du_28_aout",
            asset=asset_federe,
            status=CheckoutStripe.ERROR,
            metadata="",
        )
        creation_orpheline = Transaction.objects.create(
            ip="127.0.0.1",
            checkout_stripe=checkout_orphelin,
            sender=wallet_primaire,
            receiver=wallet_primaire,
            asset=asset_federe,
            amount=2500,
            action=Transaction.CREATION,
        )

        # La vie continue sur l'asset : une autre recharge passe entre-temps.
        # / Life goes on: another refill lands in between.
        checkout_suivant = CheckoutStripe.objects.create(
            checkout_session_id_stripe="cs_test_recharge_suivante",
            asset=asset_federe,
            status=CheckoutStripe.PAID,
            metadata="",
        )
        creation_suivante = Transaction.objects.create(
            ip="127.0.0.1",
            checkout_stripe=checkout_suivant,
            sender=wallet_primaire,
            receiver=wallet_primaire,
            asset=asset_federe,
            amount=500,
            action=Transaction.CREATION,
        )
        refill_suivant = Transaction(
            ip="127.0.0.1",
            checkout_stripe=checkout_suivant,
            sender=wallet_primaire,
            receiver=self.wallet_client_b,
            asset=asset_federe,
            amount=500,
            action=Transaction.REFILL,
        )
        refill_suivant.creation_associee = creation_suivante
        refill_suivant.save(force_insert=True)

        # Le rattrapage : aucune creation_associee passee en clair, et le precedent
        # dans la chaine n'est PAS une CREATION. L'appariement se fait par checkout.
        # / The repair: paired by checkout, not by chain position.
        refill_de_rattrapage = Transaction(
            ip="127.0.0.1",
            checkout_stripe=checkout_orphelin,
            sender=wallet_primaire,
            receiver=self.wallet_client_a,
            asset=asset_federe,
            amount=2500,
            action=Transaction.REFILL,
        )
        refill_de_rattrapage.save(force_insert=True)

        self.assertNotEqual(refill_de_rattrapage.previous_transaction.action,
                            Transaction.CREATION,
                            "Le precedent ne doit justement PAS etre une creation")
        self.assertTrue(refill_de_rattrapage.verify_hash())
        token_client = Token.objects.get(wallet=self.wallet_client_a, asset=asset_federe)
        self.assertEqual(token_client.value, 2500)
        self.assertTrue(creation_orpheline.verify_hash())
        self.assertTrue(refill_suivant.verify_hash())

    def test_refill_sans_aucune_creation_reste_refuse(self):
        """
        Le garde-fou de fond : pas de monnaie creee, pas de recharge possible.
        / No mint at all, no refill.
        """
        asset_vierge = Asset.objects.create(
            name="Sansmonnaie",
            currency_code="SAN",
            category=Asset.TOKEN_LOCAL_FIAT,
            wallet_origin=self.wallet_du_lieu,
        )
        Token.objects.get_or_create(wallet=self.wallet_du_lieu, asset=asset_vierge)
        Token.objects.get_or_create(wallet=self.wallet_client_a, asset=asset_vierge)

        with self.assertRaises(AssertionError) as contexte:
            Transaction.objects.create(
                ip="127.0.0.1",
                sender=self.wallet_du_lieu,
                receiver=self.wallet_client_a,
                asset=asset_vierge,
                amount=100,
                action=Transaction.REFILL,
            )
        self.assertIn("Previous transaction of Refill must be a creation money",
                      str(contexte.exception))

    @patch('fedow_core.views.stripe.checkout.Session.retrieve')
    def test_creation_rollbackee_si_le_refill_echoue(self, session_retrieve):
        """
        LE test du correctif d'atomicite.
        / THE atomicity test.

        C'est la CREATION restee committee alors que le REFILL echouait qui a
        immobilise 381,00 EUR en aout 2026 : monnaie creee, jamais transferee,
        et blocage definitif puisque l'anti-rejeu voyait ensuite cette CREATION.
        Ici on fait echouer le REFILL a coup sur, et on verifie qu'il ne reste
        RIEN : ni transaction, ni monnaie sur le wallet primaire.
        """
        checkout, token_primaire = self._construire_checkout_stripe_paye(
            4200, session_retrieve)

        creations_avant = Transaction.objects.filter(action=Transaction.CREATION).count()
        token_primaire.refresh_from_db()
        solde_primaire_avant = token_primaire.value

        # On fait echouer le REFILL, et lui seul : la CREATION passe, le REFILL casse.
        # / Break the refill only: the mint succeeds, the refill blows up.
        with patch.object(Transaction, '_verifie_creation_monetaire_associee',
                          side_effect=AssertionError("echec simule du refill")):
            with self.assertRaises(AssertionError):
                StripeAPI.validate_stripe_checkout_and_make_transaction(
                    checkout, APIRequestFactory().get('/webhook_stripe/'))

        self.assertEqual(
            Transaction.objects.filter(action=Transaction.CREATION).count(),
            creations_avant,
            "La CREATION doit avoir ete annulee avec le REFILL")
        self.assertEqual(
            Transaction.objects.filter(checkout_stripe=checkout).count(), 0,
            "Aucune transaction ne doit subsister pour ce checkout")
        token_primaire.refresh_from_db()
        self.assertEqual(token_primaire.value, solde_primaire_avant,
                         "Aucune monnaie ne doit avoir ete creee")

    def test_creation_associee_incoherente_est_refusee(self):
        """
        La branche d'appariement explicite ne doit pas etre un blanc-seing.
        / The explicit pairing branch must not be a free pass.
        """
        creation = self._creation_locale(1000)

        # Mauvaise action : on passe le REFILL precedent au lieu d'une CREATION.
        refill_valide = self._refill_local(1000, self.wallet_client_a, creation_associee=creation)
        creation_suivante = self._creation_locale(1000)
        with self.assertRaises(AssertionError) as contexte:
            self._refill_local(1000, self.wallet_client_b, creation_associee=refill_valide)
        self.assertIn("creation_associee must be a creation money", str(contexte.exception))

        # Montant insuffisant : la creation ne couvre pas la recharge.
        with self.assertRaises(AssertionError) as contexte:
            transaction = Transaction(
                ip="127.0.0.1",
                sender=self.wallet_du_lieu,
                receiver=self.wallet_client_b,
                asset=self.asset_local,
                amount=99999,
                action=Transaction.REFILL,
            )
            transaction.creation_associee = creation_suivante
            transaction.save(force_insert=True)
        self.assertIn("creation_associee amount must cover the refill", str(contexte.exception))

    def _construire_checkout_stripe_paye(self, montant, session_retrieve):
        """
        Prepare un checkout Stripe paye et le StripeObject correspondant.
        / Builds a paid Stripe checkout and its matching StripeObject.
        """
        wallet_primaire = Configuration.get_solo().primary_wallet
        asset_federe = Asset.objects.get(
            wallet_origin=wallet_primaire, category=Asset.STRIPE_FED_FIAT)
        token_primaire, _ = Token.objects.get_or_create(
            wallet=wallet_primaire, asset=asset_federe)
        token_utilisateur, _ = Token.objects.get_or_create(
            wallet=self.wallet_client_a, asset=asset_federe)

        donnees_signees = Signer().sign(dict_to_b64_utf8({
            'primary_token': str(token_primaire.uuid),
            'user_token': str(token_utilisateur.uuid),
        }))
        checkout = CheckoutStripe.objects.create(
            checkout_session_id_stripe=f'cs_test_{uuid4().hex}',
            asset=asset_federe,
            user=self.wallet_client_a.user,
            metadata=donnees_signees,
            status=CheckoutStripe.OPEN,
        )
        session_retrieve.return_value = StripeObject.construct_from({
            'id': checkout.checkout_session_id_stripe,
            'payment_status': 'paid',
            'amount_total': montant,
            'metadata': {'signed_data': donnees_signees},
        }, 'sk_test_fake')
        return checkout, token_primaire

    @patch('fedow_core.views.stripe.checkout.Session.retrieve')
    def test_rejoue_si_la_base_est_verrouillee_sans_creer_de_doublon(self, session_retrieve):
        """
        Sous forte affluence, SQLite peut refuser l'ecriture ("database is locked").
        On doit rejouer, et surtout ne PAS laisser de trace des tentatives ratees :
        une seule CREATION, un seul REFILL, le bon solde.
        / Retry on a locked database must leave exactly one mint and one refill.
        """
        checkout, _token_primaire = self._construire_checkout_stripe_paye(
            3300, session_retrieve)

        vraie_ecriture = TransactionW2W._ecrire_la_paire
        tentatives = {'nombre': 0}

        def echoue_deux_fois_puis_reussit(serializer, request, action):
            tentatives['nombre'] += 1
            if tentatives['nombre'] <= 2:
                raise OperationalError("database is locked")
            return vraie_ecriture(serializer, request, action)

        with patch.object(TransactionW2W, '_ecrire_la_paire',
                          echoue_deux_fois_puis_reussit):
            StripeAPI.validate_stripe_checkout_and_make_transaction(
                checkout, APIRequestFactory().get('/webhook_stripe/'))

        self.assertEqual(tentatives['nombre'], 3, "Il faut 2 echecs puis 1 reussite")
        self.assertEqual(
            Transaction.objects.filter(
                checkout_stripe=checkout, action=Transaction.CREATION).count(), 1,
            "Les tentatives ratees ne doivent laisser aucune CREATION")
        self.assertEqual(
            Transaction.objects.filter(
                checkout_stripe=checkout, action=Transaction.REFILL).count(), 1)
        token = Token.objects.get(wallet=self.wallet_client_a,
                                  asset=checkout.asset)
        self.assertEqual(token.value, 3300)

    @patch('fedow_core.views.stripe.checkout.Session.retrieve')
    def test_ne_rejoue_pas_une_erreur_qui_n_est_pas_un_verrou(self, session_retrieve):
        """
        Le retry vise le verrou SQLite, pas les autres pannes : une erreur de base
        differente doit remonter tout de suite, sans reessayer.
        / Only lock errors are retried; anything else surfaces immediately.
        """
        checkout, _token_primaire = self._construire_checkout_stripe_paye(
            1000, session_retrieve)

        tentatives = {'nombre': 0}

        def echoue_autrement(serializer, request, action):
            tentatives['nombre'] += 1
            raise OperationalError("disk I/O error")

        with patch.object(TransactionW2W, '_ecrire_la_paire', echoue_autrement):
            with self.assertRaises(OperationalError):
                StripeAPI.validate_stripe_checkout_and_make_transaction(
                    checkout, APIRequestFactory().get('/webhook_stripe/'))

        self.assertEqual(tentatives['nombre'], 1, "Une seule tentative attendue")

    @patch('fedow_core.views.stripe.checkout.Session.retrieve')
    def test_abandonne_apres_les_tentatives_prevues(self, session_retrieve):
        """
        Si la base reste verrouillee, on abandonne proprement : l'erreur remonte,
        et rien n'a ete ecrit.
        / When the lock never clears, fail cleanly with nothing written.
        """
        checkout, _token_primaire = self._construire_checkout_stripe_paye(
            1000, session_retrieve)

        tentatives = {'nombre': 0}

        def toujours_verrouille(serializer, request, action):
            tentatives['nombre'] += 1
            raise OperationalError("database is locked")

        with patch.object(TransactionW2W, '_ecrire_la_paire', toujours_verrouille):
            with self.assertRaises(OperationalError):
                StripeAPI.validate_stripe_checkout_and_make_transaction(
                    checkout, APIRequestFactory().get('/webhook_stripe/'))

        self.assertEqual(tentatives['nombre'], 3)
        self.assertEqual(Transaction.objects.filter(checkout_stripe=checkout).count(), 0)


class RetryLimiteAuCheminAtomiqueTest(FedowTestCase):
    """
    Le retry ne doit JAMAIS toucher une action non atomique.
    / The retry must never touch a non-atomic action.

    Hors REFILL, Transaction.save() committe les deux soldes en autocommit AVANT
    d'inserer la transaction. Un "database is locked" sur l'INSERT laisse donc le
    debit du client deja passe : rejouer le debiterait une seconde fois, en
    silence. Une vente ratee doit remonter l'erreur du premier coup.
    """

    def setUp(self):
        super().setUp()
        self.wallet_client, _, _ = self.create_wallet_via_api(email='acheteur@test.test')

        generation = Origin.objects.get_or_create(place=self.place, generation=1)[0]
        tag_carte = str(uuid4())
        self.carte_client = Card.objects.create(
            complete_tag_id_uuid=tag_carte,
            first_tag_id=tag_carte.split('-')[0],
            qrcode_uuid=str(uuid4()),
            number_printed="ACHETEUR",
            origin=generation,
            user=self.wallet_client.user,
        )
        tag_primaire = str(uuid4())
        self.carte_primaire = Card.objects.create(
            complete_tag_id_uuid=tag_primaire,
            first_tag_id=tag_primaire.split('-')[0],
            qrcode_uuid=str(uuid4()),
            number_printed="CAISSE",
            origin=generation,
        )
        self.carte_primaire.primary_places.add(self.place)

        self.asset_du_lieu = Asset.objects.create(
            name="Ventoune", currency_code="VTN",
            category=Asset.TOKEN_LOCAL_FIAT, wallet_origin=self.place.wallet,
        )
        Token.objects.get_or_create(wallet=self.place.wallet, asset=self.asset_du_lieu)
        Token.objects.get_or_create(wallet=self.wallet_client, asset=self.asset_du_lieu)
        # On charge la carte du client pour pouvoir lui vendre quelque chose.
        creation = Transaction.objects.create(
            ip="127.0.0.1", sender=self.place.wallet, receiver=self.place.wallet,
            asset=self.asset_du_lieu, amount=5000, action=Transaction.CREATION,
        )
        recharge = Transaction(
            ip="127.0.0.1", sender=self.place.wallet, receiver=self.wallet_client,
            asset=self.asset_du_lieu, amount=5000, action=Transaction.REFILL,
        )
        recharge.creation_associee = creation
        recharge.save(force_insert=True)

    def test_une_vente_verrouillee_n_est_jamais_rejouee(self):
        """
        Une SALE qui echoue sur un verrou ne doit etre tentee qu'UNE fois :
        son debit est deja committe, rejouer doublerait le debit du client.
        / A locked SALE must be attempted only once: the debit is already committed.
        """
        tentatives = {'nombre': 0}

        def echoue_sur_verrou(serializer, request, action):
            tentatives['nombre'] += 1
            raise OperationalError("database is locked")

        donnees_de_vente = {
            "amount": 1000,
            "sender": str(self.wallet_client.uuid),
            "receiver": str(self.place.wallet.uuid),
            "asset": str(self.asset_du_lieu.uuid),
            "user_card_firstTagId": self.carte_client.first_tag_id,
            "primary_card_fisrtTagId": self.carte_primaire.first_tag_id,
        }

        with patch.object(TransactionW2W, '_ecrire_la_paire', echoue_sur_verrou):
            with self.assertRaises(OperationalError):
                self._post_from_simulated_cashless('transaction', donnees_de_vente)

        self.assertEqual(
            tentatives['nombre'], 1,
            "Une vente ne doit JAMAIS etre rejouee : son debit est deja committe")


class ContrainteUnCreditParCheckoutTest(FedowTestCase):
    """
    La contrainte d'unicite (checkout_stripe, action) et son perimetre.
    / The (checkout_stripe, action) unique constraint and its scope.

    Elle rend structurellement impossible le double credit d'un meme paiement
    Stripe, la ou la regle ne vivait que dans un .exists() verifie hors verrou.
    Elle est VOLONTAIREMENT partielle : tout ce qui n'est pas une CREATION ou un
    REFILL adosse a un checkout doit rester parfaitement libre.
    """

    def setUp(self):
        super().setUp()
        self.wallet_primaire = Configuration.get_solo().primary_wallet
        self.asset_federe = Asset.objects.get(
            wallet_origin=self.wallet_primaire, category=Asset.STRIPE_FED_FIAT)
        self.wallet_client, _, _ = self.create_wallet_via_api(email='porteur@test.test')
        Token.objects.get_or_create(wallet=self.wallet_client, asset=self.asset_federe)
        self.checkout = CheckoutStripe.objects.create(
            checkout_session_id_stripe=f"cs_test_{uuid4().hex}",
            asset=self.asset_federe, status=CheckoutStripe.PAID, metadata="",
        )

    def _creation(self, **surcharges):
        donnees = dict(
            ip="127.0.0.1", checkout_stripe=self.checkout,
            sender=self.wallet_primaire, receiver=self.wallet_primaire,
            asset=self.asset_federe, amount=1000, action=Transaction.CREATION)
        donnees.update(surcharges)
        return Transaction.objects.create(**donnees)

    def test_un_second_credit_sur_le_meme_paiement_est_impossible(self):
        """
        Deux livraisons simultanees du meme event Stripe ne peuvent plus crediter
        deux fois : la base refuse le doublon.
        / Two concurrent deliveries can no longer double-credit.
        """
        creation = self._creation()
        refill = Transaction(
            ip="127.0.0.1", checkout_stripe=self.checkout,
            sender=self.wallet_primaire, receiver=self.wallet_client,
            asset=self.asset_federe, amount=1000, action=Transaction.REFILL)
        refill.creation_associee = creation
        refill.save(force_insert=True)

        # Le doublon de CREATION est refuse par la base.
        with self.assertRaises(IntegrityError):
            self._creation()

    def test_les_autres_transactions_ne_sont_pas_impactees(self):
        """
        LA condition posee : rien d'autre ne doit etre gene par la contrainte.
        / THE requirement: nothing else may be affected.
        """
        # 1. Sans checkout : autant de transactions qu'on veut, meme action.
        #    C'est le cas des 159 128 ventes, adhesions, fusions, corrections.
        asset_local = Asset.objects.create(
            name="Libre", currency_code="LIB",
            category=Asset.TOKEN_LOCAL_FIAT, wallet_origin=self.place.wallet)
        Token.objects.get_or_create(wallet=self.place.wallet, asset=asset_local)
        premiere = Transaction.objects.create(
            ip="127.0.0.1", checkout_stripe=None,
            sender=self.place.wallet, receiver=self.place.wallet,
            asset=asset_local, amount=500, action=Transaction.CREATION)
        seconde = Transaction.objects.create(
            ip="127.0.0.1", checkout_stripe=None,
            sender=self.place.wallet, receiver=self.place.wallet,
            asset=asset_local, amount=700, action=Transaction.CREATION)
        self.assertNotEqual(premiere.uuid, seconde.uuid)
        self.assertTrue(seconde.verify_hash())

        # 2. Avec checkout mais hors perimetre : REFUND reste libre.
        #    Un remboursement partiel puis un autre restent possibles.
        self._creation()
        for montant in (100, 200):
            remboursement = Transaction.objects.create(
                ip="127.0.0.1", checkout_stripe=self.checkout,
                sender=self.wallet_primaire, receiver=self.wallet_primaire,
                asset=self.asset_federe, amount=montant, action=Transaction.REFUND)
            self.assertIsNotNone(remboursement.uuid)
        self.assertEqual(
            Transaction.objects.filter(
                checkout_stripe=self.checkout, action=Transaction.REFUND).count(), 2,
            "Les REFUND doivent rester libres : la contrainte ne les couvre pas")
