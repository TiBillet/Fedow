from django.contrib import admin

from fedow_core.models import Federation, Asset, Place, Wallet


# Register your models here.
@admin.register(Federation)
class FederationAdmin(admin.ModelAdmin):
    pass

@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    pass

@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    fields = [
        'name',
        'currency_code',
        'category',
        'archive',
        'last_update',
        'img',
        'wallet_origin',
    ]
    readonly_fields = ['last_update', ]

# Register your models here.
@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    fields = [
        "name",
        "is_primary",
        "is_place",
    ]
    readonly_fields = fields
