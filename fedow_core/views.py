import base64
import json

import stripe
from django.core.validators import URLValidator
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_api_key.models import APIKey
from rest_framework_api_key.permissions import HasAPIKey

from fedow_core.models import Transaction, Place, Configuration
from fedow_core.serializers import TransactionSerializer, PlaceSerializer, WalletCreateSerializer, ConnectPlaceCashless
from rest_framework.pagination import PageNumberPagination

import logging

logger = logging.getLogger(__name__)


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 1000


# Create your views here.
class TestApiKey(viewsets.ViewSet):
    """
    GET /helloworld_apikey/ : Hello, world!
    """

    def list(self, request):
        key = request.META["HTTP_AUTHORIZATION"].split()[1]
        api_key = APIKey.objects.get_from_key(key)
        return Response({'message': 'Hello world!'})

    def get_permissions(self):
        permission_classes = [HasAPIKey]
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
        serializer = WalletCreateSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get_permissions(self):
        permission_classes = [HasAPIKey]
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
        # Request only work if came from Cashless server
        # with the right API key gived at the manual creation of new place
        validator = ConnectPlaceCashless(data=request.data, context={'request': request})
        if validator.is_valid():
            place: Place = validator.validated_data['uuid']

            # on renseigne les infos du serveur cashless
            place.cashless_server_ip = validator.validated_data['ip']
            place.cashless_server_url = validator.validated_data['url']
            place.cashless_server_key = validator.validated_data['apikey']


            # Create the definitive key for the cashless server
            api_key, key = APIKey.objects.create_key(name=place.name)
            place.wallet.key = api_key
            place.wallet.save()
            place.save()

            # Creation du lien Onboard Stripe
            url_onboard = create_account_link_for_onboard(place)

            data = {
                "url_onboard": url_onboard,
                "key": key
            }

            data_encoded = base64.b64encode(json.dumps(data).encode('utf-8')).decode('utf-8')

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

    url_cashless_server = place.cashless_server_url

    account_link = stripe.AccountLink.create(
        account=place.stripe_connect_account,
        refresh_url=f"{url_cashless_server}/onboard_stripe_return/{place.stripe_connect_account}",
        return_url=f"{url_cashless_server}/onboard_stripe_return/{place.stripe_connect_account}",
        type="account_onboarding",
    )

    url_onboard = account_link.get('url')
    return url_onboard

@permission_classes([AllowAny])
class Onboard_stripe_return(APIView):
    def get(self, request, id_acc_connect):
        stripe.api_key = Configuration.get_solo().get_stripe_api()
        info_stripe = stripe.Account.retrieve(id_acc_connect)
        details_submitted = info_stripe.details_submitted
        if details_submitted:
            logger.info(f"details_submitted : {details_submitted}")
            # TODO: COntinuer l'installation
        else:
            return Response(f"{create_account_link_for_onboard()}", status=status.HTTP_206_PARTIAL_CONTENT)


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
        serializer = TransactionSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get_permissions(self):
        permission_classes = [HasAPIKey]
        return [permission() for permission in permission_classes]
