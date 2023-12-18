import base64
import json

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
        parser.add_argument('--create', action='store_true',
                            help='Create a new Place. Need --name --email. Can --description. If --test -> auto add to test federation')
        parser.add_argument('--list', action='store_true', help="List all places")

        parser.add_argument('--name', type=str)
        parser.add_argument('--email', type=str)
        parser.add_argument('--description', type=str)
        parser.add_argument('--test', type=str)

    def handle(self, *args, **options):

        if options.get('list'):
            for place in Place.objects.all():
                self.stdout.write(self.style.HTTP_NOT_MODIFIED(
                    f"Place : {place} - {place.uuid}"), ending='\n')

        if options.get('create'):
            if not options.get('name'):
                raise CommandError('Please provide a place name')
            if not options.get('email'):
                raise CommandError('Please provide a admin email')

            try:
                configuration = Configuration.get_solo()

                if not configuration.domain:
                    raise CommandError('Please set the domain name in the admin panel')

                # Avons nous les informations nécessaires ?
                description = options.get('description', None)
                email = options['email']
                place_name = options['name']
                test = options.get('test')

                if not all([email, place_name]):
                    raise CommandError('Please provide --name and --email')

                user, user_created = get_or_create_user(email)

                try:
                    Place.objects.get(name=place_name)
                    raise CommandError('Place name already exist')
                except Place.DoesNotExist:
                    pass

                place = Place.objects.create(
                    name=place_name,
                    description=description,
                    wallet=wallet_creator(),
                )

                place.admins.add(user)
                place.save()

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

                # Pour test, on le lie à la fedération de test :
                if test == "TEST FED":
                    federation = Federation.objects.get(name='TEST FED')
                    federation.places.add(place)

                # TODO: Envoyer la clé par email
                self.stdout.write(self.style.SUCCESS(
                    f"New place succesfully created.\nNAME : {place.name}\nWALLET UUID: {place.wallet.uuid}\nPlease enter this string in your TiBillet/LaBoutik admin panel : "),
                    ending='\n')
                self.stdout.write(f"", ending='\n')
                self.stdout.write(f"{utf8_encoded_data}", ending='\n')

            except Exception as e:
                raise CommandError(e)
