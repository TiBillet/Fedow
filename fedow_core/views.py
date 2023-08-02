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


# Create your views here.


class TransactionAPI(viewsets.ViewSet):
    """
    API CRUD : create read update delete
    Exemple :
    GET /api/transaction/ : liste des utilisateurs
    GET /api/user/transaction/ : utilisateur avec primary key <uuid>
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