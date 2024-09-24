import logging
import os
import stripe
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from fedow_core.models import Configuration, Asset, Federation, wallet_creator

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    def handle(self, *args, **options):
        config_exist = Configuration.objects.all().exists()
        if config_exist:
            self.stdout.write(
                self.style.SUCCESS(f'Configuration and master wallet already exists continue'),
                ending='\n')
            return ' '

        try:
            logger.info("Try stripe api key")
            if not os.environ.get('STRIPE_KEY_TEST') and not os.environ.get('STRIPE_KEY') and not settings.DEBUG:
                raise ValueError('STRIPE_KEY nor STRIPE_KEY_TEST')

            logger.info("Configuration does not exist -> go install")


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


            # TEST IF PRIMARY IS THE ONLY
            if Asset.objects.all().count() > 1:
                raise CommandError("There is more than one asset, it's not an install nor an empty database.")
            fed_asset = Asset.objects.first()
            if fed_asset.wallet_origin != config.primary_wallet:
                raise CommandError("Fedow origin is not primary wallet")
            # END TEST IF PRIMARY IS THE ONLY

            # Primary federation creation
            primary_federation = Federation.objects.create(name="Fedow")

            # CONFIGURE STRIPE
            # Test si la clé stripe est ok
            stripe_key = config.get_stripe_api()
            try:
                stripe.api_key = stripe_key
                acc = stripe.Account.list()
                price_stripe_id_refill_fed = fed_asset.get_id_price_stripe()

            except Exception as e:
                logger.error(e)
                self.stdout.write(self.style.ERROR(f'Stripe key not valid'),
                                  ending='\n')
                self.stdout.write(self.style.ERROR(f'You can use Fedow without Stripe, but no federation nor online refill can be possible.'),
                          ending='\n')

            self.stdout.write(
                self.style.SUCCESS(f'Configuration, primary asset, wallet and token created : {instance_name}'),
                ending='\n')

        except Exception as e:
            logger.error(e)
            raise e
