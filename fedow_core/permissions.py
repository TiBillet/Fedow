import json
import os
import typing
from datetime import datetime

from django.http import HttpRequest
from rest_framework.permissions import AllowAny
from rest_framework_api_key.models import APIKey
from rest_framework_api_key.permissions import BaseHasAPIKey
from stripe.error import SignatureVerificationError

from fedow_core.models import Wallet, OrganizationAPIKey, Configuration
from fedow_core.utils import verify_signature, dict_to_b64
import stripe
import logging

logger = logging.getLogger(__name__)


class IsStripe(AllowAny):
    def valid_signature(self, request: HttpRequest) -> str | bool:
        start = datetime.now()
        # stripe.api_key = config.get_stripe_api()
        stripe_endpoint_secret = Configuration.get_solo().get_stripe_endpoint_secret()
        signature = request.headers.get('stripe-signature')
        signed_payload = request.body.decode('utf-8')

        # if request.data.get('type') == "checkout.session.completed":
        #     import ipdb; ipdb.set_trace()
        # checkout_session_id_stripe=request.data['data']['object']['id']
        # checkout_session = stripe.checkout.Session.retrieve(checkout_session_id_stripe)

        try:
            signed_stripe_event = stripe.Webhook.construct_event(
                signed_payload, signature, stripe_endpoint_secret
            )
            request.signed_payload = True
            request.signed_stripe_event = signed_stripe_event
            logger.debug(f"Stripe webhook valid_signature : {datetime.now() - start}")
            return True
        except SignatureVerificationError as e:
            logger.error(f"Stripe webhook SignatureVerificationError : {e}")
        except Exception as e:
            logger.error(f"Stripe webhook valid_signature error : {e}")
        return False

    def has_permission(self, request, view):
        return self.valid_signature(request)


class HasAPIKey(BaseHasAPIKey):
    model = OrganizationAPIKey


class HasKeyAndCashlessSignature(BaseHasAPIKey):
    model = OrganizationAPIKey

    def get_signature(self, request: HttpRequest) -> str | bool:
        signature = request.META.get("HTTP_SIGNATURE")
        return signature

    # def get_wallet(self, request: HttpRequest) -> str | bool:
    #     wallet = request.POST.get("sender")
    #     return wallet

    def get_key(self, request: HttpRequest) -> typing.Optional[str]:
        return super().get_key(request)

    def has_permission(self, request: HttpRequest, view: typing.Any) -> bool:
        key = self.get_key(request)
        if key:
            api_key = self.model.objects.get_from_key(key)
            signature = self.get_signature(request)

            if signature and api_key:
                message = dict_to_b64(request.data)
                cashless_public_key = api_key.place.cashless_public_key()
                if cashless_public_key:
                    if verify_signature(cashless_public_key, message, signature):
                        request.place = api_key.place
                        return super().has_permission(request, view)
        return False
