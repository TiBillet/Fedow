import base64
import json
from collections import OrderedDict
import hashlib
from cryptography.hazmat.primitives.asymmetric import rsa
from django.utils import timezone
from rest_framework import serializers
from rest_framework_api_key.models import APIKey
from fedow_core.models import Place, FedowUser, Card, Wallet, Transaction, OrganizationAPIKey, Asset, Token, \
    get_or_create_user
from fedow_core.utils import get_request_ip, get_public_key, dict_to_b64, verify_signature, rsa_generator
import logging

logger = logging.getLogger(__name__)


class HandshakeValidator(serializers.Serializer):
    # Temp fedow place APIkey inside the request header
    fedow_place_uuid = serializers.PrimaryKeyRelatedField(queryset=Place.objects.all())
    cashless_rsa_pub_key = serializers.CharField(max_length=512)
    cashless_ip = serializers.IPAddressField()
    cashless_url = serializers.URLField()
    cashless_admin_apikey = serializers.CharField(max_length=41, min_length=41)

    def validate_fedow_place_uuid(self, value) -> Place:
        # TODO: Si place à déja été configuré, on renvoie un 400
        # if place.cashless_server_ip or place.cashless_server_url or place.cashless_server_key:
        #     logger.error(f"{timezone.localtime()} Place already configured {self.context.get('request').data}")
        #     raise serializers.ValidationError("Place already configured")

        return value

    def validate_cashless_rsa_pub_key(self, value) -> rsa.RSAPublicKey:
        # Valide uniquement le format avec la biblothèque cryptography
        self.pub_key = get_public_key(value)
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
        signed_message = dict_to_b64(request.data)
        signature = request.META.get('HTTP_SIGNATURE')
        if not verify_signature(public_key, signed_message, signature):
            logger.error(f"{timezone.localtime()} ERROR HANDSHAKE Invalid signature - {request.data}")
            raise serializers.ValidationError("Invalid signature")

        # Check if key is the temp given by the manual creation.
        # and if the user associated is admin of the place
        key = request.META["HTTP_AUTHORIZATION"].split()[1]
        api_key = OrganizationAPIKey.objects.get_from_key(key)
        user = api_key.user

        place: Place = attrs.get('fedow_place_uuid')
        if user not in place.admins.all() and place != api_key.place:
            logger.error(f"{timezone.localtime()} ERROR HANDSHAKE user not in place admins - {request.data}")
            raise serializers.ValidationError("Unauthorized")

        if 'temp_' not in api_key.name:
            logger.error(f"{timezone.localtime()} ERROR ApiKey not temp_ : {request.data}")
            raise serializers.ValidationError("Unauthorized")

        return attrs

    # def to_representation(self, instance):
    #     # Add apikey user to representation
    #     representation = super().to_representation(instance)
    #     representation['user'] = self.user
    #     return representation


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
        ip = None
        request = self.context.get('request')
        if request:
            ip = get_request_ip(request)
        self.user, created = get_or_create_user(value, ip=ip)
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
        # Link card to user
        self.card.user = self.user
        self.card.save()

        return attrs

    def to_representation(self, instance):
        # Add apikey user to representation
        representation = super().to_representation(instance)
        representation['wallet'] = f"{self.user.wallet.uuid}"
        return representation


class NewTransactionValidator(serializers.Serializer):
    amount = serializers.IntegerField()
    sender = serializers.PrimaryKeyRelatedField(queryset=Wallet.objects.all())
    receiver = serializers.PrimaryKeyRelatedField(queryset=Wallet.objects.all())
    asset = serializers.PrimaryKeyRelatedField(queryset=Asset.objects.all())

    def validate_amount(self, value):
        # Positive amount only
        if value <= 0:
            raise serializers.ValidationError("Amount must be positive")
        return value

    def is_place_wallet(self) -> bool:
        # Place from key are one of the two wallets ?
        key = self.context['request'].META["HTTP_AUTHORIZATION"].split()[1]
        api_key = OrganizationAPIKey.objects.get_from_key(key)
        place: Place = api_key.place
        return place.wallet == self.sender or place.wallet == self.receiver

    def create_hash(self):
        encoded_block = json.dumps(self.__dict__, sort_keys=True).encode()
        return hashlib.sha256(encoded_block).hexdigest()

    def validate(self, attrs):
        request = self.context.get('request')
        if not self.is_place_wallet:
            logger.error(f"{timezone.localtime()} ERROR sender nor receiver are Unauthorized - {request}")
            raise serializers.ValidationError("Unauthorized")

        try:
            token_sender = Token.objects.get(wallet=attrs.get('sender'), asset=attrs.get('asset'))
        except Token.DoesNotExist:
            raise serializers.ValidationError("Sender token does not exist")

        if token_sender.value < attrs.get('amount'):
            logger.error(f"{timezone.localtime()} ERROR sender not enough value - {request}")
            raise serializers.ValidationError("Sender not enough value")

        return attrs

    def get_attribute(self, instance):
        attribute = super().get_attribute(instance)
        attribute['hash'] = self.create_hash()
        return attribute


class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = (
            "uuid",
            "sender",
            "receiver",
            "date",
            "amount",
            "comment",
        )
