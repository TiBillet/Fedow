from django.shortcuts import render, get_object_or_404
from rest_framework import viewsets
from rest_framework.permissions import AllowAny

from fedow_core.models import Asset, Place, Wallet, Card, Federation


# Create your views here.
class PlaceAPI(viewsets.ViewSet):
    def retrieve(self, request, pk=None):
        place = get_object_or_404(Place, pk=pk)
        accepted_assets = place.accepted_assets()
        place_federated_with = place.federated_with()

        context = {
            'assets': accepted_assets,
            'federations': place.federations.all(),
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
        'federations': Federation.objects.all(),
        'assets': Asset.objects.all(),
        'places': Place.objects.all(),
        'wallets': Wallet.objects.all(),
        'cards': Card.objects.all(),
    }
    return render(request, 'index/index.html', context=context)