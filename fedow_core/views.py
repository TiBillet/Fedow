import base64
import json

import stripe
from cryptography.fernet import Fernet
from django.conf import settings
from django.core import signing
from django.core.signing import Signer
from django.core.validators import URLValidator
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_api_key.models import APIKey
from fedow_core.models import Transaction, Place, Configuration, Asset, CheckoutStripe, Token, Wallet, FedowUser, \
    OrganizationAPIKey
from fedow_core.permissions import HasKeyAndCashlessSignature, HasAPIKey, IsStripe
from fedow_core.serializers import TransactionSerializer, PlaceSerializer, WalletCreateSerializer, HandshakeValidator, \
    NewTransactionValidator
from rest_framework.pagination import PageNumberPagination

from fedow_core.utils import get_request_ip, fernet_encrypt, fernet_decrypt, dict_to_b64_utf8, dict_to_b64, \
    get_public_key, verify_signature, utf8_b64_to_dict

import logging

logger = logging.getLogger(__name__)


def get_api_place_user(request) -> tuple:
    key = request.META["HTTP_AUTHORIZATION"].split()[1]
    api_key = OrganizationAPIKey.objects.get_from_key(key)
    return api_key, api_key.place, api_key.user


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 1000


# Create your views here.
class TestApiKey(viewsets.ViewSet):
    def list(self, request):
        return Response({'message': 'Hello world ApiKey!'})

    def create(self, request):
        # On test ici la permission : HasKeyAndCashlessSignature
        return Response({'message': 'Hello world Signature!'})

    def get_permissions(self):
        permission_classes = [HasAPIKey]
        if self.action in ['create']:
            permission_classes = [HasKeyAndCashlessSignature]
        return [permission() for permission in permission_classes]


class HelloWorld(viewsets.ViewSet):
    """
    GET /heloworld/ : Hello, world!
    """

    def list(self, request):
        return Response({'message': 'Hello world!'})

    def get_permissions(self):
        permission_classes = [AllowAny]
        return [permission() for permission in permission_classes]


### REST API ###

class WalletAPI(viewsets.ViewSet):
    """
    GET /wallet/ : liste des wallets
    """
    pagination_class = StandardResultsSetPagination

    # def list(self, request):
    #     serializer = WalletSerializer(Wallet.objects.all(), many=True)
    #     return Response(serializer.data)

    # def retrieve(self, request, pk=None):
    #     serializer = WalletSerializer(Wallet.objects.get(pk=pk))
    #     return Response(serializer.data)

    def create(self, request):
        serializer = WalletCreateSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get_permissions(self):
        permission_classes = [AllowAny]
        return [permission() for permission in permission_classes]


class PlaceAPI(viewsets.ViewSet):
    """
    GET /place : Places where we can use all federated wallets
    GET /place/<uuid> : Retrieve one place
    POST /place : Create a place where we can use all federated wallets.
    """
    # Déclaration du model principal utilisé pour la vue
    model = Place

    def update(self, request):
        pass

    def create(self, request):
        # HANDSHAKE with cashless server
        # Request only work if came from Cashless server
        # with the right API key gived at the manual creation of new place
        validator = HandshakeValidator(data=request.data, context={'request': request})
        if validator.is_valid():
            validated_data = validator.validated_data

            place: Place = validated_data.get('fedow_place_uuid')
            place.cashless_server_ip = validated_data.get('cashless_ip')
            place.cashless_server_url = validated_data.get('cashless_url')
            place.cashless_rsa_pub_key = validated_data.get('cashless_rsa_pub_key')
            place.cashless_admin_apikey = fernet_encrypt(validated_data.get('cashless_admin_apikey'))
            place.save()

            # Create the definitive key for the admin user
            api_key, place_fk, user = get_api_place_user(request)
            api_key.delete()
            assert place_fk == place, "Place not match with the API key"

            api_key, key = OrganizationAPIKey.objects.create_key(
                name=f"{place.name}:{user.email}",
                place=place,
                user=user,
            )

            # Creation du lien Onboard Stripe
            url_onboard = create_account_link_for_onboard(place)
            data = {
                "url_onboard": url_onboard,
                "admin_key": key,
                "wallet_rsa_public_key": place.wallet.public_pem,
            }

            data_encoded = dict_to_b64_utf8(data)
            return Response(data_encoded, status=status.HTTP_202_ACCEPTED)
        return Response(validator.errors, status=status.HTTP_400_BAD_REQUEST)

    def get_permissions(self):
        permission_classes = [AllowAny]
        if self.action in ['create']:
            permission_classes = [HasAPIKey]
        return [permission() for permission in permission_classes]


def create_account_link_for_onboard(place: Place):
    conf = Configuration.get_solo()
    stripe.api_key = conf.get_stripe_api()

    place.refresh_from_db()
    if not place.stripe_connect_account:
        acc_connect = stripe.Account.create(
            type="standard",
            country="FR",
        )
        id_acc_connect = acc_connect.get('id')
        place.stripe_connect_account = id_acc_connect
        place.save()

    cashless_server_url = place.cashless_server_url

    account_link = stripe.AccountLink.create(
        account=place.stripe_connect_account,
        refresh_url=f"{cashless_server_url}api/onboard_stripe_return/{place.stripe_connect_account}",
        return_url=f"{cashless_server_url}api/onboard_stripe_return/{place.stripe_connect_account}",
        type="account_onboarding",
    )

    url_onboard = account_link.get('url')
    return url_onboard


def HasAPIKeyAndWalletSigned(request, wallet: Wallet) -> bool | Http404:
    """
    Check if the API key and wallet are signed correctly.

    Args:
        request: The HTTP request object.
        wallet: The wallet object.

    Returns:
        True if the API key and wallet are signed correctly.

    Raises:
        Http404: If the API key or wallet are not signed correctly.
    """
    api_key = APIKey.objects.get_from_key(request.META["HTTP_AUTHORIZATION"].split()[1])
    user: FedowUser = api_key.fedow_user
    place: Place = wallet.place

    public_key = get_public_key(wallet.public_pem)
    signature = request.META.get('HTTP_SIGNATURE')
    signed_message = dict_to_b64(request.data)

    if place.admins.filter(id=user.id).exists() and verify_signature(public_key, signed_message, signature):
        return True
    raise Http404


@permission_classes([IsStripe])
class WebhookStripe(APIView):
    def post(self, request):
        # Help STRIPE : https://stripe.com/docs/webhooks/quickstart
        payload = request.data
        if payload.get('type') == "checkout.session.completed":
            # Récupération de l'objet checkout chez Stripe
            checkout_session_id_stripe = payload['data']['object']['id']
            config = Configuration.get_solo()
            stripe.api_key = config.get_stripe_api()
            checkout = stripe.checkout.Session.retrieve(checkout_session_id_stripe)


            # Vérification de la signature Django et des uuid token par la même occasion.
            signer = Signer()
            signed_data = utf8_b64_to_dict(signer.unsign(
                checkout.metadata.get('signed_data')
            ))

            primary_token = Token.objects.get(uuid=signed_data.get('primary_token'))
            user_token = Token.objects.get(uuid=signed_data.get('user_token'))
            assert primary_token.asset == user_token.asset, "Asset not match"

            checkout_db = CheckoutStripe.objects.get(
                checkout_session_id_stripe=checkout_session_id_stripe,
                asset=primary_token.asset,
            )

            if checkout.payment_status == 'paid' :
                # and checkout_db.status == CheckoutStripe.OPEN:
                # Paiement ok, on enregistre la transaction

                # Create token from scratch
                token_creation = Transaction.objects.create(
                    ip=get_request_ip(request),
                    checkoupt_stripe=checkout_db,
                    sender=primary_token.wallet,
                    receiver=primary_token.wallet,
                    asset=primary_token.asset,
                    amount=int(checkout.amount_total),
                    action=Transaction.CREATION,
                    primary_card_uuid=None,  # Création de monnaie
                    card_uuid=None,  # Création de monnaie
                )

                # import ipdb; ipdb.set_trace()
                # checkout_db.status = CheckoutStripe.WALLET_PRIMARY_OK
                # checkout_db.save()

            # logger.info(f"checkout_session_id_stripe : {checkout.checkout_session_id_stripe}")
            # logger.warning(f"checkout_session_id_stripe : {checkout.checkout_session_id_stripe}")

        """
        # import ipdb; ipdb.set_trace()
        # On stocke en db les checkouts Stripe,
        # ils participent aux hash de signature des transactions

        if checkout.is_valid():
            # Création de monnaie : On incrémente le wallet primaire
            prime_wallet = config.primary_wallet,
            prime_asset = Asset.objects.get(federated_primary=True)

            Transaction.objects.create(
                ip=get_request_ip(request),
                checkoupt_stripe=checkout,
                sender=prime_wallet,
                receiver=prime_wallet,
                asset=prime_asset,
                action=Transaction.CREATION,
            )
        """

        return Response("OK", status=status.HTTP_200_OK)


@permission_classes([HasAPIKey])
class Onboard_stripe_return(APIView):
    def get(self, request, encoded_data):
        decoded_data = json.loads(base64.b64decode(encoded_data).decode('utf-8'))
        uuid = decoded_data.get('uuid')

        api_key = APIKey.objects.get_from_key(request.META["HTTP_AUTHORIZATION"].split()[1])
        place = Place.objects.get(pk=uuid)
        if place.wallet.key != api_key:
            return Response("Unauthorized", status=status.HTTP_401_UNAUTHORIZED)

        stripe.api_key = Configuration.get_solo().get_stripe_api()
        info_stripe = stripe.Account.retrieve(decoded_data.get('id_acc_connect'))
        details_submitted = info_stripe.details_submitted
        if details_submitted:
            place.stripe_connect_account = decoded_data.get('id_acc_connect')
            place.stripe_connect_valid = True
            place.save()
            logger.info(f"details_submitted : {details_submitted}")

            # Stripe est OK
            # Envoie des infos de la monnaie fédéré

            federated_asset = Asset.objects.get(federated_primary=True)
            data = {
                'uuid': f'{federated_asset.uuid}',
                'name': federated_asset.name,
                'currency_code': federated_asset.currency_code,
            }

            data_encoded = base64.b64encode(json.dumps(data).encode('utf-8')).decode('utf-8')

            return Response(data_encoded, status=status.HTTP_200_OK)

        else:
            # return Response(f"{create_account_link_for_onboard()}", status=status.HTTP_206_PARTIAL_CONTENT)
            place.stripe_connect_valid = False
            place.save()
            return Response("Compte stripe non valide", status=status.HTTP_406_NOT_ACCEPTABLE)


@permission_classes([HasAPIKey])
class Onboard(APIView):
    def get(self, request):
        return Response(f"{create_account_link_for_onboard()}", status=status.HTTP_202_ACCEPTED)


class TransactionAPI(viewsets.ViewSet):
    """
    GET /transaction/ : liste des transactions
    GET /user/transaction/ : transactions avec primary key <uuid>
    """
    pagination_class = StandardResultsSetPagination

    def list(self, request):
        serializer = TransactionSerializer(Transaction.objects.all(), many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        serializer = TransactionSerializer(Transaction.objects.get(pk=pk))
        return Response(serializer.data)

    def create(self, request):
        serializer = NewTransactionValidator(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get_permissions(self):
        permission_classes = [HasKeyAndCashlessSignature]
        return [permission() for permission in permission_classes]
