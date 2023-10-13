import base64
import json
import uuid
from collections import OrderedDict
import hashlib
import re
from datetime import datetime

from cryptography.hazmat.primitives.asymmetric import rsa
from django.utils import timezone
from rest_framework import serializers
from rest_framework.fields import empty
from rest_framework_api_key.models import APIKey
from fedow_core.models import Place, FedowUser, Card, Wallet, Transaction, OrganizationAPIKey, Asset, Token, \
    get_or_create_user, Origin, wallet_creator, asset_creator
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


class TokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = Token
        fields = (
            'uuid',
            'name',
            'value',
        )


class WalletSerializer(serializers.ModelSerializer):
    tokens = TokenSerializer(many=True)

    class Meta:
        model = Wallet
        fields = (
            'uuid',
            'tokens',
        )


class UserSerializer(serializers.ModelSerializer):
    wallet = WalletSerializer(many=False)

    class Meta:
        model = FedowUser
        fields = (
            'uuid',
            'wallet',
        )


class CheckCardSerializer(serializers.ModelSerializer):
    user = UserSerializer(many=False)

    class Meta:
        model = Card
        fields = (
            'first_tag_id',
            'user',
        )


class AssetCreateValidator(serializers.Serializer):
    uuid = serializers.UUIDField(required=False)
    name = serializers.CharField()
    currency_code = serializers.CharField(max_length=3)
    category = serializers.ChoiceField(choices=Asset.CATEGORIES)
    created_at = serializers.DateTimeField(required=False)

    def validate_name(self, value):
        if Asset.objects.filter(name=value).exists():
            raise serializers.ValidationError("Asset already exists")
        return value

    def validate_currency_code(self, value):
        if Asset.objects.filter(currency_code=value).exists():
            raise serializers.ValidationError("Currency code already exists")
        return value.upper()

    def validate(self, attrs):
        request = self.context.get('request')
        place = request.place

        asset_dict = {
            "name": attrs.get('name'),
            "currency_code": attrs.get('currency_code'),
            "category": attrs.get('category'),
            "origin": place.wallet,
            "ip": get_request_ip(request),
        }

        if attrs.get('uuid'):
            asset_dict["original_uuid"] = attrs.get('uuid')
        if attrs.get('created_at'):
            asset_dict["created_at"] = attrs.get('created_at')

        self.asset = asset_creator(**asset_dict)

        if self.asset:
            return attrs
        else:
            raise serializers.ValidationError("Asset creation failed")


class CardCreateValidator(serializers.Serializer):
    email = serializers.EmailField(required=False)
    generation = serializers.IntegerField()
    first_tag_id = serializers.CharField()
    complete_tag_id_uuid = serializers.UUIDField(required=False)
    qrcode_uuid = serializers.UUIDField()
    number_printed = serializers.CharField()
    tokens = serializers.ListField(required=False)

    def validate_first_tag_id(self, value):
        first_tag_regex = r"^[0-9a-fA-F]{8}\b"
        if not re.match(first_tag_regex, value):
            raise serializers.ValidationError("First tag id invalid")

        if Card.objects.filter(first_tag_id=value).exists():
            raise serializers.ValidationError("First tag id already used")
        return value

    def validate_number_printed(self, value):
        first_tag_regex = r"^[0-9a-fA-F]{8}\b"
        if not re.match(first_tag_regex, value):
            raise serializers.ValidationError("First tag id invalid")

        if Card.objects.filter(number_printed=value).exists():
            raise serializers.ValidationError("First tag id already used")
        return value

    def validate_email(self, value):
        self.user = None
        if value:
            self.user, created = get_or_create_user(value)
            return self.user.email
        return value

    def validate_generation(self, value):
        place = self.context.get('request').place
        if not place:
            raise serializers.ValidationError("Place not found")

        self.origin, created = Origin.objects.get_or_create(place=place, generation=value)
        return self.origin.generation

    def validate_tokens(self, value):
        # Retourne une liste avec les valeurs des futurs tokens
        # La création des tokens se fait dans le validateur global
        self.pre_tokens = []
        for token in value:
            try:
                asset_uuid = uuid.UUID(token['asset_uuid'])
                asset = Asset.objects.get(uuid=asset_uuid)

                # Seul la clé du serveur LaBoutik est autorisé à créer des tokens
                # sur l'asset de la carte
                place = self.context.get('request').place
                assert asset.origin == place.wallet, "Unauthorized"

                qty_cents = int(token['qty_cents'])
                last_date_used = datetime.fromisoformat(token['last_date_used'])

                self.pre_tokens.append({
                    "Asset": asset,
                    "qty_cents": qty_cents,
                    "last_date_used": last_date_used,
                })
            except Exception as e:
                # import ipdb; ipdb.set_trace()
                raise serializers.ValidationError(f"Assets error : {e}")
        return value

    def validate(self, attrs):
        # User est vide si pas d'email
        # Doit être remis à zéro pour chaque itération de many=True
        user = getattr(self, 'user', None) if attrs.get('email') else None

        # Création de la carte cashless
        self.card = Card.objects.create(
            first_tag_id=attrs.get('first_tag_id'),
            complete_tag_id_uuid=attrs.get('complete_tag_id_uuid'),

            qrcode_uuid=attrs.get('qrcode_uuid'),
            number_printed=attrs.get('number_printed'),

            user=user,
            origin=self.origin,
        )

        # Si le serveur LaBoutik envoie des valeurs d'assets
        # Alors le validate_asset à vérifié que les assets correspondent entre LaBoutik et Fedow
        # Il faut alors gérer la création monnétaire et le transfert sur le wallet de la carte et/ou de le user
        pre_tokens = self.pre_tokens if attrs.get('tokens', None) else None
        if pre_tokens:
            # import ipdb; ipdb.set_trace()
            for pre_token in pre_tokens:
                # Create token from scratch
                asset: Asset = pre_token['Asset']

                token_creation = Transaction.objects.create(
                    ip=get_request_ip(self.context.get('request')),
                    checkout_stripe=None,
                    sender=asset.origin,
                    receiver=asset.origin,
                    asset=asset,
                    amount=pre_token['qty_cents'],
                    action=Transaction.CREATION,
                    card=self.card,
                    primary_card=None,  # Création de monnaie
                )

                assert token_creation.verify_hash(), "Token creation hash is not valid"

                # virement vers le wallet de l'utilisateur
                virement = Transaction.objects.create(
                    ip=get_request_ip(self.context.get('request')),
                    checkout_stripe=None,
                    sender=asset.origin,
                    receiver=self.card.get_wallet(),
                    asset=asset,
                    amount=pre_token['qty_cents'],
                    action=Transaction.REFILL,
                    card=self.card,
                    primary_card=None,  # Création de monnaie
                )

                assert virement.verify_hash(), "Token creation hash is not valid"
        return attrs


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
            if self.card.user != self.user:
                raise serializers.ValidationError("Card already used")

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


class NewTransactionFromCardToPlaceValidator(serializers.Serializer):
    amount = serializers.IntegerField()
    asset = serializers.PrimaryKeyRelatedField(queryset=Asset.objects.all())
    primary_card = serializers.PrimaryKeyRelatedField(queryset=Card.objects.all())
    user_card = serializers.PrimaryKeyRelatedField(queryset=Card.objects.all())

    def validate_amount(self, value):
        # Positive amount only
        if value <= 0:
            raise serializers.ValidationError("Amount must be positive")
        return value

    def validate_user_primary_card(self, value):
        # Check if card is linked to user
        if not value.user:
            raise serializers.ValidationError("Card not linked to user")
        return value

    def validate_user_card(self, value):
        # Check if card is linked to user
        if not value.user:
            raise serializers.ValidationError("Card not linked to user")
        return value

    def validate(self, attrs):
        # Récupération de la place grâce a la permission HasKeyAndCashlessSignature
        request = self.context.get('request')
        place: Place = request.place
        receiver: Wallet = place.wallet
        card: Card = attrs.get('user_card')
        sender: Wallet = card.user.wallet

        # Si le lieu du wallet est dans la délégation d'autorité du wallet de la carte
        if not receiver in sender.get_authority_delegation(card=card):
            # Place must be in card user wallet authority delegation
            raise serializers.ValidationError("Unauthorized")

        self.receiver = receiver
        self.sender = sender

        return attrs


class NewTransactionWallet2WalletValidator(serializers.Serializer):
    amount = serializers.IntegerField()
    sender = serializers.PrimaryKeyRelatedField(queryset=Wallet.objects.all())
    receiver = serializers.PrimaryKeyRelatedField(queryset=Wallet.objects.all())
    asset = serializers.PrimaryKeyRelatedField(queryset=Asset.objects.all())

    # primary_card = serializers.PrimaryKeyRelatedField(queryset=Card.objects.all())
    # user_card = serializers.PrimaryKeyRelatedField(queryset=Card.objects.all())

    def validate_amount(self, value):
        # Positive amount only
        if value <= 0:
            raise serializers.ValidationError("Amount must be positive")
        return value

    def validate(self, attrs):
        # Récupération de la place grâce a la permission HasKeyAndCashlessSignature
        request = self.context.get('request')
        place: Place = request.place

        if not place.wallet == self.sender and not place.wallet == self.receiver:
            # Place must be sender or receiver
            logger.error(f"{timezone.localtime()} ERROR sender nor receiver are Unauthorized - {request}")
            raise serializers.ValidationError("Unauthorized")

        try:
            self.token_sender = Token.objects.get(wallet=attrs.get('sender'), asset=attrs.get('asset'))
        except Token.DoesNotExist:
            raise serializers.ValidationError("Sender token does not exist")

        try:
            self.token_receiver = Token.objects.get(wallet=attrs.get('receiver'), asset=attrs.get('asset'))
        except Token.DoesNotExist:
            raise serializers.ValidationError("Receiver token does not exist")

        if self.token_sender.value < attrs.get('amount'):
            logger.error(f"{timezone.localtime()} ERROR sender not enough value - {request}")
            raise serializers.ValidationError("Sender not enough value")

        # TODO: Checker les clé rsa des wallets
        raise serializers.ValidationError("TODO: Checker les signatures des wallets")
        # return attrs

    # def get_attribute(self, instance):
    #     attribute = super().get_attribute(instance)
    #     return attribute


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
