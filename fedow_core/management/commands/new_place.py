import base64
import json

import stripe
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify
from rest_framework_api_key.models import APIKey

from fedow_core.models import Asset, Place, Wallet, Configuration

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
    help = 'Creation of a new place. First we test the name. Return a key to enter inside the TiBillet Cashless'

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('name', type=str)

    def handle(self, *args, **options):
        configuration = Configuration.get_solo()
        stripe.api_key = configuration.get_stripe_api()

        if not configuration.domain:
            raise CommandError('Please set the domain name in the admin panel')

        place_name = options['name']
        self.stdout.write(f"", ending='\n')

        try:
            Place.objects.get(name=place_name)
            raise CommandError('Place name already exist')
        except Place.DoesNotExist:
            pass

        self.stdout.write(
            f"Initiate a new point of sale location : {place_name}. "
            f"To finalise the creation, please enter this key in your cashless interface",
            ending='\n')

        api_key, key = APIKey.objects.create_key(name=f"temp_{place_name}")
        # Create wallet
        wallet = Wallet.objects.create(
            key=api_key,
            name=place_name,
        )

        place = Place.objects.create(
            name=place_name,
            wallet=wallet,
        )

        json_key_to_cashless = {
            "domain": configuration.domain,
            "uuid": f"{place.uuid}",
            "temp_key": key,
        }
        encoded_data = base64.b64encode(json.dumps(json_key_to_cashless).encode('utf-8')).decode('utf-8')

        self.stdout.write(self.style.SUCCESS(
            f"New place succesfully created. Please enter this string in your TiBillet admin panel."), ending='\n')
        self.stdout.write(f"", ending='\n')
        self.stdout.write(f"{encoded_data}", ending='\n')
