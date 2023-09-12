from io import StringIO
from uuid import uuid4

import stripe
from django.conf import settings
from django.core import signing
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.core.signing import Signer

from fedow_core.models import Asset, Configuration, Token, get_or_create_user, Wallet, CheckoutStripe, Origin, Place, \
    Card
from fedow_core.utils import rsa_generator, dict_to_b64_utf8, utf8_b64_to_dict


class Command(BaseCommand):
    help = 'Asset creation'

    def add_arguments(self, parser):
        pass

    # parser.add_argument('--test', type=str)

    def handle(self, *args, **options):
        # Stripe ne permet pas de valider un checkout automatiquement en test.
        # Il faut le faire manuellement, on crée alors tout ce qu'il faut pour
        # faire un checkout valide.
        config = Configuration.get_solo()
        stripe.api_key = settings.STRIPE_KEY_TEST


        ### Création de l'user
        email = 'lambda@lambda.com'
        user, created = get_or_create_user(email)

        ### Création d'un lieu
        try :
            place = Place.objects.get(name='TestPlace')
        except Place.DoesNotExist:
            out = StringIO()
            call_command('new_place',
                         '--name', 'TestPlace',
                         '--email', 'place@place.coop',
                         stdout=out)

            self.last_line = out.getvalue().split('\n')[-2]
            decoded_data = utf8_b64_to_dict(self.last_line)
            place = Place.objects.get(pk=decoded_data.get('uuid'))

        ### Création d'une carte
        try :
            card = Card.objects.get(user=user)
        except Card.DoesNotExist:

            gen1, created = Origin.objects.get_or_create(
                place=place,
                generation=1
            )

            nfc_uuid = uuid4()
            qrcode = uuid4()
            card = Card.objects.create(
                uuid=uuid4(),
                first_tag_id=f"{str(nfc_uuid).split('-')[0]}",
                nfc_uuid=nfc_uuid,
                qr_code_printed=qrcode,
                number=str(qrcode).split('-')[0],
                origin=gen1,
                user=user,
            )


        primary_wallet = config.primary_wallet

        stripe_asset = Asset.objects.get(stripe_primary=True)
        id_price_stripe = stripe_asset.get_id_price_stripe()

        primary_token, created = Token.objects.get_or_create(
            wallet=primary_wallet,
            asset=stripe_asset,
        )

        user_token, created = Token.objects.get_or_create(
            wallet=user.wallet,
            asset=stripe_asset,
        )

        # Lancer stripe :
        # stripe listen --forward-to http://127.0.0.1:8000/webhook_stripe/
        # S'assurer que la clé de signature soit la même que dans le .env
        line_items = [{
            "price": f"{id_price_stripe}",
            "quantity": 1
        }]

        metadata = {
            "primary_token": f"{primary_token.uuid}",
            "user_token": f"{user_token.uuid}",
            "card_uuid": f"{card.uuid}",
        }
        signer = Signer()
        signed_data = signer.sign(dict_to_b64_utf8(metadata))

        data_checkout = {
            'success_url': 'https://127.0.0.1:8000/checkout_stripe/',
            'cancel_url': 'https://127.0.0.1:8000/checkout_stripe/',
            'payment_method_types': ["card"],
            'customer_email': f'{email}',
            'line_items': line_items,
            'mode': 'payment',
            'metadata': {
                'signed_data': f'{signed_data}',
            },
            'client_reference_id': f"{user.pk}",
        }
        checkout_session = stripe.checkout.Session.create(**data_checkout)

        # Enregistrement du checkout Stripe dans la base de donnée
        checkout_db = CheckoutStripe.objects.create(
            checkout_session_id_stripe=checkout_session.id,
            asset=user_token.asset,
            status=CheckoutStripe.OPEN,
            user=user,
            metadata=signed_data,
        )

        # self.stdout.write(self.style.WARNING(f"stripe listen --forward-to http://127.0.0.1:8000/webhook_stripe/"),
        #                   ending='\n')
        # self.stdout.write(
        #     self.style.WARNING(f"Payez manuellement, gardez le numéro de l'event pour faire un stripe events resend"),
        #     ending='\n')
        self.stdout.write(self.style.SUCCESS(f'{checkout_session.url}'), ending='\n')
