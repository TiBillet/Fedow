from django.core.management.base import BaseCommand, CommandError
from rest_framework_api_key.models import APIKey

from fedow_core.models import Asset, Transaction, Configuration

"""
Pense bête :

self.stdout.write("Unterminated line", ending='\n')
self.stdout.write(self.style.SUCCESS('SUCCESS'), ending='\n')
self.stdout.write(self.style.ERROR('ERROR'), ending='\n')
self.stdout.write(self.style.WARNING('WARNING'), ending='\n')
raise CommandError('Poll does not exist')

def add_arguments(self, parser):
    # Positional arguments
    parser.add_argument('poll_ids', nargs='+', type=int)

    # Named (optional) arguments
    parser.add_argument(
        '--delete',
        action='store_true',
        help='Delete poll instead of closing it',
    )
"""


class Command(BaseCommand):
    help = 'Asset creation'

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('name', type=str)
        parser.add_argument('currency_code', type=str)

    def handle(self, *args, **options):
        asset_name = options['name']
        currency_code = options['currency_code'].upper()
        if len(currency_code) > 3:
            raise CommandError('Max 3 for currency code')

        self.stdout.write(f"", ending='\n')
        self.stdout.write(f"NAME : {asset_name} - CURRENCY CODE : {currency_code}", ending='\n')

        try:
            Asset.objects.get(name=asset_name)
            raise CommandError('Asset name already exist')
        except Asset.DoesNotExist:
            pass

        try:
            Asset.objects.get(currency_code=currency_code)
            raise CommandError('Asset currency_code already exist')
        except Asset.DoesNotExist:
            pass

        asset = Asset.objects.create(
            name=asset_name,
            currency_code=currency_code,
        )

        # Création du premier block
        config = Configuration.get_solo()
        primary_wallet = config.primary_wallet
        first_block = Transaction.objects.create(
            ip='0.0.0.0',
            checkout_stripe=None,
            sender=primary_wallet,
            receiver=primary_wallet,
            asset=asset,
            amount=int(0),
            action=Transaction.FIRST,
            card=None,
            primary_card_uuid=None,
        )

        self.stdout.write(self.style.SUCCESS(f"Asset succesfully created."), ending='\n')
