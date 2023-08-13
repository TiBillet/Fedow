from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_api_key.models import APIKey
from rest_framework_api_key.permissions import HasAPIKey

from fedow_core.models import Transaction, Place
from fedow_core.serializers import TransactionSerializer, PlaceSerializer, WalletCreateSerializer
from rest_framework.pagination import PageNumberPagination

from fedow_core.utils import get_client_ip
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

        # Check place exist
        place = get_object_or_404(Place, pk=request.data.get('uuid'))
        ip = get_client_ip(request)

        # Si place a déja été configuré, on renvoie un 400
        if place.cashless_server_ip or place.cashless_server_url or place.cashless_server_key:
            logger.error(f"{timezone.localtime()} Place already configured - ip : {ip} - {request.data}")
            return Response('HTTP_400_BAD_REQUEST', status=status.HTTP_400_BAD_REQUEST)

        # Check if key is the temp given by the manual creation
        key = request.META["HTTP_AUTHORIZATION"].split()[1]
        api_key = APIKey.objects.get_from_key(key)
        if place.wallet.key != api_key or 'temp_' not in api_key.name:
            logger.error(f"{timezone.localtime()} Place create Unauthorized - ip : {ip} - {request.data}")
            return Response('Unauthorized', status=status.HTTP_401_UNAUTHORIZED)

        # Get url, key and ip from cashless server
        place.cashless_server_ip  = ip
        place.cashless_server_url = request.data.get('csu')
        place.cashless_server_key = request.data.get('csk')

        return Response(PlaceSerializer(place).data, status=status.HTTP_201_CREATED)

    def get_permissions(self):
        permission_classes = [AllowAny]
        if self.action in ['create']:
            permission_classes = [HasAPIKey]
        return [permission() for permission in permission_classes]


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
