from decimal import Decimal

from django import template

from fedow_core.models import Asset

register = template.Library()

@register.filter
def dround(value):
    # return 'prou'
    return Decimal(value/100).quantize(Decimal('1.00'))


@register.filter
def unite_asset(asset):
    """
    Renvoie le libelle d'unite a afficher pour un asset.
    / Returns the unit label to display for an asset.

    Fidelite -> "pts". Sinon (fiduciaire, monnaie temps "H"...) -> code devise.
    / Fidelity -> "pts". Otherwise (fiat, time currency "H"...) -> currency code.
    """
    if asset.category == Asset.FIDELITY:
        return "pts"
    return (asset.currency_code or "").upper()
