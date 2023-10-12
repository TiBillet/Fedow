from django.shortcuts import render

from fedow_core.models import Asset, Place, Wallet, Card


# Create your views here.


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