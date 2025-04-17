import logging
import typing
from datetime import datetime

import stripe
from django.http import HttpRequest
from rest_framework import permissions
from rest_framework.permissions import AllowAny
from rest_framework.views import PermissionDenied
from rest_framework_api_key.permissions import BaseHasAPIKey
from stripe.error import SignatureVerificationError

from fedow_core.models import OrganizationAPIKey, Configuration, CreatePlaceAPIKey, Wallet
from fedow_core.utils import verify_signature, data_to_b64

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

class CanCreatePlace(BaseHasAPIKey):
    model = CreatePlaceAPIKey

    def get_key(self, request: HttpRequest) -> typing.Optional[str]:
        return super().get_key(request)

    def has_permission(self, request: HttpRequest, view: typing.Any) -> bool:
        return super().has_permission(request, view)


class HasWalletSignature(permissions.BasePermission):
    # On récupère l'uuid dans le wallet et on vérifie la signature avec la clé publique qui est stockée
    def get_signature(self, request: HttpRequest) -> str | bool:
        signature = request.META.get("HTTP_SIGNATURE")
        return signature

    def get_wallet(self, request: HttpRequest) -> Wallet | None:
        wallet_uuid = request.headers.get("Wallet")
        if not wallet_uuid:
            # Header Wallet manquant
            return None
        try:
            wallet = Wallet.objects.get(uuid=wallet_uuid)
            return wallet
        except Wallet.DoesNotExist:
            # UUID non trouvé
            return None

    def get_date(self, request: HttpRequest) -> datetime | None:
        date_str = request.META.get("HTTP_DATE")
        if not date_str:
            return None
        date = datetime.fromisoformat(date_str)
        return date

    def has_permission(self, request: HttpRequest, view: typing.Any) -> bool:
        wallet = self.get_wallet(request)
        date = self.get_date(request)
        if not date or not wallet:
            raise PermissionDenied("Missing date or wallet")

        signature = self.get_signature(request)
        if not signature:
            raise PermissionDenied("Missing signature")
        wallet_public_key = wallet.public_key() if wallet else None

        # SIGNATURE ( GET / POST )
        # On signe la donnée si c'est du post.
        # Uniquement la clé si c'est du get.
        if request.method == 'POST':
            message = data_to_b64(request.data)
        elif request.method == 'GET':
            message = f"{wallet.uuid}:{date.isoformat()}".encode('utf8') if wallet else None
        else :
            raise PermissionDenied("Invalid method")

        if wallet and verify_signature(wallet_public_key, message, signature):
            request.wallet = wallet
            return True

        raise PermissionDenied("Invalid signature")


class HasPlaceKeyAndWalletSignature(BaseHasAPIKey):
    # Permission pour billetterie : Place Api key + wallet user signature
    model = OrganizationAPIKey

    def get_key(self, request: HttpRequest) -> typing.Optional[str]:
        return super().get_key(request)

    def get_signature(self, request: HttpRequest) -> str | bool:
        signature = request.META.get("HTTP_SIGNATURE")
        return signature

    def get_wallet(self, request: HttpRequest) -> Wallet | None:
        wallet_uuid = request.headers.get("Wallet")
        if not wallet_uuid:
            # Header Wallet manquant
            return None
        try:
            wallet = Wallet.objects.get(uuid=wallet_uuid)
            return wallet
        except Wallet.DoesNotExist:
            # UUID non trouvé
            return None

    def get_date(self, request: HttpRequest) -> datetime | None:
        date_str = request.META.get("HTTP_DATE")
        if not date_str:
            return None
        date = datetime.fromisoformat(date_str)
        return date

    def has_permission(self, request: HttpRequest, view: typing.Any) -> bool:
        # Récupération de la clé API qui va nous permettre de connaitre
        # le lieu et sa clé RSA publique pour vérifier la signature.
        key = self.get_key(request)
        if not key:
            logger.warning(f"HasKeyAndCashlessSignature : no key")
            return False

        try :
            api_key = self.model.objects.get_from_key(key)
            place = api_key.place
            request.place = place
        except Exception as e :
            logger.warning(f"HasPlaceKeyAndUserSignature : {e}")
            return False

        # On a la place, on va chercher le wallet

        wallet = self.get_wallet(request)
        date = self.get_date(request)
        if not date:
            return False  # Date manquante
        signature = self.get_signature(request)
        if not signature:
            return False  # Signature manquante
        wallet_public_key = wallet.public_key()

        # SIGNATURE ( GET / POST )
        # On signe la donnée si c'est du post.
        # Uniquement la clé si c'est du get.
        if request.method == 'POST':
            message = data_to_b64(request.data)
        elif request.method == 'GET':
            message = f"{wallet.uuid}:{date.isoformat()}".encode('utf8')
        else :
            return False

        if verify_signature(wallet_public_key, message, signature):
            request.wallet = wallet
            return True

        return False



class HasOrganizationAPIKeyOnly(BaseHasAPIKey):
    model = OrganizationAPIKey
    def get_key(self, request: HttpRequest) -> typing.Optional[str]:
        return super().get_key(request)

    def has_permission(self, request: HttpRequest, view: typing.Any) -> bool:
        # Récupération de la clé API qui va nous permettre de connaitre
        # le lieu et sa clé RSA publique pour vérifier la signature.
        key = self.get_key(request)
        if not key:
            logger.warning(f"HasKeyAndCashlessSignature : no key")
            return False

        try :
            api_key = self.model.objects.get_from_key(key)
            place = api_key.place
            request.place = place
            return True
        except Exception as e :
            logger.warning(f"HasPlaceKeyAndUserSignature : {e}")

        return False


class HasKeyAndPlaceSignature(BaseHasAPIKey):
    '''
    Méthode pour LaBoutik
    A besoin de la clé présente dans config.fedow_place_admin_apikey de LaBoutik
    et échangée lors du handshake de lancement du serveur LaBoutik
    '''
    model = OrganizationAPIKey

    def get_signature(self, request: HttpRequest) -> str | bool:
        signature = request.META.get("HTTP_SIGNATURE")
        return signature

    def get_key(self, request: HttpRequest) -> typing.Optional[str]:
        return super().get_key(request)

    def has_permission(self, request: HttpRequest, view: typing.Any) -> bool:
        # Récupération de la clé API qui va nous permettre de connaitre
        # le lieu et sa clé RSA publique pour vérifier la signature.
        key = self.get_key(request)
        if not key:
            logger.warning(f"HasKeyAndCashlessSignature : no key")
            return False

        try :
            api_key = self.model.objects.get_from_key(key)
            place = api_key.place
            request.place = place
            # On va chercher la clé publique du cashless
            cashless_public_key = place.cashless_public_key()
        except OrganizationAPIKey.DoesNotExist:
            logger.warning(f"HasKeyAndCashlessSignature : no api key")
            return False
        except Exception as e:
            # Pas de cashless_public_key ?
            logger.warning(f"HasKeyAndCashlessSignature : {e}")
            return False

        signature = self.get_signature(request)
        if not signature:
            logger.debug(f"HasKeyAndCashlessSignature : no signature")
            return False

        # SIGNATURE ( GET / POST )
        # On signe la donnée si c'est du post.
        # Uniquement la clé si c'est du get.
        if request.method == 'POST':
            message = data_to_b64(request.data)
        elif request.method == 'GET':
            message = key.encode('utf8')
        else :
            return False

        if cashless_public_key:
            if verify_signature(cashless_public_key, message, signature):
                return super().has_permission(request, view)

        logger.warning(f"HasKeyAndCashlessSignature : signature invalid")
        return False
