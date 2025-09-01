from django.contrib import admin
from django.core.cache import cache
from django.utils.html import mark_safe

from fedow_core.models import Federation, Asset, Place, Wallet, Transaction


# Register your models here.
@admin.register(Federation)
class FederationAdmin(admin.ModelAdmin):
    pass

@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    readonly_fields = [
        'wallet',
    ]

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    fields = [
        'name',
        'category',
        'archive',
        'last_update',
        'img',
        'wallet_origin',
        'total_token_value_display',
        'total_in_place_display',
        'total_in_wallet_not_place_display',
        'total_bank_deposit_display',
        'total_by_place_display',
    ]
    readonly_fields = ['last_update', 'wallet_origin', 'category', 'total_token_value_display', 'total_in_place_display', 'total_in_wallet_not_place_display', 'total_bank_deposit_display', 'total_by_place_display']
    list_display = ['display_last_update', 'display_name', 'display_place_origin', 'display_type', 'display_total_market', 'display_total_in_place', 'display_total_in_wallet_not_place', 'display_total_bank_deposit']
    ordering = ['-last_update']

    def display_place_origin(self, obj):
        place = obj.place_origin()
        if place:
            return place.name
        return "-"

    def display_type(self, obj):
        return obj.get_category_display()

    def display_total_market(self, obj):
        cache_key = f'asset_total_market_{obj.uuid}'
        total = cache.get(cache_key)

        if total is None:
            total = obj.total_token_value()
            cache.set(cache_key, total, 5*60)  # Cache for 5 minutes

        return f"{total / 100:.2f}" if total else "0"

    def display_total_in_place(self, obj):
        cache_key = f'asset_total_in_place_{obj.uuid}'
        total = cache.get(cache_key)

        if total is None:
            total = obj.total_in_place()
            cache.set(cache_key, total, 5*60)  # Cache for 5 minutes

        return f"{total / 100:.2f}" if total else "0"

    def display_total_in_wallet_not_place(self, obj):
        cache_key = f'asset_total_in_wallet_not_place_{obj.uuid}'
        total = cache.get(cache_key)

        if total is None:
            total = obj.total_in_wallet_not_place()
            cache.set(cache_key, total, 5*60)  # Cache for 5 minutes

        return f"{total / 100:.2f}" if total else "0"

    def display_total_bank_deposit(self, obj):
        cache_key = f'asset_total_bank_deposit_{obj.uuid}'
        total = cache.get(cache_key)

        if total is None:
            total = obj.total_bank_deposit()
            cache.set(cache_key, total, 5*60)  # Cache for 5 minutes

        return f"{total / 100:.2f}" if total else "0"

    def display_name(self, obj):
        display_text = obj.name
        url = f"/admin/fedow_core/asset/{obj.uuid}/change/"
        return mark_safe(f'<a href="{url}">{display_text}</a>')

    def display_last_update(self, obj):
        return obj.last_update.strftime("%Y-%m-%d %H:%M:%S")

    display_place_origin.short_description = 'Place origine'
    display_type.short_description = 'Type'
    display_total_market.short_description = 'Total market'
    display_total_in_place.short_description = 'Total in place'
    display_total_in_wallet_not_place.short_description = 'Total in wallet (not place)'
    display_total_bank_deposit.short_description = 'Total bank deposit'
    display_last_update.short_description = 'Dernière mise à jour'
    display_last_update.admin_order_field = 'last_update'
    display_name.short_description = 'Nom'

    def total_token_value_display(self, obj):
        total = obj.total_token_value()
        return f"{total / 100:.2f} €" if total else "0.00 €"

    def total_in_place_display(self, obj):
        total = obj.total_in_place()
        return f"{total / 100:.2f} €" if total else "0.00 €"

    def total_in_wallet_not_place_display(self, obj):
        total = obj.total_in_wallet_not_place()
        return f"{total / 100:.2f} €" if total else "0.00 €"

    def total_bank_deposit_display(self, obj):
        total = obj.total_bank_deposit()
        return f"{total / 100:.2f} €" if total else "0.00 €"

    def total_by_place_display(self, obj):
        place_totals = obj.total_by_place()
        if not place_totals:
            return "No tokens in any place wallet"

        html = '<table style="width:100%; border-collapse: collapse;">'
        html += '<tr><th style="text-align:left; padding:5px; border-bottom:1px solid #ddd;">Place</th>'
        html += '<th style="text-align:right; padding:5px; border-bottom:1px solid #ddd;">Amount</th></tr>'

        for place_name, value in sorted(place_totals.items()):
            formatted_value = f"{value / 100:.2f} €"
            html += f'<tr><td style="padding:5px; border-bottom:1px solid #eee;">{place_name}</td>'
            html += f'<td style="text-align:right; padding:5px; border-bottom:1px solid #eee;">{formatted_value}</td></tr>'

        html += '</table>'
        return mark_safe(html)

    total_token_value_display.short_description = 'Total market value'
    total_in_place_display.short_description = 'Total in place'
    total_in_wallet_not_place_display.short_description = 'Total in wallet (not place)'
    total_bank_deposit_display.short_description = 'Total bank deposit'
    total_by_place_display.short_description = 'Total by place'

    def has_delete_permission(self, request, obj=None):
        return False

# Register your models here.
@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    fields = [
        "name",
        "is_primary",
        "is_place",
    ]
    readonly_fields = fields

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    fields = [
        "uuid",
        "hash",
        "ip",
        "checkout_stripe",
        "sender",
        "receiver",
        "asset",
        "card",
        "primary_card",
        "previous_transaction",
        "datetime",
        "amount",
        "comment",
        "metadata",
        "subscription_type",
        "subscription_first_datetime",
        "subscription_start_datetime",
        "last_check",
        "action",
    ]
    readonly_fields = fields
    list_display = ["display_datetime", "display_sender", "display_receiver", "display_asset_name", "display_amount", "display_card_info", "action"]
    search_fields = [
        "asset__name",
        "sender__place__name",
        "receiver__place__name",
        "sender__name",
        "sender__uuid",
        "receiver__name",
        "receiver__uuid",
        "card__user__email",
        "card__uuid",
        "card__first_tag_id",
        "card__qrcode_uuid",
        "card__number_printed",
    ]
    list_filter = ["asset", "action", "sender__place", "receiver__place"]

    def display_sender(self, obj):
        display_text = obj.sender.place.name if hasattr(obj.sender, 'place') else str(obj.sender.uuid)[:8]
        url = f"?sender__uuid__exact={obj.sender.uuid}"
        return mark_safe(f'<a href="{url}">{display_text}</a>')

    def display_receiver(self, obj):
        display_text = obj.receiver.place.name if hasattr(obj.receiver, 'place') else str(obj.receiver.uuid)[:8]
        url = f"?receiver__uuid__exact={obj.receiver.uuid}"
        return mark_safe(f'<a href="{url}">{display_text}</a>')

    def display_asset_name(self, obj):
        display_text = obj.asset.name
        url = f"?asset__uuid__exact={obj.asset.uuid}"
        return mark_safe(f'<a href="{url}">{display_text}</a>')

    def display_card_info(self, obj):
        if obj.card:
            display_text = f"{obj.card.number_printed} {obj.card.origin.place.name}"
            url = f"?card__uuid__exact={obj.card.uuid}"
            return mark_safe(f'<a href="{url}">{display_text}</a>')
        return "-"

    def display_amount(self, obj):
        return f"{obj.amount / 100:.2f}"

    def display_datetime(self, obj):
        return obj.datetime.strftime("%Y-%m-%d %H:%M:%S")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
