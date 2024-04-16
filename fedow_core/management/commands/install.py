import logging
import os
import stripe
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from fedow_core.models import Configuration, Asset, Federation, wallet_creator

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
            self.stdout.write(self.style.SUCCESS(f'Configuration and master wallet already exists : {config.name}, continue'),
                              ending='\n')

        except Configuration.DoesNotExist as e:
            logger.info("Configuration does not exist -> go install")
            # Test si la clé stripe est ok
            stripe_key = settings.STRIPE_KEY_TEST if settings.STRIPE_TEST else settings.STRIPE_KEY
            stripe.api_key = stripe_key
            try:
                acc = stripe.Account.list()
            except Exception as e:
                logger.error(e)
                self.stdout.write(self.style.ERROR(f'Stripe key not valid'),
                                  ending='\n')
                raise e

            instance_name = os.environ['DOMAIN']

            primary_wallet = wallet_creator(name="Primary Wallet", generate_rsa=True)

            config = Configuration(
                name=instance_name,
                domain=instance_name,
                primary_wallet=primary_wallet,
            )

            config.save()

            call_command("assets",
                         '--create',
                         '--name', 'Primary Asset',
                         '--currency_code', 'FED',
                         '--wallet_origin', f'{primary_wallet.uuid}',
                         '--category', 'FED')

            if Asset.objects.all().count() > 1:
                raise CommandError("There is more than one asset, it's not an install nor an empty database.")

            fed_asset = Asset.objects.first()
            if fed_asset.wallet_origin != config.primary_wallet:
                raise CommandError("Fedow origin is not primary wallet")

            price_stripe_id_refill_fed = os.environ.get('PRICE_STRIPE_ID_FED')
            if not price_stripe_id_refill_fed:
                price_stripe_id_refill_fed = fed_asset.get_id_price_stripe(force=True)
            fed_asset.id_price_stripe = price_stripe_id_refill_fed
            fed_asset.save()

            primary_federation = Federation.objects.create(name="Fedow")

            self.stdout.write(
                self.style.SUCCESS(f'Configuration, primary asset, wallet and token created : {instance_name}'),
                ending='\n')

        except Exception as e:
            logger.error(e)
            raise e