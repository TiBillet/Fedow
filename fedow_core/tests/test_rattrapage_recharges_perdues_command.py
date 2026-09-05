"""
Commande de rattrapage des recharges Stripe perdues.
/ Repair command for lost Stripe refills.

LOCALISATION : fedow_core/tests/test_rattrapage_recharges_perdues_command.py

POURQUOI CE FICHIER :
La commande rattrapage_recharges_perdues ecrit de l'argent reel en production.
Elle doit donc etre prouvee sur les trois lots de l'incident des 28-29/08/2026 :
  A - rendre au porteur (il choisira de se faire rembourser ou non),
  B - tracer un remboursement Stripe deja fait a la main, sans rappeler Stripe,
  C - reverser au lieu qui a avance la valeur au porteur.
Et surtout : ne rien ecrire en dry-run, et ne rien refaire si on la relance.
"""
from io import StringIO
from unittest.mock import patch
from uuid import uuid4

from django.core.management import call_command
from django.core.management.base import CommandError

from fedow_core.models import (
    Asset, Card, CheckoutStripe, Configuration, Origin, Token, Transaction,
    wallet_creator,
)
from fedow_core.tests.tests import FedowTestCase


class RattrapageRechargesPerduesTest(FedowTestCase):

    def setUp(self):
        super().setUp()
        self.configuration = Configuration.get_solo()
        self.wallet_primaire = self.configuration.primary_wallet
        self.asset_federe = Asset.objects.get(
            wallet_origin=self.wallet_primaire, category=Asset.STRIPE_FED_FIAT)
        self.wallet_porteur, _, _ = self.create_wallet_via_api(email='porteur@test.test')
        Token.objects.get_or_create(wallet=self.wallet_porteur, asset=self.asset_federe)
        self.compteur_de_checkout = 0

    def _fabriquer_creation_orpheline(self, montant, statut=CheckoutStripe.ERROR,
                                      carte=None, avec_user=True):
        """
        Reproduit l'etat exact d'apres incident : la monnaie a ete creee sur le
        wallet primaire, mais aucun REFILL ne l'a transferee.
        / Reproduces the post-incident state: minted, never moved.
        """
        self.compteur_de_checkout += 1
        checkout = CheckoutStripe.objects.create(
            checkout_session_id_stripe=f"cs_test_orphelin_{self.compteur_de_checkout}",
            asset=self.asset_federe,
            status=statut,
            metadata="",
            user=self.wallet_porteur.user if avec_user else None,
        )
        creation = Transaction.objects.create(
            ip="127.0.0.1",
            checkout_stripe=checkout,
            sender=self.wallet_primaire,
            receiver=self.wallet_primaire,
            asset=self.asset_federe,
            amount=montant,
            action=Transaction.CREATION,
            card=carte,
        )
        return checkout, creation

    def _fabriquer_carte_anonyme(self):
        # Une carte de festival sans porteur identifie : elle n'a qu'un wallet
        # ephemere, joignable uniquement avec la carte physique en main.
        # / A festival card with no account: only an ephemeral wallet.
        origine, _ = Origin.objects.get_or_create(place=self.place, generation=1)
        return Card.objects.create(
            first_tag_id=f"TAG{self.compteur_de_checkout:05d}",
            complete_tag_id_uuid=uuid4(),
            qrcode_uuid=uuid4(),
            number_printed=f"CARTE{self.compteur_de_checkout:03d}",
            origin=origine,
            wallet_ephemere=wallet_creator(),
        )

    def _solde(self, wallet):
        token = Token.objects.filter(wallet=wallet, asset=self.asset_federe).first()
        return token.value if token else 0

    # ------------------------------------------------------------------

    def test_dry_run_n_ecrit_rien(self):
        self._fabriquer_creation_orpheline(1000)
        self._fabriquer_creation_orpheline(2500)
        solde_primaire_avant = self._solde(self.wallet_primaire)

        sortie = StringIO()
        call_command('rattrapage_recharges_perdues', '--lot', 'A', stdout=sortie)

        self.assertIn("DRY-RUN", sortie.getvalue())
        self.assertIn("35.00 EUR", sortie.getvalue())
        self.assertEqual(Transaction.objects.filter(action=Transaction.REFILL).count(), 0)
        self.assertEqual(self._solde(self.wallet_primaire), solde_primaire_avant)
        self.assertEqual(self._solde(self.wallet_porteur), 0)

    def test_lot_a_cree_le_refill_et_repasse_le_checkout_en_paid(self):
        checkout, _creation = self._fabriquer_creation_orpheline(2500)
        solde_primaire_avant = self._solde(self.wallet_primaire)

        call_command('rattrapage_recharges_perdues', '--lot', 'A', '--apply',
                     '--total-attendu', '2500', stdout=StringIO())

        refill = Transaction.objects.get(action=Transaction.REFILL, checkout_stripe=checkout)
        self.assertEqual(refill.amount, 2500)
        self.assertEqual(refill.receiver, self.wallet_porteur)
        self.assertTrue(refill.verify_hash())
        self.assertEqual(self._solde(self.wallet_porteur), 2500)
        self.assertEqual(self._solde(self.wallet_primaire), solde_primaire_avant - 2500)
        checkout.refresh_from_db()
        # Sans PAID, refund_fed_by_signature ignorerait le checkout (402).
        self.assertEqual(checkout.status, CheckoutStripe.PAID)

    def test_est_idempotente(self):
        self._fabriquer_creation_orpheline(1000)
        call_command('rattrapage_recharges_perdues', '--lot', 'A', '--apply',
                     '--total-attendu', '1000', stdout=StringIO())
        solde_apres_premier_passage = self._solde(self.wallet_porteur)

        sortie = StringIO()
        call_command('rattrapage_recharges_perdues', '--lot', 'A', '--apply',
                     '--total-attendu', '0', stdout=sortie)

        self.assertIn("Aucune recharge orpheline", sortie.getvalue())
        self.assertEqual(Transaction.objects.filter(action=Transaction.REFILL).count(), 1)
        self.assertEqual(self._solde(self.wallet_porteur), solde_apres_premier_passage)

    @patch('fedow_core.models.stripe.Refund.create')
    def test_lot_b_trace_le_remboursement_sans_rappeler_stripe(self, refund_stripe):
        checkout, _creation = self._fabriquer_creation_orpheline(2000)
        solde_primaire_avant = self._solde(self.wallet_primaire)

        call_command('rattrapage_recharges_perdues', '--lot', 'B', '--apply', '--total-attendu', '2000',
                     '--checkout', checkout.checkout_session_id_stripe,
                     '--commentaire', 'rembourse sur Stripe re_test_123',
                     stdout=StringIO())

        # L'argent est sorti du systeme : le porteur revient a zero et le primaire
        # est debite, sans que le primaire soit recredite par le REFUND.
        self.assertEqual(self._solde(self.wallet_porteur), 0)
        self.assertEqual(self._solde(self.wallet_primaire), solde_primaire_avant - 2000)
        remboursement = Transaction.objects.get(action=Transaction.REFUND, checkout_stripe=checkout)
        self.assertEqual(remboursement.receiver, self.wallet_primaire)
        self.assertIn('re_test_123', remboursement.comment)
        self.assertTrue(remboursement.verify_hash())
        checkout.refresh_from_db()
        self.assertEqual(checkout.status, CheckoutStripe.REFUND)
        # La garantie centrale du lot B : on ecrit la trace, on ne rembourse pas.
        refund_stripe.assert_not_called()

    def test_lot_c_reverse_au_lieu_sans_creer_de_vente(self):
        checkout, _creation = self._fabriquer_creation_orpheline(4500)
        solde_primaire_avant = self._solde(self.wallet_primaire)
        ventes_avant = Transaction.objects.filter(action=Transaction.SALE).count()

        call_command('rattrapage_recharges_perdues', '--lot', 'C', '--apply', '--total-attendu', '4500',
                     '--checkout', checkout.checkout_session_id_stripe,
                     '--place', self.place.name, stdout=StringIO())

        self.assertEqual(self._solde(self.wallet_porteur), 0)
        self.assertEqual(self._solde(self.wallet_primaire), solde_primaire_avant - 4500)
        self.assertEqual(self._solde(self.place.wallet), 4500)
        # Le lieu est credite sans qu'aucune vente fictive ne soit enregistree.
        self.assertEqual(Transaction.objects.filter(action=Transaction.SALE).count(), ventes_avant)

    def test_refuse_si_le_total_attendu_differe(self):
        self._fabriquer_creation_orpheline(1000)

        with self.assertRaises(CommandError) as contexte:
            call_command('rattrapage_recharges_perdues', '--lot', 'A', '--apply',
                         '--total-attendu', '9999', stdout=StringIO())

        self.assertIn("total-attendu", str(contexte.exception))
        self.assertEqual(Transaction.objects.filter(action=Transaction.REFILL).count(), 0)

    def test_refuse_le_lot_c_sans_place(self):
        checkout, _creation = self._fabriquer_creation_orpheline(1000)

        with self.assertRaises(CommandError):
            call_command('rattrapage_recharges_perdues', '--lot', 'C', '--apply',
                         '--total-attendu', '1000',
                         '--checkout', checkout.checkout_session_id_stripe, stdout=StringIO())

        self.assertEqual(Transaction.objects.filter(action=Transaction.REFILL).count(), 0)

    def test_la_chaine_reste_valide_apres_rattrapage(self):
        self._fabriquer_creation_orpheline(1000)
        self._fabriquer_creation_orpheline(2500)

        call_command('rattrapage_recharges_perdues', '--lot', 'A', '--apply',
                     '--total-attendu', '3500', stdout=StringIO())

        for transaction in Transaction.objects.filter(asset=self.asset_federe):
            self.assertTrue(transaction.verify_hash(),
                            f"hash invalide sur {transaction.action} {transaction.uuid}")

    # ------------------------------------------------------------------
    # Resolution du destinataire : c'est elle qui decide QUI recoit l'argent.
    # / Recipient resolution: it decides WHO gets real money.
    # ------------------------------------------------------------------

    def test_credite_le_compte_plutot_que_la_carte_anonyme(self):
        """
        Une carte anonyme n'est joignable qu'avec la carte physique en main.
        Si le paiement porte un compte, c'est le compte qui doit etre credite,
        sinon l'argent devient inaccessible des que l'evenement est fini.
        / An account always wins over an anonymous ephemeral wallet.
        """
        carte = self._fabriquer_carte_anonyme()
        checkout, _creation = self._fabriquer_creation_orpheline(900, carte=carte)

        sortie = StringIO()
        call_command('rattrapage_recharges_perdues', '--lot', 'A', '--apply',
                     '--total-attendu', '900', stdout=sortie)

        self.assertIn("compte du checkout", sortie.getvalue())
        self.assertEqual(self._solde(self.wallet_porteur), 900)
        self.assertEqual(self._solde(carte.wallet_ephemere), 0,
                         "Le wallet ephemere ne doit pas avoir ete credite")

    def test_credite_la_carte_anonyme_quand_il_n_y_a_aucun_compte(self):
        """
        A defaut de compte, on credite la carte : le porteur la presentera.
        / With no account at all, credit the card.
        """
        carte = self._fabriquer_carte_anonyme()
        checkout, _creation = self._fabriquer_creation_orpheline(
            1500, carte=carte, avec_user=False)

        sortie = StringIO()
        call_command('rattrapage_recharges_perdues', '--lot', 'A', '--apply',
                     '--total-attendu', '1500', stdout=sortie)

        self.assertIn("anonyme", sortie.getvalue())
        self.assertEqual(self._solde(carte.wallet_ephemere), 1500)

    def test_ignore_un_checkout_deja_rembourse(self):
        """
        Un checkout en REFUND a deja rendu son argent : le crediter serait une
        seconde sortie. La commande doit l'ecarter et le dire.
        / A checkout already refunded must never be credited again.
        """
        self._fabriquer_creation_orpheline(2000, statut=CheckoutStripe.REFUND)

        sortie = StringIO()
        call_command('rattrapage_recharges_perdues', '--lot', 'A', stdout=sortie)

        self.assertIn("deja en REFUND", sortie.getvalue())
        self.assertIn("Aucune recharge orpheline", sortie.getvalue())
        self.assertEqual(Transaction.objects.filter(action=Transaction.REFILL).count(), 0)

    def test_refuse_apply_sans_total_attendu(self):
        """
        Le total attendu oblige a relire le dry-run avant d'ecrire de l'argent.
        / The expected total forces a human to read the dry-run first.
        """
        self._fabriquer_creation_orpheline(1000)

        with self.assertRaises(CommandError) as contexte:
            call_command('rattrapage_recharges_perdues', '--lot', 'A', '--apply',
                         stdout=StringIO())

        self.assertIn("total-attendu", str(contexte.exception))
        self.assertEqual(Transaction.objects.filter(action=Transaction.REFILL).count(), 0)

    def test_signale_un_checkout_demande_introuvable(self):
        """
        Une coquille dans un --checkout ne doit pas passer pour un "rien a faire".
        / A typo in --checkout must not look like a no-op.
        """
        self._fabriquer_creation_orpheline(1000)

        with self.assertRaises(CommandError) as contexte:
            call_command('rattrapage_recharges_perdues', '--lot', 'B', '--apply',
                         '--total-attendu', '1000',
                         '--checkout', 'cs_test_qui_nexiste_pas', stdout=StringIO())

        self.assertIn("introuvable", str(contexte.exception))
