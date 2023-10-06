from django.shortcuts import render

from fedow_core.models import Asset, Place


# Create your views here.


def index(request):
    """
    Livre un template HTML
    """
    context = {
        'assets': Asset.objects.all(),
        'places': Place.objects.all(),
    }
    return render(request, 'index/index.html', context=context)