from django.urls import path, include
from fedow_core.views import TransactionAPI, TestApiKey, HelloWorld
# from django.conf import settings
from rest_framework import routers

router = routers.DefaultRouter()

router.register(r'transaction', TransactionAPI, basename='transaction')
router.register(r'helloworld', HelloWorld, basename='testapikey')
router.register(r'helloworld_apikey', TestApiKey, basename='testapikey')

urlpatterns = [
    path('', include(router.urls)),
]
