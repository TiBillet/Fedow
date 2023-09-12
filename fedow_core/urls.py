from django.urls import path, include
from fedow_core.views import TransactionAPI, TestApiKey, HelloWorld, WalletAPI, PlaceAPI, Onboard_stripe_return, \
    WebhookStripe, ChargePrimaryAsset
# from django.conf import settings
from rest_framework import routers

router = routers.DefaultRouter()

router.register(r'helloworld_apikey', TestApiKey, basename='testapikey')
router.register(r'helloworld', HelloWorld, basename='testapikey')

router.register(r'transaction', TransactionAPI, basename='transaction')
router.register(r'wallet', WalletAPI, basename='wallet')
router.register(r'place', PlaceAPI, basename='place')

urlpatterns = [
    path('', include(router.urls)),
    path('onboard_stripe_return/<str:encoded_data>/', Onboard_stripe_return.as_view()),
    path('charge_primary_asset/', ChargePrimaryAsset.as_view()),

    path('webhook_stripe/', WebhookStripe.as_view()),
]
