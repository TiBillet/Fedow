from django.urls import path, include
from django.contrib import admin

from fedow_dashboard import urls as dashboard_urls
from fedow_core.views import TransactionAPI, TestApiKey, HelloWorld, WalletAPI, PlaceAPI, FederationAPI, Onboard_stripe_return, \
    WebhookStripe, CheckoutStripeForChargePrimaryAsset, CardAPI, AssetAPI, get_new_place_token_for_test
# from django.conf import settings
from rest_framework import routers

router = routers.DefaultRouter()

router.register(r'helloworld_apikey', TestApiKey, basename='testapikey')
router.register(r'helloworld', HelloWorld, basename='testapikey')

router.register(r'transaction', TransactionAPI, basename='transaction')
router.register(r'place', PlaceAPI, basename='place')
router.register(r'federation', FederationAPI, basename='federation')
router.register(r'asset', AssetAPI, basename='asset')
router.register(r'wallet', WalletAPI, basename='wallet')
router.register(r'card', CardAPI, basename='card')


urlpatterns = [
    # Route pour test fedow :
    path('get_new_place_token_for_test/', get_new_place_token_for_test),

    # Requete depuis le cashless pour le retour de l'onboarding stripe
    path('onboard_stripe_return/', Onboard_stripe_return.as_view()),

    path('checkout_stripe_for_charge_primary_asset/', CheckoutStripeForChargePrimaryAsset.as_view()),
    path('webhook_stripe/', WebhookStripe.as_view()),

    path('admin/', admin.site.urls),
    path('', include(dashboard_urls)),
    path('', include(router.urls)),
]
