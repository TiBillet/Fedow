"""
Une carte primaire sur plusieurs lieux : le VOID d'un lieu ne touche que ce lieu.
/ A primary card on several places: a VOID from one place only affects that place.

LOCALISATION : fedow_core/tests/test_void_primary_card_multi_place.py

Card.primary_places est un ManyToMany : une meme carte physique peut ouvrir la
caisse de plusieurs lieux a la fois. Chaque lieu ne gere que SA propre ligne.

Le VOID (dissociation carte / wallet user) est declenche par UN lieu, avec sa
propre cle d'API. Il n'a donc aucune autorite sur le lien primaire des autres
lieux de la federation.
"""

from uuid import uuid4

from rest_framework import status

from fedow_core.models import Card, Place, Transaction
from fedow_core.tests.tests import FedowTestCase


class VoidPrimaryCardMultiPlaceTest(FedowTestCase):

    def setUp(self):
        super().setUp()

        # Un deuxieme lieu dans la federation, avec son propre wallet.
        # / A second place in the federation, with its own wallet.
        from fedow_core.utils import rsa_generator
        from fedow_core.validators import PlaceValidator

        second_place_private_pem, second_place_public_pem = rsa_generator()
        validator = PlaceValidator(data={
            'place_domain': 'secondplace.tibillet.localhost',
            'place_name': 'SecondPlace',
            'admin_email': 'admin_second_place@admin.admin',
            'admin_pub_pem': second_place_public_pem,
        })
        self.assertTrue(validator.is_valid())
        validator.create_place()
        self.second_place: Place = Place.objects.get(name='SecondPlace')

        # La carte primaire qui autorise le lieu 1 a lancer le VOID.
        # / The primary card allowing place 1 to trigger the VOID.
        self.carte_primaire_du_lieu = self._cree_carte_via_api(is_primary=True)
        self.carte_primaire_du_lieu.primary_places.add(self.place)

        # La carte visee par le VOID. Elle est primaire sur les DEUX lieux.
        # / The card targeted by the VOID. It is primary on BOTH places.
        self.carte_partagee = self._cree_carte_via_api(is_primary=True)
        self.carte_partagee.primary_places.add(self.place)
        self.carte_partagee.primary_places.add(self.second_place)

    def _cree_carte_via_api(self, is_primary: bool) -> Card:
        """
        Cree une carte en passant par l'API, comme le fait un serveur LaBoutik.
        / Creates a card through the API, the way a LaBoutik server does.
        """
        complete_tag_id_uuid = str(uuid4())
        qrcode_uuid = str(uuid4())
        first_tag_id = complete_tag_id_uuid.split('-')[0]

        response = self._post_from_simulated_cashless('card', [{
            "first_tag_id": first_tag_id,
            "complete_tag_id_uuid": complete_tag_id_uuid,
            "qrcode_uuid": qrcode_uuid,
            "number_printed": qrcode_uuid.split('-')[0],
            "generation": 1,
            "is_primary": is_primary,
        }])
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        return Card.objects.get(first_tag_id=first_tag_id)

    def test_void_ne_retire_la_carte_primaire_que_du_lieu_demandeur(self):
        """
        Le lieu 1 fait un VOID : le lieu 2 garde sa carte primaire.
        / Place 1 runs a VOID: place 2 keeps its primary card.
        """
        response = self._post_from_simulated_cashless('card/refund', {
            'primary_card_fisrtTagId': self.carte_primaire_du_lieu.first_tag_id,
            'user_card_firstTagId': self.carte_partagee.first_tag_id,
            'action': Transaction.VOID,
        })
        self.assertEqual(response.status_code, status.HTTP_205_RESET_CONTENT)

        lieux_primaires = self.carte_partagee.primary_places.all()

        # Le lieu qui a demande le VOID perd bien son lien primaire.
        # / The place that asked for the VOID does lose its primary link.
        self.assertNotIn(self.place, lieux_primaires)

        # Le lieu 2 n'a rien demande : son lien primaire doit survivre.
        # / Place 2 asked for nothing: its primary link must survive.
        self.assertIn(self.second_place, lieux_primaires)
