import base64
import json

import stripe
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify
from rest_framework_api_key.models import APIKey

from fedow_core.models import Asset, Place, Wallet, Configuration, get_or_create_user, OrganizationAPIKey, Federation, \
    wallet_creator
from fedow_core.utils import rsa_generator, dict_to_b64_utf8

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
    help = 'Creation of a new place. Need --name and --email'

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('--name', type=str)
        parser.add_argument('--email', type=str)
        parser.add_argument('--federation', type=str)

    def handle(self, *args, **options):
        configuration = Configuration.get_solo()
        stripe.api_key = configuration.get_stripe_api()

        if not configuration.domain:
            raise CommandError('Please set the domain name in the admin panel')

        # Avons nous les informations nécessaires ?
        # Si non, on les réclame en input user
        federation_name = options.get('federation', None)
        email = options.get('email', None)
        place_name = options.get('name', None)

        if not all([federation_name, email, place_name]):
            place_name = input("Please enter the name of the place : ")
            email = input("Please enter the admin email : ")
            print("\n".join([f.name for f in Federation.objects.all()]))
            federation_name = input("Please enter the Federation name :")

        federation = Federation.objects.get(name=federation_name)
        user, user_created = get_or_create_user(email)

        if not user_created:
            raise CommandError('User name already exist')

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

        place = Place.objects.create(
            name=place_name,
            wallet=wallet_creator(),
        )

        place.admins.add(user)
        place.save()
        federation.places.add(place)

        api_key, key = OrganizationAPIKey.objects.create_key(
            name=f"temp_{place_name}:{user.email}",
            place=place,
            user=user,
        )

        json_key_to_cashless = {
            "domain": configuration.domain,
            "uuid": f"{place.uuid}",
            "temp_key": key,
        }
        utf8_encoded_data = dict_to_b64_utf8(json_key_to_cashless)

        # TODO: Envoyer la clé par email
        self.stdout.write(self.style.SUCCESS(
            f"New place succesfully created. Please enter this string in your TiBillet admin panel."), ending='\n')
        self.stdout.write(f"", ending='\n')
        self.stdout.write(f"{utf8_encoded_data}", ending='\n')
