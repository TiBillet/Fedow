import typing

from django.http import HttpRequest
from rest_framework_api_key.models import APIKey
from rest_framework_api_key.permissions import BaseHasAPIKey

from fedow_core.models import Wallet, OrganizationAPIKey
from fedow_core.utils import verify_signature, dict_to_b64


class HasAPIKey(BaseHasAPIKey):
    model = OrganizationAPIKey

class HasKeyAndSignedData(BaseHasAPIKey):
    model = OrganizationAPIKey
    def get_signature(self, request: HttpRequest) -> str | bool:
        signature = request.META.get("HTTP_SIGNATURE")
        return signature

    def get_wallet(self, request: HttpRequest) -> str | bool:
        wallet = request.POST.get("sender")
        return wallet

    def get_key(self, request: HttpRequest) -> typing.Optional[str]:
        return super().get_key(request)

    def has_permission(self, request: HttpRequest, view: typing.Any) -> bool:
        key = self.get_key(request)
        signature = self.get_signature(request)
        wallet = self.get_wallet(request)

        if signature and wallet and key:
            message = dict_to_b64(request.data)
            public_key = Wallet.objects.get(pk=wallet).public_key()
            if verify_signature(public_key, message, signature):
               return super().has_permission(request, view)
        return False
