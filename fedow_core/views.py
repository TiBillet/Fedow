from django.shortcuts import render
from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_api_key.permissions import HasAPIKey

from fedow_core.models import Transaction
from fedow_core.serializers import TransactionSerializer
from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 1000


def apikey_validate(request):
    """
    Return Wallet associate to a public key
    Check ip Source and public key
    """


"""
def user_apikey_valid(view):
    # En string : On vérifie que view.basename == url.basename
    # exemple dans DjangoFiles/ApiBillet/urls.py
    # router.register(r'events', api_view.EventsViewSet, basename='event')
    # On peut aussi faire action = view.action -> create ? Pas utile pour l'instant.
    try :
        key = view.request.META["HTTP_AUTHORIZATION"].split()[1]
        api_key = APIKey.objects.get_from_key(key)
        tenant_apikey = get_object_or_404(ExternalApiKey, key=api_key)

        ip = get_client_ip(view.request)

        logger.info(
            f"is_apikey_valid : "
            f"ip request : {ip} - ip apikey : {tenant_apikey.ip} - "
            f"basename : {view.basename} : {tenant_apikey.api_permissions().get(view.basename)} - "
            f"permission : {tenant_apikey.api_permissions()}"
        )

        if all([
            ip == tenant_apikey.ip,
            tenant_apikey.api_permissions().get(view.basename)
        ]):
            return tenant_apikey.user

    except:
        return False

"""


# Create your views here.
class TestApiKey(viewsets.ViewSet):
    """
    API Test HasAPIKey. Si hello word, vous avez la permission :)

    Exemple :
    GET /api/ : Hello, world!
    """

    def list(self, request):
        return Response({'message': 'Hello world!'})

    def get_permissions(self):
        permission_classes = [HasAPIKey]
        return [permission() for permission in permission_classes]


class HelloWorld(viewsets.ViewSet):
    """
    API Test AllowAny. If hello word, you have permission :)

    Example:
    GET /api/ : Hello, world!
    """

    def list(self, request):
        return Response({'message': 'Hello world!'})

    def get_permissions(self):
        permission_classes = [AllowAny]
        return [permission() for permission in permission_classes]


class TransactionAPI(viewsets.ViewSet):
    """
    API CRUD : create read update delete
    Exemple :
    GET /api/transaction/ : liste des transactions
    GET /api/user/transaction/ : transactions avec primary key <uuid>
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
        return Response(serializer.errors)

    def get_permissions(self):
        permission_classes = [HasAPIKey]
        return [permission() for permission in permission_classes]
