"""
Tests de sécurité des endpoints Fedow : accès sans signature

Ce fichier vérifie que les endpoints protégés par signature ou clé API refusent les accès non signés ou mal signés.
"""
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from fedow_core.models import Card, Wallet
from fedow_core.tests.tests import FedowTestCase
import json

class EndpointSecurityTest(FedowTestCase):
    """
    Tests d'accès non authentifié ou sans signature sur les endpoints sensibles.
    """
    def ensure_card_without_user(self):
        """
        S'assure qu'il existe au moins une carte sans user en base et la retourne.
        """
        card = Card.objects.filter(user__isnull=True).first()
        if card is not None:
            return card
        # Création d'une carte vierge
        from fedow_core.models import Origin
        from uuid import uuid4
        gen1 = Origin.objects.create(place=self.place, generation=1)
        card = Card.objects.create(
            complete_tag_id_uuid=str(uuid4()),
            first_tag_id="test",
            qrcode_uuid=str(uuid4()),
            number_printed="test",
            origin=gen1,
        )
        return card

    def test_wallet_card_link_requires_signature(self):
        """
        Vérifie que l'association carte/wallet via l'API échoue sans header Signature.
        """
        # Création d'un wallet utilisateur
        wallet, private_pem, public_pem = self.create_wallet_via_api()
        card = self.ensure_card_without_user()
        self.assertIsNotNone(card)
        link_data = {
            'wallet': str(wallet.uuid),
            'card_qrcode_uuid': str(card.qrcode_uuid),
        }
        # Appel API SANS header Signature
        response = self.client.post(
            '/wallet/linkwallet_cardqrcode/',
            json.dumps(link_data),
            content_type='application/json',
            headers={
                'Authorization': f'Api-Key {self.temp_key_place}',
                'Wallet': str(wallet.uuid),
                'Date': self.now().isoformat(),
            }
        )
        self.assertIn(response.status_code, [401, 403, 400])

    def test_wallet_card_link_requires_wallet_header(self):
        """
        Vérifie que l'association carte/wallet via l'API échoue sans header Wallet.
        """
        wallet, private_pem, public_pem = self.create_wallet_via_api()
        card = self.ensure_card_without_user()
        self.assertIsNotNone(card)
        link_data = {
            'wallet': str(wallet.uuid),
            'card_qrcode_uuid': str(card.qrcode_uuid),
        }
        # Appel API SANS header Wallet
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
                'Date': self.now().isoformat(),
                'Signature': signature,
            }
        )
        self.assertIn(response.status_code, [401, 403, 400])

    def test_wallet_card_link_requires_date_header(self):
        """
        Vérifie que l'association carte/wallet via l'API échoue sans header Date.
        """
        wallet, private_pem, public_pem = self.create_wallet_via_api()
        card = self.ensure_card_without_user()
        self.assertIsNotNone(card)
        link_data = {
            'wallet': str(wallet.uuid),
            'card_qrcode_uuid': str(card.qrcode_uuid),
        }
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
                'Signature': signature,
            }
        )
        print(response)
        # On vérifie que le code d'erreur est bien une erreur d'accès (401/403/400)
        self.assertIn(response.status_code, [401, 403, 400])
        # On vérifie aussi que le message d'erreur parle du header Date ou d'une permission
        content = response.content.decode().lower()
        self.assertTrue(
            ("date" in content or "permission" in content or "signature" in content or "header" in content),
            f"Le message d'erreur ne parle pas du header manquant ou d'une permission : {content}"
        )

    def now(self):
        from django.utils.timezone import now
        return now()
