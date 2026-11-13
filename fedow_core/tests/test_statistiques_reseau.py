"""
Route des statistiques du reseau, lue par l'observatoire de Lespass.
/ Network statistics route, read by the Lespass observatory.

LOCALISATION : fedow_core/tests/test_statistiques_reseau.py

CE QUE CES TESTS PROTEGENT
1. Seule la cle « root » de la billetterie lit ces chiffres de tout le reseau.
2. La reponse a la forme attendue par Lespass.
3. Le calcul est garde en cache : un appel repete ne relit pas la base, fragile.
4. Les ventes par lieu et par mois : NFC (SAL) et QR code (QRS) comptees, le reste non.
/ Root key only; expected shape; cached; sales per place and per month.
"""

from unittest import mock
from uuid import uuid4

from django.core.cache import cache
from django.utils import timezone
from rest_framework import status

from fedow_core.models import Asset, CreatePlaceAPIKey, OrganizationAPIKey, Transaction, Wallet
from fedow_core.tests.tests import FedowTestCase
from fedow_core.views import StatistiquesReseauAPI

ADRESSE = "/statistiques_reseau/"


class StatistiquesReseauTest(FedowTestCase):

    def setUp(self):
        super().setUp()
        cache.delete(StatistiquesReseauAPI.CLE_DU_CACHE)
        _cle_en_base, self.cle_root = CreatePlaceAPIKey.objects.create_key(name="root_de_test")

    def test_sans_cle_la_route_refuse(self):
        reponse = self.client.get(ADRESSE)
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)

    def test_une_cle_inconnue_est_refusee(self):
        reponse = self.client.get(ADRESSE, headers={"Authorization": "Api-Key cle.inconnue"})
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)

    def test_une_cle_de_lieu_est_refusee(self):
        # Une cle de lieu ne voit que son lieu : les chiffres du reseau lui sont fermes.
        # / A place key only sees its place: network figures are closed to it.
        _cle_en_base, cle_du_lieu = OrganizationAPIKey.objects.create_key(
            name="lieu_de_test", place=self.place, user=self.admin,
        )
        reponse = self.client.get(ADRESSE, headers={"Authorization": f"Api-Key {cle_du_lieu}"})
        self.assertEqual(reponse.status_code, status.HTTP_403_FORBIDDEN)

    def test_la_cle_root_recoit_les_recharges_et_les_cartes(self):
        reponse = self.client.get(ADRESSE, headers={"Authorization": f"Api-Key {self.cle_root}"})

        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        donnees = reponse.json()
        self.assertIn("recharges_par_asset", donnees)
        self.assertEqual(set(donnees["cartes"].keys()), {"total", "liees_a_un_compte"})

    def test_un_deuxieme_appel_ne_recalcule_pas(self):
        with mock.patch.object(
            StatistiquesReseauAPI, "calculer_les_statistiques",
            return_value={"recharges_par_asset": [], "cartes": {"total": 0, "liees_a_un_compte": 0}},
        ) as calcul_espionne:
            for _numero in range(2):
                self.client.get(ADRESSE, headers={"Authorization": f"Api-Key {self.cle_root}"})

        self.assertEqual(calcul_espionne.call_count, 1)


class VentesParLieuTest(FedowTestCase):
    """
    L'agregat « ventes_par_lieu » : ce que l'observatoire lit pour voir la caisse V1.
    / The "ventes_par_lieu" aggregate: what the observatory reads to see the V1 till.
    """

    def setUp(self):
        super().setUp()
        cache.delete(StatistiquesReseauAPI.CLE_DU_CACHE)
        self.asset = Asset.objects.filter(category=Asset.STRIPE_FED_FIAT).first()
        self.transaction_precedente = Transaction.objects.first()
        self.premier_porte_monnaie = Wallet.objects.create(name="porte_monnaie_1")
        self.deuxieme_porte_monnaie = Wallet.objects.create(name="porte_monnaie_2")

    def creer_des_transactions(self, actions_et_porte_monnaie):
        # bulk_create saute Transaction.save() (hash chaine, controles de solde) :
        # ce test ne verifie que l'agregat en lecture, pas l'ecriture.
        # / bulk_create skips save(): this test only checks the read aggregate.
        maintenant = timezone.now()
        Transaction.objects.bulk_create([
            Transaction(
                hash=uuid4().hex, ip="127.0.0.1", sender=porte_monnaie,
                receiver=self.place.wallet, asset=self.asset, amount=100, action=action,
                datetime=maintenant, previous_transaction=self.transaction_precedente,
            )
            for action, porte_monnaie in actions_et_porte_monnaie
        ])

    def test_ventes_nfc_et_qr_comptees_avec_les_porte_monnaie_distincts(self):
        self.creer_des_transactions([
            (Transaction.SALE, self.premier_porte_monnaie),
            (Transaction.SALE, self.premier_porte_monnaie),
            (Transaction.QRCODE_SALE, self.deuxieme_porte_monnaie),
        ])

        ventes_par_lieu = StatistiquesReseauAPI.calculer_les_statistiques()["ventes_par_lieu"]

        mois_courant = timezone.now().strftime("%Y-%m")
        self.assertEqual(
            ventes_par_lieu[self.place.uuid.hex][mois_courant],
            {"transactions": 3, "portemonnaies": 2},
        )

    def test_une_recharge_n_est_pas_une_vente(self):
        self.creer_des_transactions([(Transaction.REFILL, self.premier_porte_monnaie)])

        ventes_par_lieu = StatistiquesReseauAPI.calculer_les_statistiques()["ventes_par_lieu"]

        self.assertNotIn(self.place.uuid.hex, ventes_par_lieu)

    def test_la_reponse_http_porte_les_ventes_par_lieu(self):
        # Les cles (uuid, mois) doivent etre du texte : sinon la reponse JSON plante.
        # / Keys must be text, or the JSON response crashes.
        self.creer_des_transactions([(Transaction.SALE, self.premier_porte_monnaie)])
        _cle_en_base, cle_root = CreatePlaceAPIKey.objects.create_key(name="root_de_test")

        reponse = self.client.get(ADRESSE, headers={"Authorization": f"Api-Key {cle_root}"})

        self.assertEqual(reponse.status_code, status.HTTP_200_OK)
        self.assertIn(self.place.uuid.hex, reponse.json()["ventes_par_lieu"])
