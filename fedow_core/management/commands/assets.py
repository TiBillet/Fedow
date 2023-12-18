from django.core.management.base import BaseCommand, CommandError
from rest_framework_api_key.models import APIKey

from fedow_core.models import Federation, Asset, Place, Wallet, asset_creator


class Command(BaseCommand):
    help = 'Federation management. add_asset, remove_asset, add_place, remove_place'

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('--create', action='store_true',
                            help='Create an asset. Need --name --currency_code --category. Need  --place_origin OR --wallet_origin')

        parser.add_argument('--name',
                            help='Asset name')
        parser.add_argument('--place_origin',
                            help='Place origin uuid')
        parser.add_argument('--wallet_origin',
                            help='Place origin uuid')
        parser.add_argument('--currency_code',
                            help='char max 3')
        parser.add_argument('--category',
                            help='Category of the asset (TLF for token local fiat currency, TNF for token local non fiat currency, SUB for subscrition)')

        parser.add_argument('--list',
                            action='store_true',
                            help='List all assets on the database')

    def handle(self, *args, **options):
        print(options)
        if options.get('create'):
            if not options.get('name'):
                raise CommandError('Please provide a federation name')
            if not options.get('currency_code'):
                raise CommandError('Please provide a currency code')
            if not options.get('category'):
                raise CommandError('Please provide a category')
            if not options.get('place_origin') and not options.get('wallet_origin'):
                raise CommandError('Please provide a place origin uuid or a wallet origin uuid')

            try:
                asset_name = options['name']
                category = options['category']
                if category not in [Asset.TOKEN_LOCAL_FIAT, Asset.TOKEN_LOCAL_NOT_FIAT, Asset.SUBSCRIPTION]:
                    raise CommandError('Please provide a valid category')
                currency_code = options['currency_code'].upper()

                origin_wallet = None
                if options.get('wallet_origin'):
                    origin_wallet = Wallet.objects.get(uuid=options['wallet_origin'])
                if options.get('place_origin'):
                    place = Place.objects.get(uuid=options['place_origin'])
                    origin_wallet = place.wallet

                asset = asset_creator(
                    name=asset_name,
                    currency_code=currency_code,
                    category=category,
                    origin=origin_wallet
                )

                self.stdout.write(self.style.SUCCESS(f"Asset succesfully created\nNAME : {asset.name} - CURRENCY CODE : {asset.currency_code}\nUUID : {asset.uuid}"),ending='\n')
            except Exception as e:
                raise CommandError(e)

        if options.get('list'):
            fed_asset = Asset.objects.get(category=Asset.STRIPE_FED_FIAT)
            self.stdout.write(self.style.HTTP_NOT_MODIFIED(
                f"FIAT PRIMARY FEDERATED ASSET"), ending='\n')
            self.stdout.write(self.style.SQL_KEYWORD(
                f"    Asset : {fed_asset.name} - {fed_asset.currency_code} - {fed_asset.uuid}"), ending='\n')

            for place in Place.objects.all():
                if place.wallet.assets_created.count() > 0:
                    self.stdout.write(self.style.HTTP_NOT_MODIFIED(
                        f"Place origin : {place} - {place.uuid}"), ending='\n')
                    wallet_origin = place.wallet
                    for asset in wallet_origin.assets_created.all():
                        self.stdout.write(self.style.SQL_KEYWORD(
                            f"    Asset : {asset.name} - {asset.currency_code} - {asset.uuid}"), ending='\n')


