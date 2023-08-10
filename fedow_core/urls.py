from django.urls import path, include
from fedow_core.views import TransactionAPI, TestApiKey, HelloWorld, WalletAPI
# from django.conf import settings
from rest_framework import routers

router = routers.DefaultRouter()

router.register(r'helloworld_apikey', TestApiKey, basename='testapikey')
router.register(r'helloworld', HelloWorld, basename='testapikey')

router.register(r'transaction', TransactionAPI, basename='transaction')
router.register(r'wallet', WalletAPI, basename='wallet')

urlpatterns = [
    path('', include(router.urls)),
]
