import uuid, re
from collections import OrderedDict
from datetime import datetime
from django.utils import timezone
from rest_framework import serializers
from fedow_core.models import Place, FedowUser, Card, Wallet, Transaction, OrganizationAPIKey, Asset, Token, \
    get_or_create_user, Origin, asset_creator, Configuration
from fedow_core.utils import get_request_ip, get_public_key, dict_to_b64, verify_signature
from cryptography.hazmat.primitives.asymmetric import rsa
import stripe
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


class OnboardSerializer(serializers.Serializer):
    id_acc_connect = serializers.CharField(max_length=21)
    fedow_place_uuid = serializers.PrimaryKeyRelatedField(queryset=Place.objects.all())

    def validate_id_acc_connect(self, value):
        config = Configuration.get_solo()
        stripe.api_key = config.get_stripe_api()
        self.info_stripe = None
        try:
            info_stripe = stripe.Account.retrieve(value)
            self.info_stripe = info_stripe
        except Exception as exc:
            logger.error(f"Stripe Account.retrieve : {exc}")
            raise serializers.ValidationError("Stripe error")
        if not info_stripe:
            raise serializers.ValidationError("id_acc_connect not a stripe account")
        return value

    def validate_fedow_place_uuid(self, value):
        place: Place = self.context.get('request').place
        if place != value:
            raise serializers.ValidationError("Place not match")
        return value


class TokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = Token
        fields = (
            'uuid',
            'asset',
            'asset_name',
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


class CardCreateValidator(serializers.ModelSerializer):
    generation = serializers.IntegerField(required=True)
    is_primary = serializers.BooleanField(required=True)

    def validate_generation(self, value):
        place = self.context.get('request').place
        if not place:
            raise serializers.ValidationError("Place not found")

        if not getattr(self, 'origin', None):
            self.origin, created = Origin.objects.get_or_create(place=place, generation=value)

        if self.origin.generation != value:
            raise serializers.ValidationError("One generation per request")

        return value

    def create(self, validated_data):
        is_primary = validated_data.pop('is_primary', False)
        validated_data.pop('generation')
        validated_data['origin'] = self.origin

        card = Card.objects.create(**validated_data)
        if is_primary:
            self.origin.place.primary_cards.add(card)
        return card

    class Meta:
        model = Card
        fields = (
            'uuid',
            'first_tag_id',
            'complete_tag_id_uuid',
            'qrcode_uuid',
            'number_printed',
            'generation',
            'is_primary',
        )


class AssetSerializer(serializers.ModelSerializer):
    class Meta:
        model = Asset
        fields = (
            'uuid',
            'name',
            'currency_code',
            'category',
            'origin',
            'created_at',
            'last_update',
            'is_stripe_primary',
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


class PlaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Place
        fields = (
            'uuid',
            'name',
        )

    def validate(self, attrs):
        return attrs


class OriginSerializer(serializers.ModelSerializer):
    place = serializers.SlugField(source='place.name')

    class Meta:
        model = Origin
        fields = (
            'place',
            'generation',
            'img',
        )


class WalletCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()

    card_first_tag_id = serializers.SlugRelatedField(slug_field='first_tag_id',
                                                     queryset=Card.objects.all(), required=False)
    card_qrcode_uuid = serializers.SlugRelatedField(slug_field='qrcode_uuid',
                                                    queryset=Card.objects.all(), required=False)

    def validate(self, attrs):
        # On trace l'ip de la requete
        ip = None
        request = self.context.get('request')
        if request:
            ip = get_request_ip(request)

        # Récupération de l'email
        self.user = None
        email = attrs.get('email')
        user_exist = FedowUser.objects.filter(email=email).exists()

        # Avons nous une carte dans la requete ?
        card: Card = attrs.get('card_first_tag_id') or attrs.get('card_qrcode_uuid')
        if card:
            # On ne veut pas écraser une carte avec un user existant,
            # ou un wallet ephemère présent

            # Cas 1 : Carte anonyme mais avec un wallet_ephemere
            # On le lie à l'user
            if card.wallet_ephemere and not user_exist:
                user, created = get_or_create_user(email, ip=ip, wallet_uuid=card.wallet_ephemere.uuid)
                card.user = user
                self.user = user
                card.save()

            # Cas 2 : Carte vierge
            elif not card.user and not card.wallet_ephemere:
                user, created = get_or_create_user(email, ip=ip)
                card.user = user
                self.user = user
                card.save()

            # Cas 3 : User exist et carte avec wallet, erreur à gerer
            # TODO: fusion de wallet
            elif user_exist:
                user = FedowUser.objects.get(email=email)
                self.user = user
                if card.wallet_ephemere :
                    if card.wallet_ephemere != user.wallet:
                        raise serializers.ValidationError("Card already linked to another user")
                if card.user:
                    if card.user != user:
                        raise serializers.ValidationError("Card already linked to another user")

        if not self.user:
            self.user, created = get_or_create_user(email, ip=ip)
        return attrs

    def to_representation(self, instance):
        # Add apikey user to representation
        representation = super().to_representation(instance)
        representation['wallet'] = f"{self.user.wallet.uuid}"
        return representation


class CardSerializer(serializers.ModelSerializer):
    # Un MethodField car le wallet peut être celui de l'user ou celui de la carte anonyme.
    # Faut lancer la fonction get_wallet() pour avoir le bon wallet...
    wallet = serializers.SerializerMethodField()
    origin = OriginSerializer()

    def get_place_origin(self, obj: Card):
        return f"{obj.origin.place.name} V{obj.origin.generation}"

    def get_wallet(self, obj: Card):
        wallet = obj.get_wallet()
        return WalletSerializer(wallet).data

    class Meta:
        model = Card
        fields = (
            'first_tag_id',
            'wallet',
            'origin',
            'uuid',
            'qrcode_uuid',
            'number_printed',
        )


class TransactionW2W(serializers.Serializer):
    amount = serializers.IntegerField()
    sender = serializers.PrimaryKeyRelatedField(queryset=Wallet.objects.all())
    receiver = serializers.PrimaryKeyRelatedField(queryset=Wallet.objects.all())
    asset = serializers.PrimaryKeyRelatedField(queryset=Asset.objects.all())
    subscription_start_datetime = serializers.DateTimeField(required=False)

    primary_card_uuid = serializers.PrimaryKeyRelatedField(queryset=Card.objects.all(), required=False)
    primary_card_fisrtTagId = serializers.SlugRelatedField(
        queryset=Card.objects.all(),
        required=False, slug_field='first_tag_id')
    user_card_uuid = serializers.PrimaryKeyRelatedField(queryset=Card.objects.all(), required=False)
    user_card_firstTagId = serializers.SlugRelatedField(
        queryset=Card.objects.all(),
        required=False, slug_field='first_tag_id')

    def validate_amount(self, value):
        # Positive amount only
        if value <= 0:
            raise serializers.ValidationError("Amount must be positive")
        return value

    def validate_primary_card(self, value):
        # TODO; Check carte primaire et lieux
        return value

    def get_action(self):
        # Quel type de transaction ?
        action = None

        if self.place.wallet == self.sender:
            # Un lieu envoi : c'est une recharge de carte
            action = Transaction.REFILL

            if self.asset.category == Asset.SUBSCRIPTION:
                # ou une adhésion / abonnement
                action = Transaction.SUBSCRIBE

            if self.sender == self.receiver:
                if self.asset.origin == self.place.wallet:
                    raise Exception('send REFILL instead')

        elif self.place.wallet == self.receiver:
            action = Transaction.SALE
            if not self.primary_card:
                raise serializers.ValidationError("Primary card is required for sale transaction")
            if self.primary_card not in self.place.primary_cards.all():
                raise serializers.ValidationError("Primary card must be in place primary cards")
            if not self.user_card:
                raise serializers.ValidationError("User card is required for sale transaction")
            # Si le lieu du wallet est dans la délégation d'autorité du wallet de la carte
            if not self.receiver in self.user_card.get_authority_delegation():
                # Place must be in card user wallet authority delegation
                logger.warning(f"{timezone.localtime()} WARNING sender not in receiver authority delegation")
                raise serializers.ValidationError("Unauthorized")

        return action

    def validate(self, attrs):
        # Récupération de la place grâce à la permission HasKeyAndCashlessSignature
        request = self.context.get('request')
        self.place: Place = request.place

        # get variable
        self.sender: Wallet = attrs.get('sender')
        self.receiver: Wallet = attrs.get('receiver')
        self.asset: Asset = attrs.get('asset')
        self.amount: int = attrs.get('amount')

        # Subscription :
        self.subscription_start_datetime = attrs.get('subscription_start_datetime')

        # Avons nous une carte user et/ou une carte primaire LaBoutik ?
        self.primary_card = attrs.get('primary_card_uuid') or attrs.get('primary_card_fisrtTagId')
        self.user_card = attrs.get('user_card_uuid') or attrs.get('user_card_firstTagId')

        action = self.get_action()
        if not action:
            # Si aucune des conditions d'action n'est remplie, c'est une erreur
            logger.error(
                f"{timezone.localtime()} ERROR sender nor receiver are Unauthorized - ZERO ACTION FOUND - {request}")
            raise serializers.ValidationError("Unauthorized")

        # Check if sender or receiver are authorized
        if not self.place.wallet == self.sender and not self.place.wallet == self.receiver:
            # Place must be sender or receiver
            logger.error(f"{timezone.localtime()} ERROR sender nor receiver are Unauthorized - {request}")
            raise serializers.ValidationError("Unauthorized")

        # get sender token
        try:
            token_sender = Token.objects.get(wallet=self.sender, asset=self.asset)
            # Check if sender has enough value
            if token_sender.value < self.amount and action in [Transaction.SALE, Transaction.TRANSFER]:
                logger.error(f"{timezone.localtime()} ERROR sender not enough value - {request}")
                raise serializers.ValidationError("Not enough token on sender wallet")
        except Token.DoesNotExist:
            raise serializers.ValidationError("Sender token does not exist")

        # get or create receiver token
        try:
            self.token_receiver = Token.objects.get(wallet=self.receiver, asset=self.asset)
        except Token.DoesNotExist:
            logger.info(
                f"{timezone.localtime()} INFO NewTransactionWallet2WalletValidator : receiver token does not exist")
            self.token_receiver = Token.objects.create(wallet=self.receiver, asset=self.asset, value=0)

        ### ALL CHECK OK ###

        # Si c'est un refill, on génère la monnaie avant :
        if action == Transaction.REFILL:
            if not self.primary_card or not self.user_card:
                raise serializers.ValidationError("Primary card and user card are required for refill transaction")

            crea_transac_dict = {
                "ip": get_request_ip(request),
                "checkout_stripe": None,
                "sender": self.sender,
                "receiver": self.sender,
                "asset": self.asset,
                "amount": self.amount,
                "action": Transaction.CREATION,
                "primary_card": self.primary_card,
                "card": self.user_card,
            }
            crea_transaction = Transaction.objects.create(**crea_transac_dict)


            if not crea_transaction.verify_hash():
                logger.error(
                    f"{timezone.localtime()} ERROR NewTransactionWallet2WalletValidator : transaction hash is not valid on CREATION")
                raise serializers.ValidationError("Transaction hash is not valid")

        transaction_dict = {
            "ip": get_request_ip(request),
            "checkout_stripe": None,
            "sender": self.sender,
            "receiver": self.receiver,
            "asset": self.asset,
            "amount": self.amount,
            "action": action,
            "primary_card": self.primary_card,
            "card": self.user_card,
            "subscription_start_datetime": self.subscription_start_datetime
        }
        transaction = Transaction.objects.create(**transaction_dict)

        if not transaction.verify_hash():
            logger.error(
                f"{timezone.localtime()} ERROR NewTransactionWallet2WalletValidator : transaction hash is not valid")
            raise serializers.ValidationError("Transaction hash is not valid")

        self.transaction = transaction
        return attrs


class TransactionSerializer(serializers.ModelSerializer):
    card = CardSerializer(many=False)

    class Meta:
        model = Transaction
        fields = (
            "uuid",
            "action",
            "hash",
            "datetime",
            "subscription_start_datetime",
            "sender",
            "receiver",
            "asset",
            "amount",
            "card",
            "primary_card",
            "previous_transaction",
            "comment",
            "verify_hash",
        )
