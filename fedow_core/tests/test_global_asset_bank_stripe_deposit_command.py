from datetime import timedelta
from io import StringIO
from uuid import uuid4

from django.core.management import call_command
from django.core.signing import Signer
from django.utils import timezone

from fedow_core.models import (
    Asset,
    CheckoutStripe,
    Configuration,
    Token,
    Transaction,
)
from fedow_core.tests.tests import FedowTestCase


class GlobalAssetBankStripeDepositCommandTest(FedowTestCase):
    """
    Teste la commande de remise en banque forcée:
    - Crée une chaîne valide (FIRST -> CREATION -> REFILL -> SALE)
    - Exécute la commande `global_asset_bank_stripe_deposit` pour forcer un DEPOSIT
    - Vérifie que la chaîne de hash reste cohérente
    - Crée ensuite une nouvelle transaction classique (SALE) pour vérifier que tout fonctionne encore
    """

    def test_cashless_chain_with_deposit_command(self):
        """
        Séquence demandée:
        - Recharge cashless (REFILL)
        - Vente cashless (SALE)
        - Bank deposit avec commande (DEPOSIT)
        - Recharge cashless (REFILL)
        - Vente cashless (SALE)
        """
        fed_asset = Asset.objects.get(category=Asset.STRIPE_FED_FIAT)
        config = Configuration.get_solo()
        primary_wallet = config.primary_wallet
        place_wallet = self.place.wallet

        # 0. Initialisation des tokens et cartes
        user_wallet, _, _ = self.create_wallet_via_api()
        user_token = Token.objects.get_or_create(wallet=user_wallet, asset=fed_asset)[0]
        place_token = Token.objects.get_or_create(wallet=place_wallet, asset=fed_asset)[0]
        primary_token = Token.objects.get_or_create(wallet=primary_wallet, asset=fed_asset)[0]

        # On recule la date du bloc FIRST pour avoir de la place
        first_tx = Transaction.objects.filter(asset=fed_asset, action=Transaction.FIRST).first()
        if first_tx:
            first_tx.datetime = timezone.now() - timedelta(minutes=10)
            # On court-circuite le save() pour éviter les checks de hash/datetime sur le FIRST
            Transaction.objects.filter(pk=first_tx.pk).update(datetime=first_tx.datetime)

        from fedow_core.models import Origin, Card
        gen1 = Origin.objects.get_or_create(place=self.place, generation=1)[0]
        user_card = Card.objects.create(
            complete_tag_id_uuid=str(uuid4()),
            first_tag_id=f"{str(uuid4()).split('-')[0]}",
            qrcode_uuid=str(uuid4()),
            number_printed=f"{str(uuid4()).split('-')[0]}",
            origin=gen1,
            user=user_wallet.user,
        )
        primary_card = Card.objects.create(
            complete_tag_id_uuid=str(uuid4()),
            first_tag_id=f"{str(uuid4()).split('-')[0]}",
            qrcode_uuid=str(uuid4()),
            number_printed=f"{str(uuid4()).split('-')[0]}",
            origin=gen1,
        )
        primary_card.primary_places.add(self.place)

        # Helper pour gérer le temps et s'assurer que datetime > previous.datetime
        def get_next_time():
            last_tx = Transaction.objects.filter(asset=fed_asset).order_by('datetime').last()
            if last_tx:
                return last_tx.datetime + timedelta(seconds=1)
            # On commence 1h dans le passé pour laisser de la place au "now" de la commande
            return timezone.now() - timedelta(hours=1)

        # 0 bis. CREATION pour alimenter le primaire
        creation_checkout = CheckoutStripe.objects.create(
            checkout_session_id_stripe='cs_init',
            asset=fed_asset,
            status=CheckoutStripe.PAID,
            user=user_wallet.user,
            metadata=Signer().sign('{}'),
        )
        Transaction.objects.create(
            sender=primary_wallet, receiver=primary_wallet, asset=fed_asset,
            amount=10000, action=Transaction.CREATION, ip='127.0.0.1',
            datetime=get_next_time(), checkout_stripe=creation_checkout
        )

        # 1. Recharge cashless (REFILL) : Primaire -> User
        refill1_checkout = CheckoutStripe.objects.create(
            checkout_session_id_stripe='cs_refill_1',
            asset=fed_asset, status=CheckoutStripe.PAID,
            user=user_wallet.user, metadata=Signer().sign('{}'),
        )
        tx_refill1 = Transaction.objects.create(
            sender=primary_wallet, receiver=user_wallet, asset=fed_asset,
            amount=5000, action=Transaction.REFILL, ip='127.0.0.1',
            datetime=get_next_time(), checkout_stripe=refill1_checkout
        )
        self.assertTrue(tx_refill1.verify_hash())

        # 2. Vente cashless (SALE) : User -> Place
        tx_sale1 = Transaction.objects.create(
            sender=user_wallet, receiver=place_wallet, asset=fed_asset,
            amount=2000, action=Transaction.SALE, ip='127.0.0.1',
            datetime=get_next_time(), card=user_card, primary_card=primary_card
        )
        self.assertTrue(tx_sale1.verify_hash())
        place_token.refresh_from_db()
        self.assertEqual(place_token.value, 2000)

        # 3. Bank deposit avec commande (DEPOSIT) : Place -> Primaire
        out = StringIO()
        call_command(
            'global_asset_bank_stripe_deposit',
            '--place', str(self.place.uuid),
            '--amount', '1500',
            '--comment', 'Dépôt intermédiaire',
            stdout=out
        )
        last_tx = Transaction.objects.filter(asset=fed_asset).order_by('datetime').last()
        self.assertEqual(last_tx.action, Transaction.DEPOSIT)
        self.assertTrue(last_tx.verify_hash())
        place_token.refresh_from_db()
        self.assertEqual(place_token.value, 500) # 2000 - 1500

        # 4. Création monétaire (CREATION) pour autoriser une nouvelle recharge
        creation2_checkout = CheckoutStripe.objects.create(
            checkout_session_id_stripe='cs_creation_2',
            asset=fed_asset,
            status=CheckoutStripe.PAID,
            user=user_wallet.user,
            metadata=Signer().sign('{}'),
        )
        Transaction.objects.create(
            sender=primary_wallet, receiver=primary_wallet, asset=fed_asset,
            amount=3000, action=Transaction.CREATION, ip='127.0.0.1',
            datetime=get_next_time(), checkout_stripe=creation2_checkout
        )

        # 5. Recharge cashless (REFILL) : Primaire -> User
        refill2_checkout = CheckoutStripe.objects.create(
            checkout_session_id_stripe='cs_refill_2',
            asset=fed_asset, status=CheckoutStripe.PAID,
            user=user_wallet.user, metadata=Signer().sign('{}'),
        )
        tx_refill2 = Transaction.objects.create(
            sender=primary_wallet, receiver=user_wallet, asset=fed_asset,
            amount=1000, action=Transaction.REFILL, ip='127.0.0.1',
            datetime=get_next_time(), checkout_stripe=refill2_checkout
        )
        self.assertTrue(tx_refill2.verify_hash())

        # 5. Vente cashless (SALE) : User -> Place
        tx_sale2 = Transaction.objects.create(
            sender=user_wallet, receiver=place_wallet, asset=fed_asset,
            amount=800, action=Transaction.SALE, ip='127.0.0.1',
            datetime=get_next_time(), card=user_card, primary_card=primary_card
        )
        self.assertTrue(tx_sale2.verify_hash())
        place_token.refresh_from_db()
        self.assertEqual(place_token.value, 1300) # 500 + 800

        # Vérification finale de toute la chaîne
        all_txs = Transaction.objects.filter(asset=fed_asset).order_by('datetime')
        for tx in all_txs:
            self.assertTrue(tx.verify_hash(), f"Hash invalide pour {tx.action} à {tx.datetime}")
