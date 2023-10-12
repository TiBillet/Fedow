from django.core.management.base import BaseCommand, CommandError
from rest_framework_api_key.models import APIKey

from fedow_core.models import Asset, Transaction, Configuration, Wallet, asset_creator

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
        parser.add_argument('--name', type=str)
        parser.add_argument('--currency_code', type=str)
        parser.add_argument('--origin', type=str)
        parser.add_argument('--category', type=str)

    def handle(self, *args, **options):
        asset_name = options['name']
        category = options['category']
        currency_code = options['currency_code'].upper()
        origin = Wallet.objects.get(uuid=options['origin'])

        asset = asset_creator(
            name=asset_name,
            currency_code=currency_code,
            category=category,
            origin=origin
        )

        self.stdout.write(self.style.SUCCESS(
            f"Asset succesfully created : NAME : {asset.name} - CURRENCY CODE : {asset.currency_code}"), ending='\n')
