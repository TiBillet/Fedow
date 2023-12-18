from django.core.management.base import BaseCommand, CommandError
from rest_framework_api_key.models import APIKey

from fedow_core.models import Federation, Asset, Place
from django.core.cache import cache
cache.clear()

class Command(BaseCommand):
    help = 'Federation management. add_asset, remove_asset, add_place, remove_place'

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('--create', action='store_true',
                            help='Create a federation. Need --name')
        parser.add_argument('--add_asset', action='store_true',
                            help='Add an asset on federation. Need --fed_uuid adn --asset_uuid')
        parser.add_argument('--remove_asset', action='store_true',
                            help='Remove an asset on federation. Need --fed_uuid adn --asset_uuid')
        parser.add_argument('--add_place', action='store_true',
                            help='Add a place on federation. Need --fed_uuid adn --asset_uuid')
        parser.add_argument('--remove_place', action='store_true',
                    help='Add a place on federation. Need --fed_uuid adn --asset_uuid')

        parser.add_argument('--fed_uuid',
                            help='Federation uuid')
        parser.add_argument('--name',
                            help='Federation name')
        parser.add_argument('--asset_uuid',
                            help='Federation uuid')

        parser.add_argument('--list',
                            action='store_true',
                            help='List all assets on the database')

    def handle(self, *args, **options):
        cache.clear()
        if options.get('create'):
            if not options.get('name'):
                raise CommandError('Please provide a federation name')
            try:
                federation = Federation.objects.get(name=options['name'])
                self.stdout.write(self.style.WARNING(
                    f"Federation already exist : {federation.name}"), ending='\n')
            except Federation.DoesNotExist:
                federation = Federation.objects.create(name=options['name'])
                self.stdout.write(self.style.SUCCESS(
                    f"Federation succesfully created.\nNAME : {federation.name}\nUUID : {federation.uuid}"),
                    ending='\n')

        if options.get('list'):
            for fed in Federation.objects.all():
                self.stdout.write(self.style.SUCCESS(
                    f"Federation : {fed.name} - {fed.uuid}"), ending='\n')
                for asset in fed.assets.all():
                    self.stdout.write(self.style.SQL_KEYWORD(
                        f"    Asset : {asset.name} - {asset.currency_code} - {asset.uuid}"), ending='\n')
                for place in fed.places.all():
                    self.stdout.write(self.style.HTTP_NOT_MODIFIED(
                        f"    Place : {place.name} - {place.uuid}"), ending='\n')

        if options.get('add_asset'):
            if not options.get('fed_uuid'):
                raise CommandError('Please provide a valid federation uuid')
            if not options.get('asset_uuid'):
                raise CommandError('Please provide an asset uuid')
            try :
                federation = Federation.objects.get(uuid=options['fed_uuid'])
                asset = Asset.objects.get(uuid=options['asset_uuid'])
            except Exception as e:
                raise CommandError(e)

            federation.assets.add(asset)
            self.stdout.write(self.style.SUCCESS(
                f"Asset {asset.name} - {asset.currency_code} - {asset.uuid} added to federation {federation.name} - {federation.uuid}"), ending='\n')

        if options.get('remove_asset'):
            if not options.get('fed_uuid'):
                raise CommandError('Please provide a valid federation uuid')
            if not options.get('asset_uuid'):
                raise CommandError('Please provide an asset uuid')
            try :
                federation = Federation.objects.get(uuid=options['fed_uuid'])
                asset = Asset.objects.get(uuid=options['asset_uuid'])
            except Exception as e:
                raise CommandError(e)

            federation.assets.remove(asset)
            self.stdout.write(self.style.SUCCESS(
                f"Asset {asset.name} - {asset.currency_code} - {asset.uuid} removed from federation {federation.name} - {federation.uuid}"), ending='\n')

        if options.get('add_place'):
            if not options.get('fed_uuid'):
                raise CommandError('Please provide a valid federation uuid')
            if not options.get('place_uuid'):
                raise CommandError('Please provide a place uuid')
            try :
                federation = Federation.objects.get(uuid=options['fed_uuid'])
                place = Place.objects.get(uuid=options['place_uuid'])
            except Exception as e:
                raise CommandError(e)

            federation.places.add(place)
            self.stdout.write(self.style.SUCCESS(
                f"Place {place.name} - {place.uuid} added to federation {federation.name} - {federation.uuid}"), ending='\n')

        if options.get('remove_place'):
            if not options.get('fed_uuid'):
                raise CommandError('Please provide a valid federation uuid')
            if not options.get('place_uuid'):
                raise CommandError('Please provide a place uuid')
            try :
                federation = Federation.objects.get(uuid=options['fed_uuid'])
                place = Place.objects.get(uuid=options['place_uuid'])
            except Exception as e:
                raise CommandError(e)

            federation.places.remove(place)
            self.stdout.write(self.style.SUCCESS(
                f"Place {place.name} - {place.uuid} removed from federation {federation.name} - {federation.uuid}"), ending='\n')

        else :
            # Print help
            self.stdout.write(self.style.WARNING(
                f"Usage : python manage.py federations --list"), ending='\n')

            #
            # self.stdout.write(self.style.ERROR(f"ERROR qsdqdqsddqsds"), ending='\n')
            # self.stdout.write(self.style.SUCCESS(f"SUCCESS qsdqdqsddqsds"), ending='\n')
            # self.stdout.write(self.style.WARNING(f"WARNING qsdqdqsddqsds"), ending='\n')
            # self.stdout.write(self.style.NOTICE(f"NOTICE qsdqdqsddqsds"), ending='\n')
            # self.stdout.write(self.style.SQL_FIELD(f"SQL_FIELD qsdqdqsddqsds"), ending='\n')
            # self.stdout.write(self.style.SQL_COLTYPE(f"SQL_COLTYPE qsdqdqsddqsds"), ending='\n')
            # self.stdout.write(self.style.SQL_KEYWORD(f"SQL_KEYWORD qsdqdqsddqsds"), ending='\n')
            # self.stdout.write(self.style.SQL_TABLE(f"SQL_TABLE qsdqdqsddqsds"), ending='\n')
            # self.stdout.write(self.style.HTTP_INFO(f"HTTP_INFO qsdqdqsddqsds"), ending='\n')
            # self.stdout.write(self.style.HTTP_SUCCESS(f"HTTP_SUCCESS qsdqdqsddqsds"), ending='\n')
            # self.stdout.write(self.style.HTTP_REDIRECT(f"HTTP_REDIRECT qsdqdqsddqsds"), ending='\n')
            # self.stdout.write(self.style.HTTP_NOT_MODIFIED(f"HTTP_NOT_MODIFIED qsdqdqsddqsds"), ending='\n')
            # self.stdout.write(self.style.HTTP_BAD_REQUEST(f"HTTP_BAD_REQUEST qsdqdqsddqsds"), ending='\n')
            # self.stdout.write(self.style.HTTP_NOT_FOUND(f"HTTP_NOT_FOUND qsdqdqsddqsds"), ending='\n')
            # self.stdout.write(self.style.HTTP_SERVER_ERROR(f"HTTP_SERVER_ERROR qsdqdqsddqsds"), ending='\n')
            # self.stdout.write(self.style.MIGRATE_HEADING(f"MIGRATE_HEADING qsdqdqsddqsds"), ending='\n')
            # self.stdout.write(self.style.MIGRATE_LABEL(f"MIGRATE_LABEL qsdqdqsddqsds"), ending='\n')
            # self.stdout.write(self.style.ERROR_OUTPUT(f"ERROR_OUTPUT qsdqdqsddqsds"), ending='\n')