import os

from django.conf import settings
from django.core.management import call_command
from rest_framework_api_key.models import APIKey

from fedow_core.models import Configuration, Wallet, Asset, Federation
from django.core.management.base import BaseCommand, CommandError

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.exceptions import InvalidSignature
import logging

from fedow_core.utils import rsa_generator

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    def add_arguments(self, parser):
        # Positional arguments
        """
        parser.add_argument(
            "--test",
            action="store_true",
            help="Add test data",
        )
        """
        pass

    def handle(self, *args, **options):

        try:
            config = Configuration.get_solo()
            self.stdout.write(self.style.ERROR(f'Configuration and master wallet already exists : {config.name}'),
                              ending='\n')
        except Exception as e:
            # Génération d'une paire de clés RSA
            private_pem, public_pem = rsa_generator()

            instance_name = os.environ.get('DOMAIN', 'fedow.tibillet.localhost')
            primary_wallet = Wallet.objects.create(
                name="Primary Wallet",
                private_pem=private_pem,
                public_pem=public_pem,
            )

            config = Configuration(
                name=instance_name,
                domain=instance_name,
                primary_wallet=primary_wallet,
            )

            config.save()

            call_command("create_asset",
                         '--name', 'Fedow',
                         '--currency_code', 'FED',
                         '--origin', f'{primary_wallet.uuid}')

            fed_asset = Asset.objects.get(name='Fedow')
            assert fed_asset.origin == config.primary_wallet, "Fedow origin is not primary wallet"
            # import ipdb; ipdb.set_trace()
            price_stripe_id_refill_fed = os.environ.get('PRICE_STRIPE_ID_FED')
            if not price_stripe_id_refill_fed:
                price_stripe_id_refill_fed = fed_asset.get_id_price_stripe(force=True)
            fed_asset.id_price_stripe = price_stripe_id_refill_fed
            fed_asset.save()

            primary_federation = Federation.objects.create(name="Fedow Primary Federation")

            self.stdout.write(
                self.style.SUCCESS(f'Configuration, primary asset, wallet and token created : {instance_name}'),
                ending='\n')
