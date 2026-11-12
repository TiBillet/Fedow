"""
Route des statistiques du reseau, lue par l'observatoire de Lespass.
/ Network statistics route, read by the Lespass observatory.

LOCALISATION : fedow_core/tests/test_statistiques_reseau.py

CE QUE CES TESTS PROTEGENT
1. Seule la cle « root » de la billetterie lit ces chiffres de tout le reseau.
2. La reponse a la forme attendue par Lespass.
3. Le calcul est garde en cache : un appel repete ne relit pas la base, fragile.
/ Root key only; expected shape; cached so repeated calls do not hit the database.
"""

from unittest import mock

from django.core.cache import cache
from rest_framework import status

from fedow_core.models import CreatePlaceAPIKey, OrganizationAPIKey
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
