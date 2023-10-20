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

# class AssetSerializer(serializers.ModelSerializer):
#     class Meta:
#         models = Asset
#         fields = (


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


class CardSerializer(serializers.ModelSerializer):
    # Un MethodField car le wallet peut être celui de l'user ou celui de la carte anonyme.
    # Faut lancer la fonction get_wallet() pour avoir le bon wallet...
    wallet= serializers.SerializerMethodField()

    def get_wallet(self, obj: Card):
        wallet= obj.get_wallet()
        return WalletSerializer(wallet).data

    class Meta:
        model = Card
        fields = (
            'wallet',
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



        self.receiver = receiver
        self.sender = sender

        return attrs


class TransactionW2W(serializers.Serializer):
    amount = serializers.IntegerField()
    sender = serializers.PrimaryKeyRelatedField(queryset=Wallet.objects.all())
    receiver = serializers.PrimaryKeyRelatedField(queryset=Wallet.objects.all())
    asset = serializers.PrimaryKeyRelatedField(queryset=Asset.objects.all())

    primary_card = serializers.PrimaryKeyRelatedField(queryset=Card.objects.all(), required=False)
    user_card = serializers.PrimaryKeyRelatedField(queryset=Card.objects.all(), required=False)

    def validate_amount(self, value):
        # Positive amount only
        if value <= 0:
            raise serializers.ValidationError("Amount must be positive")
        return value

    def validate_primary_card(self, value):
        #TODO; Check carte primaire et lieux
        return value

    def validate_user_card(self, value):
        return value

    def get_action(self):
        # Quel type de transaction ?
        action = None

        if self.place.wallet == self.sender :
            # Un lieu envoi : c'est une recharge de carte
            # ou une adhésion / abonnement
            action = Transaction.REFILL
            if self.sender == self.receiver:
                if self.asset.origin == self.place.wallet:
                    # Le wallet du lieu est le sender ET le receiver
                    # L'origine de l'asset est bien le lieu
                    # C'est alors une création de token d'asset non FEDEREE PRIMAIRE (qui doit obligatoirement passer par stripe )
                    # adhésion, monnaie temps, monnaie cadeau, etc ...
                    action = Transaction.CREATION

        elif self.place.wallet == self.receiver:
            action = Transaction.SALE
            # Si le lieu du wallet est dans la délégation d'autorité du wallet de la carte
            if not self.receiver in self.sender.get_authority_delegation(card=self.card):
                # Place must be in card user wallet authority delegation
                logger.warning(f"{timezone.localtime()} WARNING sender not in receiver authority delegation")
                raise serializers.ValidationError("Unauthorized")

        return action


    def validate(self, attrs):
        # Récupération de la place grâce a la permission HasKeyAndCashlessSignature
        request = self.context.get('request')
        self.place: Place = request.place

        # get variable
        self.sender: Wallet = attrs.get('sender')
        self.receiver: Wallet = attrs.get('receiver')
        self.asset: Asset = attrs.get('asset')
        self.amount: int = attrs.get('amount')
        self.card = attrs.get('user_card')

        action = self.get_action()
        if not action:
            # Si aucune des conditions d'action n'est remplie, c'est une erreur
            logger.error(f"{timezone.localtime()} ERROR sender nor receiver are Unauthorized - ZERO ACTION FOUND - {request}")
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
            if token_sender.value < self.amount and action != Transaction.CREATION:
                logger.error(f"{timezone.localtime()} ERROR sender not enough value - {request}")
                raise serializers.ValidationError("Sender not enough value")
        except Token.DoesNotExist:
            raise serializers.ValidationError("Sender token does not exist")

        # get or create receiver token
        try:
            self.token_receiver = Token.objects.get(wallet=self.receiver, asset=self.asset)
        except Token.DoesNotExist:
            logger.info(f"{timezone.localtime()} INFO NewTransactionWallet2WalletValidator : receiver token does not exist")
            self.token_receiver = Token.objects.create(wallet=self.receiver, asset=self.asset, value=0)


        ### ALL CHECK OK ###
        transaction = Transaction.objects.create(
            ip=get_request_ip(request),
            checkout_stripe=None,
            sender=self.sender,
            receiver=self.receiver,
            asset=self.asset,
            amount=self.amount,
            action=action,
            primary_card=attrs.get('primary_card'),
            card=attrs.get('user_card'),
        )

        if not transaction.verify_hash():
            logger.error(f"{timezone.localtime()} ERROR NewTransactionWallet2WalletValidator : transaction hash is not valid")
            raise serializers.ValidationError("Transaction hash is not valid")

        self.transaction = transaction
        return attrs


class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = (
            "uuid",
            "action",
            "hash",
            "datetime",
            "sender",
            "receiver",
            "amount",
            "previous_transaction",
            "comment",
            "verify_hash",
        )
