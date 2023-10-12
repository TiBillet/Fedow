from decimal import Decimal

from django import template

register = template.Library()

@register.filter
def dround(value):
    # return 'prou'
    return Decimal(value/100).quantize(Decimal('1.00'))
