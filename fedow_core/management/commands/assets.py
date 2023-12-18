from django.core.management.base import BaseCommand, CommandError
from rest_framework_api_key.models import APIKey

from fedow_core.models import Asset, Transaction, Configuration, Wallet, asset_creator

class Command(BaseCommand):
    help = 'Asset Management'

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('--list',
                            action='store_true',
                            help='List all assets on the database')

    def handle(self, *args, **options):
        if options.get('list'):
            for asset in Asset.objects.all():
                self.stdout.write(self.style.SUCCESS(
                    f"Asset : {asset.name} - {asset.currency_code} - {asset.uuid}"), ending='\n')

        else :
            # Print help
            self.stdout.write(self.style.WARNING(
                f"Usage : python manage.py assets --list"), ending='\n')