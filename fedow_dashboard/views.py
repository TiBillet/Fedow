from django.shortcuts import render
from rest_framework import viewsets
from rest_framework.permissions import AllowAny

from fedow_core.models import Asset, Place, Wallet, Card


# Create your views here.
class PlaceAPI(viewsets.ViewSet):
    def retrieve(self, request, pk=None):
        place = Place.objects.get(pk=pk)
        accepted_assets = place.accepted_assets()
        place_federated_with = place.federated_with()

        context = {
            'assets': accepted_assets,
            'places': place_federated_with,
            'wallets': Wallet.objects.all(),
            'cards': Card.objects.all(),
        }
        return render(request, 'place/place.html', context=context)

    def get_permissions(self):
        permission_classes = [AllowAny]
        return [permission() for permission in permission_classes]

def index(request):
    """
    Livre un template HTML
    """
    context = {
        'assets': Asset.objects.all(),
        'places': Place.objects.all(),
        'wallets': Wallet.objects.all(),
        'cards': Card.objects.all(),
    }
    return render(request, 'index/index.html', context=context)