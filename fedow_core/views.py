import base64
import json
from io import StringIO

import stripe
from cryptography.fernet import Fernet
from django.conf import settings
from django.core import signing
from django.core.management import call_command
from django.core.serializers import serialize
from django.core.serializers.json import DjangoJSONEncoder
from django.core.signing import Signer
from django.core.validators import URLValidator
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from faker import Faker
from rest_framework import viewsets, status, serializers
from rest_framework.decorators import permission_classes, action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_api_key.models import APIKey
from fedow_core.models import Transaction, Place, Configuration, Asset, CheckoutStripe, Token, Wallet, FedowUser, \
    OrganizationAPIKey, Card, Federation
from fedow_core.permissions import HasKeyAndCashlessSignature, HasAPIKey, IsStripe
from fedow_core.serializers import TransactionSerializer, WalletCreateSerializer, HandshakeValidator, \
    TransactionW2W, CardSerializer, CardCreateValidator, \
    AssetCreateValidator, OnboardSerializer, AssetSerializer, WalletSerializer, CardRefundOrVoidValidator, \
    FederationSerializer, BadgeValidator
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


#### HTMX PAGE ####


### REST API ###

class AssetAPI(viewsets.ViewSet):
    # def list(self, request):
    #     serializer = AssetSerializer(Asset.objects.all(), many=True)
    #     return Response(serializer.data)

    def create(self, request):
        # Création de l'asset :
        serializer = AssetCreateValidator(data=request.data, context={'request': request})

        if serializer.is_valid():
            # Sérialisation de l'asset
            asset_seralized = AssetSerializer(serializer.asset, context={'request': request})
            return Response(asset_seralized.data, status=status.HTTP_201_CREATED)

        logger.error(f"Asset create error : {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def list(self, request):
        accepted_assets = request.place.accepted_assets()
        serializers = AssetSerializer(accepted_assets, many=True, context={'request': request})
        # if settings.DEBUG:
        #     logger.info(f"{timezone.now()} {len(serializers.data)} Assets list")
        #     logger.info(f"")
        return Response(serializers.data)

    def retrieve(self, request, pk=None):
        asset = get_object_or_404(Asset, pk=pk)
        # self.action = retrieve -> on ajoute les totaux des token dans la réponse
        serializer = AssetSerializer(asset, context={'request': request, "action": self.action})
        return Response(serializer.data)

    def get_permissions(self):
        permission_classes = [HasKeyAndCashlessSignature]
        return [permission() for permission in permission_classes]


class CardAPI(viewsets.ViewSet):

    @action(detail=False, methods=['post'])
    def refund(self, request):
        # VOID ou REFUND, on vide la carte des assets non adhésion avec le lieu comme origine
        validator = CardRefundOrVoidValidator(data=request.data, context={'request': request})
        if validator.is_valid():
            refund_data = {
                "serialized_card": CardSerializer(validator.user_card, context={'request': request}).data,
                "before_refund_serialized_wallet": validator.ex_wallet_serialized,
                "serialized_transactions": validator.transactions,
            }
            return Response(refund_data, status=status.HTTP_205_RESET_CONTENT)
        logger.error(f"{timezone.now()} Card update error : {validator.errors}")
        return Response(validator.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def badge(self, request):
        validator = BadgeValidator(data=request.data, context={'request': request})
        if validator.is_valid():
            transaction = validator.transaction
            transaction_serialized = TransactionSerializer(transaction, context={'request': request})
            return Response(transaction_serialized, status=status.HTTP_200_OK)
        logger.error(f"{timezone.now()} Card update error : {validator.errors}")
        return Response(validator.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def get_checkout(self, request):
        # Même sérializer que la création, sauf qu'on vérifie que le mail soit bien présent.
        if not request.data.get('email'):
            return Response("Email missing", status=status.HTTP_406_NOT_ACCEPTABLE)

        serializer = WalletCreateSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            config = Configuration.get_solo()
            stripe.api_key = config.get_stripe_api()

            # Vérification que l'email soit bien présent pour l'envoyer a Stripe
            user: FedowUser = serializer.user
            email = user.email

            primary_wallet = config.primary_wallet
            stripe_asset = Asset.objects.get(wallet_origin=primary_wallet, category=Asset.STRIPE_FED_FIAT)
            id_price_stripe = stripe_asset.get_id_price_stripe()

            primary_token, created = Token.objects.get_or_create(
                wallet=primary_wallet,
                asset=stripe_asset,
            )

            user_token, created = Token.objects.get_or_create(
                wallet=user.wallet,
                asset=stripe_asset,
            )

            line_items = [{
                "price": f"{id_price_stripe}",
                "quantity": 1
            }]

            metadata = {
                "primary_token": f"{primary_token.uuid}",
                "user_token": f"{user_token.uuid}",
                "card_uuid": f"{serializer.card.uuid}",
            }

            signer = Signer()
            signed_data = signer.sign(dict_to_b64_utf8(metadata))

            data_checkout = {
                'success_url': f'https://{config.domain}/checkout_stripe/',
                'cancel_url': f'https://{config.domain}/checkout_stripe/',
                'payment_method_types': ["card"],
                'customer_email': f'{email}',
                'line_items': line_items,
                'mode': 'payment',
                'metadata': {
                    'signed_data': f'{signed_data}',
                },
                'client_reference_id': f"{user.pk}",
            }

            if settings.STRIPE_TEST and settings.DEBUG:
                data_checkout['success_url'] = f'https://127.0.0.1:8442/checkout_stripe/'
                data_checkout['cancel_url'] = f'https://127.0.0.1:8442/checkout_stripe/'

            try:
                checkout_session = stripe.checkout.Session.create(**data_checkout)
            except Exception as e :
                logger.error(f"Creation of Stripe Checkout error : {e}")
                import ipdb; ipdb.set_trace()
                raise Exception("Creation of Stripe Checkout error")

            # Enregistrement du checkout Stripe dans la base de donnée
            checkout_db = CheckoutStripe.objects.create(
                checkout_session_id_stripe=checkout_session.id,
                asset=user_token.asset,
                status=CheckoutStripe.OPEN,
                user=user,
                metadata=signed_data,
            )

            return Response(checkout_session.url, status=status.HTTP_202_ACCEPTED)

        logger.error(f"get_checkout error : {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


    def retrieve(self, request, pk=None):
        # Utilisé par les serveurs cashless comme un check card
        try:
            card = Card.objects.get(first_tag_id=pk)
            serializer = CardSerializer(card, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Card.DoesNotExist:
            return Response("Carte inconnue", status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"{timezone.now()} Card retrieve error : {e}")
            raise e

    def create(self, request):
        card_serializer = CardCreateValidator(data=request.data, context={'request': request}, many=True)
        if card_serializer.is_valid():
            card_serializer.save()
            logger.info(f"{len(card_serializer.validated_data)} Cards created")
            return Response(f"{len(card_serializer.validated_data)}", status=status.HTTP_201_CREATED,
                            content_type="application/json")

        logger.error(f"Card create error : {card_serializer.errors}")
        return Response(card_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get_permissions(self):
        permission_classes = [HasKeyAndCashlessSignature]
        return [permission() for permission in permission_classes]


class WalletAPI(viewsets.ViewSet):
    """
    GET /wallet/ : liste des wallets
    """
    pagination_class = StandardResultsSetPagination

    # def list(self, request):
    #     serializer = WalletSerializer(Wallet.objects.all(), many=True)
    #     return Response(serializer.data)

    def retrieve(self, request, pk=None):
        serializer = WalletSerializer(Wallet.objects.get(pk=pk), context={'request': request})
        return Response(serializer.data)

    def create(self, request):
        wallet_create_serializer = WalletCreateSerializer(data=request.data, context={'request': request})
        if wallet_create_serializer.is_valid():
            wallet_uuid = wallet_create_serializer.data['wallet']
            return Response(f"{wallet_uuid}", status=status.HTTP_201_CREATED)

        return Response(wallet_create_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get_permissions(self):
        permission_classes = [HasKeyAndCashlessSignature]
        return [permission() for permission in permission_classes]


def get_new_place_token_for_test(request):
    if request.method == 'GET':
        if settings.DEBUG:
            out = StringIO()
            faker = Faker()
            name = faker.company()
            if not Federation.objects.filter(name='TEST FED').exists():
                call_command('federations',
                             '--create',
                             '--name', f'TEST FED',
                             stdout=out)

            call_command('places', '--create',
                         '--name', f'{name}',
                         '--email', f'{faker.email()}',
                         stdout=out)
            encoded_data = out.getvalue().split('\n')[-2]
            return JsonResponse({"encoded_data": encoded_data})

    return Response("Not found", status=status.HTTP_404_NOT_FOUND)


class FederationAPI(viewsets.ViewSet):

    def list(self, request):
        place: Place = request.place
        federations = place.federations.all()
        serializer = FederationSerializer(federations, many=True, context={'request': request})
        return Response(serializer.data)

    def get_permissions(self):
        permission_classes = [HasKeyAndCashlessSignature]
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
            place.dokos_id = validated_data.get('dokos_id')
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
                "place_admin_apikey": key,
                "place_wallet_public_pem": place.wallet.public_pem,
                "place_wallet_uuid": str(place.wallet.uuid),
            }
            print(data)

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


@permission_classes([IsStripe])
class WebhookStripe(APIView):
    def post(self, request):
        # Help STRIPE : https://stripe.com/docs/webhooks/quickstart
        try:
            payload = request.data
            if not payload.get('type') == "checkout.session.completed":
                return Response("Not for me", status=status.HTTP_204_NO_CONTENT)

            # Récupération de l'objet checkout chez Stripe
            checkout_session_id_stripe = payload['data']['object']['id']
            config = Configuration.get_solo()
            stripe.api_key = config.get_stripe_api()
            checkout = stripe.checkout.Session.retrieve(checkout_session_id_stripe)

            # Vérification de la signature Django et des uuid token par la même occasion.
            signer = Signer()
            signed_data = checkout.metadata.get('signed_data')
            unsigned_data = utf8_b64_to_dict(signer.unsign(signed_data))

            primary_token = Token.objects.get(uuid=unsigned_data.get('primary_token'))
            user_token = Token.objects.get(uuid=unsigned_data.get('user_token'))
            card = Card.objects.get(uuid=unsigned_data.get('card_uuid'))

            # L'asset est-il le même entre les deux tokens ?
            if not primary_token.asset == user_token.asset:
                return Response("Asset not match", status=status.HTTP_409_CONFLICT)

            # Le wallet est il le stripe primaire ?
            if not config.primary_wallet == primary_token.wallet:
                return Response("Primary wallet not match", status=status.HTTP_409_CONFLICT)

            # L'user du token est-il le même que celui de la carte ?
            if not card.user == user_token.wallet.user:
                return Response("User not match", status=status.HTTP_409_CONFLICT)

            checkout_db = CheckoutStripe.objects.get(
                checkout_session_id_stripe=checkout_session_id_stripe,
                asset=primary_token.asset,
            )

            if ((checkout.payment_status == 'paid'
                and checkout_db.status == CheckoutStripe.OPEN)
                or (settings.STRIPE_TEST and settings.DEBUG)):
                # Paiement ok ou stripe TEST, on enregistre la transaction

                tr_data = {
                    'amount': int(checkout.amount_total),
                    'sender': f'{primary_token.wallet.uuid}',
                    'receiver': f'{user_token.wallet.uuid}',
                    'asset': f'{primary_token.asset.uuid}',
                    'action': f'{Transaction.REFILL}',
                    'metadata': f'{signed_data}',
                    'user_card_uuid': f'{card.uuid}',
                    'checkout_stripe': f'{checkout_db.uuid}'
                }

                transaction_validator = TransactionW2W(data=tr_data, context={'request': request})
                if not transaction_validator.is_valid():
                    logger.error(f"TransactionW2W serializer ERROR : {transaction_validator.errors}")
                    # Update checkout status
                    checkout_db.status = CheckoutStripe.ERROR
                    checkout_db.save()
                    return Response("TransactionW2W serializer ERROR", status=status.HTTP_405_METHOD_NOT_ALLOWED)

                # Update checkout status
                checkout_db.status = CheckoutStripe.PAID
                checkout_db.save()

                logger.info(
                    f"WebhookStripe 200 OK - checkout.payment_status : {checkout.payment_status} - En db checkout_db.status {checkout_db.status}")
                return Response("OK", status=status.HTTP_200_OK)

            logger.warning(
                f"WebhookStripe 208 DEJA TRAITE - checkout.payment_status : {checkout.payment_status} - En db checkout_db.status {checkout_db.status}")
            return Response("Déja traité", status=status.HTTP_208_ALREADY_REPORTED)

        except Exception as e:
            logger.error(f"WebhookStripe 500 ERROR : {e}")
            return Response("ERROR", status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@permission_classes([HasKeyAndCashlessSignature])
class Onboard_stripe_return(APIView):
    def post(self, request):
        onboard_serializer = OnboardSerializer(data=request.data, context={'request': request})
        if onboard_serializer.is_valid():
            info_stripe = onboard_serializer.info_stripe
            details_submitted = info_stripe.get('details_submitted')
            place = onboard_serializer.validated_data.get('fedow_place_uuid')

            if details_submitted:
                logger.info(f"Stripe details_submitted : {details_submitted}")
                # Stripe est OK
                place.stripe_connect_account = onboard_serializer.validated_data.get('id_acc_connect')
                place.stripe_connect_valid = True
                place.save()

                # Mise à jour du cache avec la monnaie fédérée
                place.federated_with()

                # Envoie des infos de la monnaie fédéré
                config = Configuration.get_solo()
                primary_wallet = config.primary_wallet
                primary_stripe_asset = Asset.objects.get(origin=primary_wallet, category=Asset.STRIPE_FED_FIAT)
                if primary_stripe_asset.is_stripe_primary():
                    data = {
                        'primary_stripe_asset_uuid': f'{primary_stripe_asset.uuid}',
                        'primary_stripe_asset_name': primary_stripe_asset.name,
                        'primary_stripe_asset_currency_code': primary_stripe_asset.currency_code,
                    }

                    return Response(data, status=status.HTTP_200_OK)

            # return Response(f"{create_account_link_for_onboard()}", status=status.HTTP_206_PARTIAL_CONTENT)
            place.stripe_connect_valid = False
            place.save()
            logger.error(f"Onboard_stripe_return error : {onboard_serializer.errors}")
        logger.error(f"Onboard_stripe_return : {request.data}")
        return Response("Compte stripe non valide", status=status.HTTP_406_NOT_ACCEPTABLE)


@permission_classes([HasAPIKey])
class CheckoutStripeForChargePrimaryAsset(APIView):
    # Utilisez l'api card
    pass

class MembershipAPI(viewsets.ViewSet):
    def create(self, request):
        pass
        # serializer = TransactionW2W(data=request.data, context={'request': request})


class TransactionAPI(viewsets.ViewSet):
    """
    GET /transaction/ : liste des transactions
    GET /user/transaction/ : transactions avec primary key <uuid>
    """
    pagination_class = StandardResultsSetPagination

    def list(self, request):
        serializer = TransactionSerializer(Transaction.objects.all(), many=True, context={'request': request})
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        serializer = TransactionSerializer(Transaction.objects.get(pk=pk), context={'request': request})
        return Response(serializer.data)

    def create(self, request):
        transaction_validator = TransactionW2W(data=request.data, context={'request': request})
        if transaction_validator.is_valid():
            transaction: Transaction = transaction_validator.transaction
            transaction_serialized = TransactionSerializer(transaction, context={'request': request})
            return Response(transaction_serialized.data, status=status.HTTP_201_CREATED)

        logger.error(f"{timezone.localtime()} ERROR - Transaction create error : {transaction_validator.errors}")
        return Response(transaction_validator.errors, status=status.HTTP_400_BAD_REQUEST)

    def get_permissions(self):
        # Cette permission rajoute place dans request si la signature est validé
        # place: Place = request.place
        permission_classes = [HasKeyAndCashlessSignature]
        return [permission() for permission in permission_classes]
