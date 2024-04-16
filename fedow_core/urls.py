from django.urls import path, include
from django.contrib import admin

from fedow_dashboard import urls as dashboard_urls
from fedow_core.views import TransactionAPI, TestApiKey, HelloWorld, WalletAPI, PlaceAPI, FederationAPI, \
    Onboard_stripe_return, \
    WebhookStripe, CardAPI, AssetAPI, get_new_place_token_for_test, \
    root_tibillet_handshake, StripeAPI
# from django.conf import settings
from rest_framework import routers

router = routers.DefaultRouter()

router.register(r'helloworld_apikey', TestApiKey, basename='testapikey')
router.register(r'helloworld', HelloWorld, basename='helloworld')

router.register(r'transaction', TransactionAPI, basename='transaction')
router.register(r'place', PlaceAPI, basename='place')
router.register(r'federation', FederationAPI, basename='federation')
router.register(r'asset', AssetAPI, basename='asset')
router.register(r'wallet', WalletAPI, basename='wallet')
router.register(r'card', CardAPI, basename='card')
router.register(r'stripe', StripeAPI, basename='stripe')

urlpatterns = [
    # Route pour test fedow :
    path('get_new_place_token_for_test/<str:name_enc>/', get_new_place_token_for_test),
    path('root_tibillet_handshake/', root_tibillet_handshake),

    # Requete depuis le cashless pour le retour de l'onboarding stripe
    # TODO, a mettre dans StripeAPI
    path('onboard_stripe_return/', Onboard_stripe_return.as_view()),
    # Retour POST de stripe :
    # TODO, a mettre dans StripeAPI
    path('webhook_stripe/', WebhookStripe.as_view()),

    path('admin/', admin.site.urls),
    path('dashboard/', include(dashboard_urls)),
    path('', include(router.urls)),
]
