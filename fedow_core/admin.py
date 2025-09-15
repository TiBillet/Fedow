from django.contrib import admin
from django.core.cache import cache
from django.utils import timezone
from django.utils.html import mark_safe
from django.contrib.admin import SimpleListFilter
from zoneinfo import ZoneInfo

from fedow_core.models import Federation, Asset, Place, Wallet, Transaction
import logging

logger = logging.getLogger(__name__)


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
    readonly_fields = ['last_update', 'wallet_origin', 'category', 'total_token_value_display',
                       'total_in_place_display', 'total_in_wallet_not_place_display', 'total_bank_deposit_display',
                       'total_by_place_display']
    list_display = ['display_last_update', 'display_name', 'display_place_origin', 'display_type',
                    'display_total_market', 'display_total_in_place', 'display_total_in_wallet_not_place',
                    'display_total_bank_deposit']
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
            cache.set(cache_key, total, 5 * 60)  # Cache for 5 minutes

        return f"{total / 100:.2f}" if total else "0"

    def display_total_in_place(self, obj):
        cache_key = f'asset_total_in_place_{obj.uuid}'
        total = cache.get(cache_key)

        if total is None:
            total = obj.total_in_place()
            cache.set(cache_key, total, 5 * 60)  # Cache for 5 minutes

        return f"{total / 100:.2f}" if total else "0"

    def display_total_in_wallet_not_place(self, obj):
        cache_key = f'asset_total_in_wallet_not_place_{obj.uuid}'
        total = cache.get(cache_key)

        if total is None:
            total = obj.total_in_wallet_not_place()
            cache.set(cache_key, total, 5 * 60)  # Cache for 5 minutes

        return f"{total / 100:.2f}" if total else "0"

    def display_total_bank_deposit(self, obj):
        cache_key = f'asset_total_bank_deposit_{obj.uuid}'
        total = cache.get(cache_key)

        if total is None:
            total = obj.total_bank_deposit()
            cache.set(cache_key, total, 5 * 60)  # Cache for 5 minutes

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


class TimezoneFilter(SimpleListFilter):
    title = 'Timezone'
    parameter_name = 'timezone'

    def lookups(self, request, model_admin):
        return [
            ('UTC', 'UTC'),
            ('Europe/Paris', 'Europe/Paris'),
            ('Indian/Reunion', 'Indian/Reunion'),
        ]

    def queryset(self, request, queryset):
        # This filter does not alter the queryset; it just provides UI to choose display tz
        return queryset


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

    list_display = [
        "display_datetime",
        "wallet_sender",
        "wallet_receiver",
        "asset_name",
        "value",
        "card_number",
        "card_tagId",
        "card_place",
        "card_email",
        "action",
    ]

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
    list_filter = [
        "action",
        TimezoneFilter,
    ]

    def wallet_sender(self, obj):
        display_text = obj.sender.place.name if hasattr(obj.sender, 'place') else str(obj.sender.uuid)[:8]
        url = f"?q={obj.sender.uuid}"
        return mark_safe(f'<a href="{url}">{display_text}</a>')

    def wallet_receiver(self, obj):
        display_text = obj.receiver.place.name if hasattr(obj.receiver, 'place') else str(obj.receiver.uuid)[:8]
        url = f"?q={obj.receiver.uuid}"
        return mark_safe(f'<a href="{url}">{display_text}</a>')

    def asset_name(self, obj):
        display_text = obj.asset.name
        url = f"?q={obj.asset.uuid}"
        return mark_safe(f'<a href="{url}">{display_text}</a>')

    def card_number(self, obj):
        if obj.card:
            display_text = f"{obj.card.number_printed}"
            url = f"?q={obj.card.uuid}"
            return mark_safe(f'<a href="{url}">{display_text}</a>')
        return "-"

    def card_tagId(self, obj):
        if obj.card:
            display_text = f"{obj.card.first_tag_id}"
            url = f"?q={obj.card.uuid}"
            return mark_safe(f'<a href="{url}">{display_text}</a>')
        return "-"

    def card_place(self, obj):
        if obj.card:
            display_text = f"{obj.card.origin.place.name}"
            url = f"?q={obj.card.uuid}"
            return mark_safe(f'<a href="{url}">{display_text}</a>')
        return "-"

    def card_email(self, obj):
        if obj.card:
            if obj.card.user:
                display_text = f"{obj.card.user.email}"
                url = f"?q={obj.card.user.email}"
                return mark_safe(f'<a href="{url}">{display_text}</a>')
        return "-"

    def value(self, obj):
        return f"{obj.amount / 100:.2f}"

    def changelist_view(self, request, extra_context=None):
        # Store selected timezone for use in list_display rendering
        self._selected_tz = request.GET.get('timezone') or 'UTC'
        return super().changelist_view(request, extra_context=extra_context)

    def display_datetime(self, obj):
        tzname = getattr(self, '_selected_tz', 'UTC')
        try:
            tz = ZoneInfo(tzname)
        except Exception:
            tz = ZoneInfo('UTC')
        dt = obj.datetime
        # Ensure aware datetime
        if timezone.is_naive(dt):
            try:
                dt = timezone.make_aware(dt, timezone.utc)
            except Exception:
                dt = timezone.make_aware(dt)
        try:
            dt = dt.astimezone(tz)
        except Exception:
            pass
        return dt.strftime("%Y-%m-%d %H:%M:%S %Z")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
