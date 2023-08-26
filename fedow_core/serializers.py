import base64
from collections import OrderedDict

from cryptography.hazmat.primitives.asymmetric import rsa
from django.utils import timezone
from rest_framework import serializers
from rest_framework_api_key.models import APIKey
from fedow_core.models import Place, FedowUser, Card, Wallet, Transaction
from fedow_core.utils import get_request_ip, validate_format_rsa_pub_key, dict_to_b64, verify_signature
import logging

logger = logging.getLogger(__name__)


def get_or_create_fedowuser(email):
    try:
        user = FedowUser.objects.get(email=email.lower())
        created = False
    except FedowUser.DoesNotExist:
        user = FedowUser.objects.create(
            email=email.lower()
        )
        created = True
    return user, created


class HandshakeValidator(serializers.Serializer):
    # Temp fedow place APIkey inside the request header
    fedow_place_uuid = serializers.PrimaryKeyRelatedField(queryset=Place.objects.all())
    cashless_rsa_pub_key = serializers.CharField(max_length=512)
    cashless_ip = serializers.IPAddressField()
    cashless_url = serializers.URLField()
    cashless_admin_apikey = serializers.CharField(max_length=41, min_length=41)

    def validate_fedow_place_uuid(self, value) -> Place:
        #TODO: Si place à déja été configuré, on renvoie un 400
        # if place.cashless_server_ip or place.cashless_server_url or place.cashless_server_key:
        #     logger.error(f"{timezone.localtime()} Place already configured {self.context.get('request').data}")
        #     raise serializers.ValidationError("Place already configured")

        return value

    def validate_cashless_rsa_pub_key(self, value) -> rsa.RSAPublicKey:
        # Valide uniquement le format avec la biblothèque cryptography
        self.pub_key = validate_format_rsa_pub_key(value)
        if not self.pub_key:
            logger.error(f"{timezone.localtime()} Public rsa key invalid")
            raise serializers.ValidationError("Public rsa key invalid")

        # Public key, but not paired with signature (see validate)
        return value


    def validate_cashless_ip(self, value):
        request = self.context.get('request')
        if value != get_request_ip(request):
            logger.error(f"{timezone.localtime()} ERROR Place create Invalid IP {get_request_ip(request)}")
            raise serializers.ValidationError("Invalid IP")
        return value

    def validate(self, attrs: OrderedDict) -> OrderedDict:
        request = self.context.get('request')
        public_key = self.pub_key
        signed_message = dict_to_b64(request.data.dict())
        signature = request.META.get('HTTP_SIGNATURE')
        if not verify_signature(public_key, signed_message, signature):
            logger.error(f"{timezone.localtime()} ERROR HANDSHAKE Invalid signature - {request.data}")
            raise serializers.ValidationError("Invalid signature")

        # Check if key is the temp given by the manual creation.
        # and if the user associated is admin of the place
        key = request.META["HTTP_AUTHORIZATION"].split()[1]
        api_key = APIKey.objects.get_from_key(key)

        # ApiKey is an admin user key ?
        user: FedowUser | None = getattr(api_key, 'fedow_user', None)
        if not user :
            logger.error(f"{timezone.localtime()} ERROR HANDSHAKE no user associated with api key - {request.data}")
            raise serializers.ValidationError("Unauthorized")
        self.user = user

        place: Place = attrs.get('fedow_place_uuid')
        if user not in place.admins.all():
            logger.error(f"{timezone.localtime()} ERROR HANDSHAKE user not in place admins - {request.data}")
            raise serializers.ValidationError("Unauthorized")

        if 'temp_' not in api_key.name:
            logger.error(f"{timezone.localtime()} ERROR ApiKey not temp_ : {request.data}")
            raise serializers.ValidationError("Unauthorized")

        # On ajoute l'user à
        return attrs

    def to_representation(self, instance):
        # Add apikey user to representation
        representation = super().to_representation(instance)
        representation['user'] = self.user
        return representation



class PlaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Place
        fields = (
            'uuid',
            'name',
        )

    def validate(self, attrs):
        return attrs


class WalletCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    uuid_card = serializers.UUIDField()

    def validate_email(self, value):
        self.user, created = get_or_create_fedowuser(email=value)
        if not created:
            raise serializers.ValidationError("User already exists")

        return self.user.email

    def validate_uuid_card(self, value):
        try:
            self.card = Card.objects.get(uuid=value)
        except Card.DoesNotExist:
            raise serializers.ValidationError("Card does not exist")

        if self.card.user:
            raise serializers.ValidationError("Card not available")

        return self.card.uuid

    def validate(self, attrs):
        # Get ip
        ip = get_request_ip(self.context.get('request'))

        # Link card to user
        self.card.user = self.user
        self.card.save()

        # Api key generation
        api_key, self.key = APIKey.objects.create_key(name=self.user.email[:50])

        # Create wallet
        self.wallet = Wallet.objects.create(
            key=api_key,
            ip=ip,
            user=self.user
        )

        return attrs


class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = (
            "uuid",
            "sender",
            "receiver",
            "token",
            "date",
            "amount",
            "comment",
        )
