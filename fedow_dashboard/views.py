from django.shortcuts import render, get_object_or_404
from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from django.views.decorators.cache import cache_page

from fedow_core.models import Asset, Place, Wallet, Card, Federation, Configuration, Transaction
import logging

logger = logging.getLogger(__name__)


def badgeuse_view(request, pk):
    asset = get_object_or_404(Asset, pk=pk)

    # Tout les actions de badgeuse sont des articles vendus avec la methode BADGEUSE
    ligne_badgeuse = asset.transactions.filter(
        action=Transaction.BADGE).order_by('card', 'datetime')

    dict_carte_passage = {}
    for ligne in ligne_badgeuse:
        ligne: Transaction
        if ligne.card not in dict_carte_passage:
            dict_carte_passage[ligne.card] = []
        dict_carte_passage[ligne.card].append(ligne)

    passages = []
    for carte, transactions in dict_carte_passage.items():
        horaires = [transaction.datetime for transaction in transactions]
        horaires_sorted = sorted(horaires)
        if len(horaires_sorted) % 2 != 0:
            horaires_sorted.append(None)

        couples_de_passage = list(zip(horaires_sorted[::2], horaires_sorted[1::2]))
        for horaires in couples_de_passage :
            # On veut la transaction qui correspond au premier horaire du couple de passage
            index = couples_de_passage.index(horaires) * 2 # il y a deux fois plus de transaction que de couple horaire
            passages.append({carte: {
                'horaires': horaires,
                'transaction': transactions[index],
            }
            })

    context = {
        'passages': passages,
    }

    return render(request, 'asset/badgeuse.html', context=context)


def asset_view(request, pk):
    asset = get_object_or_404(Asset, pk=pk)
    if asset.category == Asset.BADGE:
        return badgeuse_view(request, pk)

    context = {
        'asset': asset,
        # seulement les 50 dernières transactions :
        'transactions': asset.transactions.all().order_by('-datetime')[:50],
    }
    if asset.category == Asset.SUBSCRIPTION:
        return render(request, 'asset/asset_transactions_membership.html', context=context)
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


# @cache_page(60 * 15)
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
