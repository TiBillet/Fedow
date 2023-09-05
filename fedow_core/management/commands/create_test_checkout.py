import stripe
from django.conf import settings
from django.core import signing
from django.core.management.base import BaseCommand
from django.core.signing import Signer

from fedow_core.models import Asset, Configuration, Token, get_or_create_user, Wallet, CheckoutStripe
from fedow_core.utils import rsa_generator, dict_to_b64_utf8


class Command(BaseCommand):
    help = 'Asset creation'

    def add_arguments(self, parser):
        pass

    # parser.add_argument('--test', type=str)

    def handle(self, *args, **options):
        config = Configuration.get_solo()
        stripe.api_key = settings.STRIPE_KEY_TEST
        email = 'lambda@lambda.com'
        user, created = get_or_create_user(email)
        if not user.wallet:
            private_pem, public_pem = rsa_generator()
            user.wallet = Wallet.objects.create(
                ip='127.0.0.1',
                private_pem=private_pem,
                public_pem=public_pem,
            )
            user.save()

        primary_wallet = config.primary_wallet

        stripe_asset = Asset.objects.get(federated_primary=True)
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
        )

        self.stdout.write(self.style.WARNING(f"stripe listen --forward-to http://127.0.0.1:8000/webhook_stripe/"),
                          ending='\n')
        self.stdout.write(
            self.style.WARNING(f"Payez manuellement, gardez le numéro de l'event pour faire un stripe events resend"),
            ending='\n')
        self.stdout.write(self.style.SUCCESS(f'{checkout_session.url}'), ending='\n')
