from django.shortcuts import render, get_object_or_404
from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from django.views.decorators.cache import cache_page

from fedow_core.models import Asset, Place, Wallet, Card, Federation
import logging

logger = logging.getLogger(__name__)


def asset_view(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    context = {
        'asset': asset,
        # seulement les 50 dernières transactions :
        'transactions': asset.transactions.all().order_by('-datetime')[:50],
    }
    return render(request, 'asset/asset_transactions.html', context=context)


# Create your views here.
def place_view(request, pk):
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




@cache_page(60 * 15)
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
    logger.info(f"Index page rendered")
    return render(request, 'index/index.html', context=context)