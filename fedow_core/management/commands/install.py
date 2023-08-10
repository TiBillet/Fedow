import os

from rest_framework_api_key.models import APIKey

from fedow_core.models import Configuration, Wallet
from django.core.management.base import BaseCommand, CommandError
class Command(BaseCommand):

    def handle(self, *args, **options):

        try:
            config = Configuration.get_solo()
            self.stdout.write(self.style.ERROR(f'Configuration and master wallet already exists : {config.name}'), ending='\n')
        except Exception as e:

            instance_name = os.environ.get('DOMAIN','fedow.betabillet.tech')

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
            self.stdout.write(self.style.SUCCESS(f'Configuration created : {instance_name}'), ending='\n')