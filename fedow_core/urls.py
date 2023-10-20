from django.urls import path, include

from fedow_dashboard import urls as dashboard_urls
from fedow_core.views import TransactionAPI, TestApiKey, HelloWorld, WalletAPI, PlaceAPI, Onboard_stripe_return, \
    WebhookStripe, ChargePrimaryAsset, CardAPI, AssetAPI
# from django.conf import settings
from rest_framework import routers

router = routers.DefaultRouter()

router.register(r'helloworld_apikey', TestApiKey, basename='testapikey')
router.register(r'helloworld', HelloWorld, basename='testapikey')

router.register(r'transaction', TransactionAPI, basename='transaction')
router.register(r'place', PlaceAPI, basename='place')
router.register(r'asset', AssetAPI, basename='asset')
router.register(r'wallet', WalletAPI, basename='wallet')
router.register(r'card', CardAPI, basename='card')

# router.register(r'', IndexRESThtmx, basename='index')

urlpatterns = [
    # Requete depuis le cashless pour le retour de l'onboarding stripe
    path('onboard_stripe_return/', Onboard_stripe_return.as_view()),

    path('charge_primary_asset/', ChargePrimaryAsset.as_view()),
    path('webhook_stripe/', WebhookStripe.as_view()),
    path('', include(dashboard_urls)),
    path('', include(router.urls)),
]
