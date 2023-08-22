import os

from django.core.management import call_command
from rest_framework_api_key.models import APIKey

from fedow_core.models import Configuration, Wallet, Asset
from django.core.management.base import BaseCommand, CommandError


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

            instance_name = os.environ.get('DOMAIN', 'fedow.tibillet.localhost')

            primary_key, key = APIKey.objects.create_key(name=instance_name)
            primary_wallet = Wallet.objects.create(
                name="Primary",
                ip="127.0.0.1",
                key=primary_key,
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
                    fed.save()
                except Exception as e :
                    self.stdout.write(self.style.ERROR(f'Asset TiBIllet already exist ? {e}'))

            self.stdout.write(self.style.SUCCESS(f'Configuration created : {instance_name}'), ending='\n')
