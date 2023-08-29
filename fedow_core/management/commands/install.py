import os

from django.conf import settings
from django.core.management import call_command
from rest_framework_api_key.models import APIKey

from fedow_core.models import Configuration, Wallet, Asset
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
        parser.add_argument(
            "--test",
            action="store_true",
            help="Add test data",
        )

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
                name="Primary",
                private_pem=private_pem,
                public_pem=public_pem,
            )

            config = Configuration(
                name=instance_name,
                domain=instance_name,
                primary_wallet=primary_wallet,
            )

            config.save()

            if options['test']:
                try:
                    call_command("create_asset", 'TiBillet', 'TBI')
                    fed = Asset.objects.get(name='TiBillet')
                    fed.federated_primary = True
                    fed.id_price_stripe = os.environ.get('PRICE_STRIPE_ID_FED')
                    fed.save()
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Asset TiBIllet already exist ? {e}'))
            self.stdout.write(self.style.SUCCESS(f'Configuration created : {instance_name}'), ending='\n')
