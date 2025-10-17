import logging
from collections import OrderedDict
from random import choices
from time import sleep
from uuid import UUID

from django.db import transaction

import stripe
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.core.cache import cache
from django.db.models import Sum
from django.db.transaction import atomic
from django.utils import timezone
from rest_framework import serializers
from rest_framework.generics import get_object_or_404

from fedow_core.models import Place, FedowUser, Card, Wallet, Transaction, OrganizationAPIKey, Asset, Token, \
    get_or_create_user, Origin, asset_creator, Configuration, Federation, CheckoutStripe
from fedow_core.utils import get_request_ip, get_public_key, dict_to_b64, verify_signature, data_to_b64

logger = logging.getLogger(__name__)


class HandshakeValidator(serializers.Serializer):
    # Temp fedow place APIkey inside the request header
    fedow_place_uuid = serializers.PrimaryKeyRelatedField(queryset=Place.objects.all())
    cashless_rsa_pub_key = serializers.CharField(max_length=512)
    cashless_ip = serializers.IPAddressField()
    cashless_url = serializers.URLField()
    cashless_admin_apikey = serializers.CharField(max_length=41, min_length=41)
    dokos_id = serializers.CharField(max_length=100, required=False, allow_null=True)

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
        ip_from_request = get_request_ip(request)
        # Si on est en mode debug, on bypass la verification
        if value != ip_from_request and not settings.DEBUG:
            # TODO: en prod, on a toujours l'ip du docker ...
            logger.warning(f"{timezone.localtime()} WARNING Place create Invalid IP {value} != {ip_from_request}")
            # raise serializers.ValidationError("Invalid IP")
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


class PlaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Place
        fields = (
            'uuid',
            'name',
            'dokos_id',
            'wallet',
            # 'stripe_connect_valid', # le stripe connect est créé coté Lespass
            'lespass_domain',
        )

    def validate(self, attrs):
        return attrs


class WalletSerializer(serializers.ModelSerializer):
    tokens = serializers.SerializerMethodField()

    def get_tokens(self, obj: Wallet):
        # On ne pousse que les tokens acceptés par le lieu
        if self.context.get('request'):
            request = self.context.get('request')

            # Requete depuis le cashless
            # Uniquement les tokens acceptés par le lieu demandeur :
            if hasattr(request, 'place'):
                logger.info(f"{timezone.localtime()} WalletSerializer from PLACE : {request.place}")
                place = request.place
                assets = place.accepted_assets()
                logger.info(f"{timezone.localtime()} Wallet : {obj}")
                return TokenSerializer(obj.tokens.filter(wallet=obj, asset__in=assets), many=True).data

        # Si pas de lieu, on envoi tous les tokens du wallet
        logger.info(f"{timezone.localtime()} WalletSerializer without PLACE")
        return TokenSerializer(obj.tokens.filter(wallet=obj), many=True).data

    class Meta:
        model = Wallet
        fields = (
            'uuid',
            'get_name',
            'tokens',
            'has_user_card',
        )


class UserSerializer(serializers.ModelSerializer):
    wallet = WalletSerializer(many=False)

    class Meta:
        model = FedowUser
        fields = (
            'uuid',
            'wallet',
        )


class CardRefundOrVoidValidator(serializers.Serializer):
    primary_card_uuid = serializers.PrimaryKeyRelatedField(queryset=Card.objects.all(), required=False)
    primary_card_fisrtTagId = serializers.SlugRelatedField(
        queryset=Card.objects.all(),
        required=False, slug_field='first_tag_id')
    user_card_uuid = serializers.PrimaryKeyRelatedField(queryset=Card.objects.all(), required=False)
    user_card_firstTagId = serializers.SlugRelatedField(
        queryset=Card.objects.all(),
        required=False, slug_field='first_tag_id')
    action = serializers.ChoiceField(choices=Transaction.TYPE_ACTION, required=False, allow_null=True)

    transactions = list()

    def validate_action(self, value):
        if value not in [Transaction.REFUND, Transaction.VOID]:
            raise serializers.ValidationError("Action must be REFUND or VOID")
        return value

    def validate(self, attrs):
        transactions = list()

        request = self.context.get('request')
        self.place: Place = request.place
        # Avons nous une carte user et/ou une carte primaire LaBoutik ?
        self.primary_card = attrs.get('primary_card_uuid') or attrs.get('primary_card_fisrtTagId')
        self.user_card: Card = attrs.get('user_card_uuid') or attrs.get('user_card_firstTagId')

        if self.primary_card not in request.place.primary_cards.all():
            raise serializers.ValidationError("Primary card must be in place primary cards")

        # On s'assure que la place ai bien un token fédéré si besoin
        if not self.place.wallet.tokens.filter(asset__category=Asset.STRIPE_FED_FIAT).exists():
            stripe_fed = Asset.objects.get(category=Asset.STRIPE_FED_FIAT)
            self.place.wallet.tokens.create(asset=stripe_fed)

        if not self.user_card:
            raise serializers.ValidationError("User card is required for void or refund")

        wallet: Wallet = self.user_card.get_wallet()
        self.ex_wallet_serialized = WalletSerializer(wallet, context=self.context).data

        # C'est ici qu'on prend les asset à rembourser
        local_tokens = wallet.tokens.filter(
            value__gt=0,
            asset__wallet_origin=request.place.wallet,
            asset__category__in=[Asset.TOKEN_LOCAL_FIAT, Asset.TOKEN_LOCAL_NOT_FIAT])
        fed_token = wallet.tokens.filter(
            value__gt=0,
            asset__category=Asset.STRIPE_FED_FIAT)

        for token in (local_tokens | fed_token):
            transaction_dict = {
                "ip": get_request_ip(request),
                "checkout_stripe": None,
                "sender": self.user_card.get_wallet(),
                "receiver": self.place.wallet,
                "asset": token.asset,
                "amount": token.value,
                "action": Transaction.REFUND,
                "primary_card": self.primary_card,
                "card": self.user_card,
                "subscription_start_datetime": None
            }
            transaction = Transaction.objects.create(**transaction_dict)
            transactions.append(TransactionSerializer(transaction, context=self.context).data)

        self.transactions = transactions
        if attrs.get('action') == Transaction.VOID:
            logger.info('action VOID !')
            self.user_card.user = None
            self.user_card.primary_places.clear()
            self.user_card.wallet_ephemere = None
            self.user_card.save()

        return attrs


class CardCreateValidator(serializers.ModelSerializer):
    generation = serializers.IntegerField(required=True)
    is_primary = serializers.BooleanField(required=True)

    # Lors de la création, si il existe déja des assets dans la carte,
    # on les créé avec l'uuid de l'asset cashless pour une meuilleur correspondance.
    tokens_uuid = serializers.ListField(required=False, allow_null=True)

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
        # Le cashless envoie des cartes qui ont déja des tokens.
        # On les créé vide pour faire la correspondance avec l'uuid du cashless.
        pre_tokens = validated_data.pop('tokens_uuid', False)

        is_primary = validated_data.pop('is_primary', False)
        validated_data.pop('generation')
        validated_data['origin'] = self.origin

        print(f"attemp to create card : {validated_data['number_printed']}")
        card = Card.objects.create(**validated_data)
        if is_primary:
            self.origin.place.primary_cards.add(card)

        if pre_tokens:
            for pre_token in pre_tokens:
                try:
                    asset = Asset.objects.get(uuid=pre_token.get('asset_uuid'))
                except Asset.DoesNotExist:
                    raise serializers.ValidationError("Asset does not exist")

                wallet = card.get_wallet()
                token, created = Token.objects.get_or_create(uuid=pre_token.get("token_uuid"), asset=asset,
                                                             wallet=wallet)
                print(f"token {token} created {created}")
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
            'tokens_uuid',
        )


class AssetSerializer(serializers.ModelSerializer):
    place_origin = PlaceSerializer(many=False)

    class Meta:
        model = Asset
        fields = (
            'uuid',
            'name',
            'currency_code',
            'category',
            'get_category_display',
            'place_origin',
            'wallet_origin',
            'created_at',
            'last_update',
            'is_stripe_primary',
            'place_uuid_federated_with',
        )

    def to_representation(self, instance: Asset):
        # Add apikey user to representation
        rep = super().to_representation(instance)
        if self.context.get('action') == 'retrieve':
            # get_or_set va toujours faire la fonction callable avant de vérifier le cache.
            # Solution : soit retirer les () dans le callable, soit utiliser lambda si on a besoin de passer des arguments

            # Pour les test unitaire, desactiver le cache
            if not settings.DEBUG:
                rep['total_token_value'] = cache.get_or_set(f"{instance.uuid}_total_token_value",
                                                            instance.total_token_value, 5)
                rep['total_in_place'] = cache.get_or_set(f"{instance.uuid}_total_in_place", instance.total_in_place, 5)
                rep['total_in_wallet_not_place'] = cache.get_or_set(f"{instance.uuid}_total_in_wallet_not_place",
                                                                    instance.total_in_wallet_not_place, 5)
            else:
                rep['total_token_value'] = instance.total_token_value()
                rep['total_in_place'] = instance.total_in_place()
                rep['total_in_wallet_not_place'] = instance.total_in_wallet_not_place()
        return rep


class AssetCreateValidator(serializers.Serializer):
    uuid = serializers.UUIDField(required=False)
    name = serializers.CharField()
    currency_code = serializers.CharField(max_length=3)
    category = serializers.ChoiceField(choices=Asset.CATEGORIES)
    created_at = serializers.DateTimeField(required=False)

    def validate_name(self, value):
        request = self.context.get('request')
        place = request.place
        if Asset.objects.filter(name=value, archive=False, wallet_origin=place.wallet).exists():
            raise serializers.ValidationError("Asset already exists")
        return value

    def validate_currency_code(self, value):
        #     if Asset.objects.filter(currency_code=value).exists():
        #         raise serializers.ValidationError("Currency code already exists")
        return value.upper()

    def validate(self, attrs):
        request = self.context.get('request')
        place = request.place

        asset_dict = {
            "name": attrs.get('name'),
            "currency_code": attrs.get('currency_code'),
            "category": attrs.get('category'),
            "wallet_origin": place.wallet,
            "ip": get_request_ip(request),
        }

        if attrs.get('uuid'):
            asset_dict["original_uuid"] = attrs.get('uuid')
        if attrs.get('created_at'):
            asset_dict["created_at"] = attrs.get('created_at')

        self.asset = asset_creator(**asset_dict)

        # Pour les tests unitaires :
        # if settings.DEBUG:
        #     federation = Federation.objects.get(name='TEST FED')
        #     federation.assets.add(self.asset)

        if not self.asset:
            raise serializers.ValidationError("Asset creation failed")
        return attrs


class OriginSerializer(serializers.ModelSerializer):
    place = PlaceSerializer()

    class Meta:
        model = Origin
        fields = (
            'place',
            'generation',
            'img',
        )


class CardSerializer(serializers.ModelSerializer):
    # Un MethodField car le wallet peut être celui de l'user ou celui de la carte anonyme.
    # Faut lancer la fonction get_wallet() pour avoir le bon wallet...
    wallet = serializers.SerializerMethodField()
    origin = OriginSerializer()
    is_primary = serializers.SerializerMethodField()

    def get_is_primary(self, obj: Card):
        try:
            request = self.context.get('request')
            place = request.place
            return obj.primary_places.filter(pk=place.pk).exists()
        except Exception as e:
            logger.warning(f"CardSerializer get_is_primary {e}. Probablement une requete en dehors du cashless.")
            return False

    def get_place_origin(self, obj: Card):
        return f"{obj.origin.place.name} V{obj.origin.generation}"

    def get_wallet(self, obj: Card):
        wallet: Wallet = obj.get_wallet()
        return WalletSerializer(wallet, context=self.context).data

    class Meta:
        model = Card
        fields = (
            'first_tag_id',
            'wallet',
            'origin',
            'uuid',
            'qrcode_uuid',
            'number_printed',
            'is_wallet_ephemere',
            'is_primary',
        )


class TransactionSerializer(serializers.ModelSerializer):
    # Serializer gourmant :
    # card va chercher le wallet et tous les assets/tokens associés
    # Aucun cache utilisé, donne l'info en temps réel
    card = CardSerializer(many=False)

    class Meta:
        model = Transaction
        fields = (
            "uuid",
            "action",
            "get_action_display",
            "hash",
            "datetime",
            "subscription_first_datetime",
            "subscription_start_datetime",
            "subscription_type",
            "last_check",
            "sender",
            "receiver",
            "asset",
            "amount",
            "comment",
            "metadata",
            "card",
            "primary_card",
            "previous_transaction",
            "comment",
            "verify_hash",
        )


class TransactionSimpleSerializer(serializers.ModelSerializer):
    """
    Sans le serializer de la carte.
    Ajoute les nom des wallets
    """
    sender_name = serializers.SerializerMethodField()
    receiver_name = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = (
            "uuid",
            "action",
            "get_action_display",
            "hash",
            "datetime",
            "subscription_first_datetime",
            "subscription_start_datetime",
            "subscription_type",
            "last_check",
            "sender",
            "receiver",
            "sender_name",
            "receiver_name",
            "asset",
            "amount",
            "comment",
            "metadata",
            "primary_card",
            "previous_transaction",
            "comment",
            "verify_hash",
        )

    def get_sender_name(self, obj: Transaction):
        return obj.sender.get_name()

    def get_receiver_name(self, obj: Transaction):
        return obj.receiver.get_name()


class TokenSerializer(serializers.ModelSerializer):
    asset = AssetSerializer(many=False)
    last_transaction = TransactionSimpleSerializer(many=False)

    class Meta:
        model = Token
        fields = (
            'uuid',
            'name',
            'value',
            'asset',

            'asset_uuid',
            'asset_name',
            'asset_category',

            'is_primary_stripe_token',

            'last_transaction',
            # Todo, a virer, déja dans last_transaction :
            'last_transaction_datetime',
            'start_membership_date',
        )


class WalletGetOrCreate(serializers.Serializer):
    # Sérialiser utilisé par le front billetterie
    # Si email existe pas, on fabrique. Si existe, on demande la signature
    email = serializers.EmailField()
    public_pem = serializers.CharField(max_length=512, required=True)

    def validate_public_pem(self, value):
        try:
            public_key = get_public_key(value)
            if public_key.key_size < 2048:
                raise serializers.ValidationError("Public key size too small")
        except Exception as e:
            raise serializers.ValidationError("Public key not valid, must be 2048 min rsa key")

        print(f"public_key is_valid")
        self.sended_public_key = public_key
        return value

    def validate(self, attrs):
        request = self.context['request']
        email = attrs.get('email')
        self.created = False

        # Vérification de la signature
        message = data_to_b64(request.data)
        signature = request.META.get("HTTP_SIGNATURE")
        if not verify_signature(self.sended_public_key, message, signature):
            raise serializers.ValidationError("Invalid singature")

        # S'il existe, on check la clé envoyée
        if FedowUser.objects.filter(email=email).exists():
            self.user = FedowUser.objects.get(email=email)
            # Check si pub == user pub

            # if not self.user.wallet.public_pem:
            #     self.user.wallet.public_pem = attrs.get('public_pem')
            #     self.user.wallet.save()
            #     self.created = True

            if attrs.get('public_pem') != self.user.wallet.public_pem:
                raise serializers.ValidationError("Invalid pub pem")

        else:
            # L'utilisateur n'existe pas, on le fabrique avec sa clé publique
            self.user, self.created = get_or_create_user(
                email,
                ip=get_request_ip(request),
                public_pem=attrs.get('public_pem'),
            )

        return attrs


class LinkWalletCard_card_number(serializers.Serializer):
    wallet = serializers.PrimaryKeyRelatedField(queryset=Wallet.objects.filter(user__isnull=False))
    card_number = serializers.SlugRelatedField(slug_field='number_printed',
                                                    queryset=Card.objects.filter(user__isnull=True))



class LinkWalletCardQrCode(serializers.Serializer):
    wallet = serializers.PrimaryKeyRelatedField(queryset=Wallet.objects.filter(user__isnull=False))
    card_qrcode_uuid = serializers.SlugRelatedField(slug_field='qrcode_uuid',
                                                    queryset=Card.objects.filter(user__isnull=True))

    @staticmethod
    def fusion(wallet_source: Wallet, wallet_target: Wallet, card: Card, request_obj) -> Card:
        # Fusion de deux wallets : On réalise une transaction de la totalité de chaque token de la source vers le wallet target
        # Exemple : On vide le wallet ephemere d'une carte en faveur du wallet de l'user

        # On ajoute le place dans la requete pour les vérif transaction.
        if not hasattr(request_obj, 'place'):
            request_obj.place = card.origin.place

        for token in wallet_source.tokens.filter(value__gt=0):
            data = {
                "amount": token.value,
                "asset": f"{token.asset.pk}",
                "sender": f"{wallet_source.pk}",
                "receiver": f"{wallet_target.pk}",
                "action": Transaction.FUSION,
                "user_card_uuid": f"{card.pk}",
            }

            transaction_validator = TransactionW2W(data=data, context={'request': request_obj})
            if not transaction_validator.is_valid():
                logger.error(
                    f"{timezone.localtime()} ERROR FUSION WalletCreateSerializer : {transaction_validator.errors}")
                raise serializers.ValidationError(transaction_validator.errors)

        # Verification que la transaciton a bien vidé le wallet wallet_source
        wallet_source.refresh_from_db()
        if wallet_source.tokens.filter(value__gt=0).exists():
            raise serializers.ValidationError("wallet_source Wallet not empty after fusion")

        # On retire le wallet ephemere de la carte après avoir vérifié qu'il est bien vide
        # On ajoute l'user dans la carte
        card.refresh_from_db()
        card.user = wallet_target.user
        if wallet_source == card.wallet_ephemere:
            card.wallet_ephemere = None
        card.save()

        return card


class WalletCheckoutSerializer(serializers.Serializer):
    email = serializers.EmailField()
    card_first_tag_id = serializers.SlugRelatedField(slug_field='first_tag_id',
                                                     queryset=Card.objects.all(), required=False)

    def validate(self, attrs):
        # On trace l'ip de la requete
        ip = None
        request = self.context.get('request')
        if request:
            ip = get_request_ip(request)

    """
    # plus besoin, les pem et qrcode sont gérés par lespass

    card_qrcode_uuid = serializers.SlugRelatedField(slug_field='qrcode_uuid',
                                                    queryset=Card.objects.all(), required=False)

    public_pem = serializers.CharField(max_length=512)

    def validate_public_pem(self, value):
        try:
            public_key = get_public_key(value)
            if public_key.key_size < 2048:
                raise serializers.ValidationError("Public key size too small")
        except Exception as e:
            raise serializers.ValidationError("Public key not valid, must be 2048 min rsa key")

        print(f"public_key is_valid")
        self.sended_public_key = public_key
        return value
    """

    """
        # Methode utilisé uniquement pour les test strip de laboutik
        
        # Récupération de l'email
        self.user = None
        email = attrs.get('email')
        user_exist = FedowUser.objects.filter(email=email).exists()
        if user_exist:
            self.user = FedowUser.objects.get(email=email)

        card: Card = attrs.get('card_first_tag_id')
        self.card = card

        # Si l'email seul est envoyé et qu'il n'existe pas : on le créé
        if not card and not user_exist:
            self.user, created = get_or_create_user(email, ip=ip, public_pem=attrs.get('public_pem'))
            return attrs

        if card and not user_exist:
            # Si une carte et un nouveau mail, liaison si carte vierge:
            if not card.user and not card.wallet_ephemere:
                user, created = get_or_create_user(email, ip=ip)
                self.user = user
                card.user = user
                card.save()
                return attrs

            # Si la carte possède un wallet ephemere, nous créons l'user avec ce wallet.
            elif not card.user and card.wallet_ephemere:
                user, created = get_or_create_user(email, ip=ip, wallet_uuid=card.wallet_ephemere.uuid)
                self.user = user
                card.user = user
                # Le wallet ephemere est devenu un wallet user, on le retire de la carte
                card.wallet_ephemere = None
                card.save()
                return attrs

            elif card.user or card.wallet_ephemere:
                raise serializers.ValidationError("Card already linked to another user")

        # L'utilisateur existe.
        # Si la carte est liée à un user, on vérifie que c'est le même
        if card and user_exist:
            # Si carte vierge, on lie l'user
            if not card.user and not card.wallet_ephemere:
                card.user = self.user
                card.save()
                return attrs

            # La carte n'a pas d'user, mais un wallet ephemere
            if not card.user and card.wallet_ephemere:
                # Si carte avec wallet ephemere, on lie l'user avec le wallet ephemere
                if card.wallet_ephemere != self.user.wallet:
                    # On vide le wallet ephemere en faveur du wallet de l'user
                    LinkWalletCardQrCode.fusion(wallet_source=card.wallet_ephemere,
                                wallet_target=self.user.wallet,
                                card=card,
                                request_obj=self.context['request'])

            if card.user == self.user:
                return attrs
            else:
                raise serializers.ValidationError("Card already linked to another user")

        raise serializers.ValidationError("User not found ?")

    def to_representation(self, instance):
        # Add apikey user to representation
        representation = super().to_representation(instance)
        self.wallet = self.user.wallet
        representation['wallet'] = f"{self.user.wallet.uuid}"
        return representation
    """


class BadgeCardValidator(serializers.Serializer):
    first_tag_id = serializers.CharField(min_length=8, max_length=8)
    primary_card_firstTagId = serializers.CharField(min_length=8, max_length=8)
    asset = serializers.PrimaryKeyRelatedField(queryset=Asset.objects.filter(category=Asset.BADGE))
    pos_uuid = serializers.UUIDField(required=False, allow_null=True)
    pos_name = serializers.CharField(required=False, allow_null=True)

    def validate_first_tag_id(self, first_tag_id):
        self.card = get_object_or_404(Card, first_tag_id=first_tag_id)
        return first_tag_id

    def validate_primary_card_firstTagId(self, primary_card_firstTagId):
        self.primary_card = get_object_or_404(Card, first_tag_id=primary_card_firstTagId)
        return primary_card_firstTagId

    def validate(self, attrs):
        asset: Asset = attrs.get('asset')
        # création du token badge s'il n'existe pas :
        card_wallet = self.card.get_wallet()
        Token.objects.get_or_create(wallet=card_wallet, asset=asset)

        request = self.context.get('request')
        place: Place = request.place
        # creation du token badge s'il n'existe pas :
        Token.objects.get_or_create(wallet=place.wallet, asset=asset)

        transaction_dict = {
            "ip": get_request_ip(request),
            "checkout_stripe": None,
            "sender": card_wallet,
            "receiver": place.wallet,
            "asset": asset,
            "amount": 0,
            "action": Transaction.BADGE,
            "metadata": self.initial_data,
            "primary_card": self.primary_card,
            "card": self.card,
            "subscription_start_datetime": None
        }
        transaction = Transaction.objects.create(**transaction_dict)
        self.transaction = transaction
        return attrs


class BadgeByWalletSignatureValidator(serializers.Serializer):
    asset = serializers.PrimaryKeyRelatedField(queryset=Asset.objects.filter(category=Asset.BADGE))

    def validate(self, attrs):
        request = self.context.get('request')
        place: Place = request.place
        wallet: Wallet = request.wallet

        transaction_dict = {
            "ip": get_request_ip(request),
            "checkout_stripe": None,
            "sender": wallet,
            "receiver": place.wallet,
            "asset": attrs.get('asset'),
            "amount": 0,
            "action": Transaction.BADGE,
            "metadata": self.initial_data,
            "primary_card": None,
            "card": None,
            "subscription_start_datetime": None
        }
        transaction = Transaction.objects.create(**transaction_dict)
        self.transaction = transaction
        return attrs


class TransactionRefilFromLespassSerializer(serializers.Serializer):
    sender = serializers.PrimaryKeyRelatedField(queryset=Wallet.objects.all())
    receiver = serializers.PrimaryKeyRelatedField(queryset=Wallet.objects.all())
    asset = serializers.PrimaryKeyRelatedField(queryset=Asset.objects.filter(archive=False))
    amount = serializers.IntegerField()
    metadata = serializers.JSONField(required=False, allow_null=True)


    def validate_sender(self, sender: Wallet):
        request = self.context.get('request')
        self.place: Place = getattr(request, 'place', None)
        if sender != self.place.wallet:
            raise serializers.ValidationError("Sender must be the place")
        logger.info(f"sender checked OK. Is {sender}")
        self.sender = sender
        return sender

    def validate_receiver(self, receiver: Wallet):
        request = self.context.get('request')
        self.wallet: Wallet = getattr(request, 'wallet', None)
        if receiver != self.wallet:
            raise serializers.ValidationError("receiver must be the signed wallet")
        logger.info(f"sender checked OK. Is {receiver}")
        self.receiver = receiver
        return receiver

    def validate_asset(self, asset: Asset):
        request = self.context.get('request')
        self.place: Place = getattr(request, 'place', None)

        if asset.category not in [
            Asset.TOKEN_LOCAL_FIAT,
            Asset.TOKEN_LOCAL_NOT_FIAT,
            Asset.TIME,
            Asset.FIDELITY,
        ]:
            raise serializers.ValidationError("Asset type must be LOCAL")


        if asset.wallet_origin != self.place.wallet:
            raise serializers.ValidationError("Asset must be from the place")

        if asset.archive:
            raise serializers.ValidationError("Asset must not be archived")

        # Create tokens for the wallet and place if not exist
        Token.objects.get_or_create(wallet=self.sender, asset=asset)
        Token.objects.get_or_create(wallet=self.receiver, asset=asset)

        logger.info(f"asset checked OK : {asset}")
        self.asset = asset
        return asset

    def validate_amount(self, value):
        # Positive amount only
        if value < 0:
            raise serializers.ValidationError("Amount cannot be negative")
        return value

    def validate_metadata(self, metadata):
        # Dans ce type de transaction, il doit y avoir l'uuid du produit qui fait le trigg
        # et l'id du checkout stripe pour vérification et traçabilité.
        keys = [
            'ligne_article_uuid',
            'membership_uuid',
            'product_uuid',
            'price_uuid',
        ]
        for key in keys:
            if not metadata.get(key):
                raise serializers.ValidationError("No data in metadata for " + key)
            try :
                UUID(metadata[key])
            except ValueError:
                raise serializers.ValidationError("No UUID in metadata for " + key)

        # Check checkout_session_id_stripe
        checkout_session_id_stripe = metadata.get('checkout_session_id_stripe') # dans le cas d'un paiement direct
        invoice_stripe_id = metadata.get('invoice_stripe_id') # dans le cas d'un renouvellement

        if not checkout_session_id_stripe and not invoice_stripe_id:
            raise serializers.ValidationError("No checkout_session_id_stripe nor invoice_stripe_id in metadata")

        if checkout_session_id_stripe:
           if CheckoutStripe.objects.filter(checkout_session_id_stripe=checkout_session_id_stripe).exists():
                raise serializers.ValidationError("checkout_session_id_stripe Already reported")
        if invoice_stripe_id:
            if CheckoutStripe.objects.filter(invoice_stripe_id=invoice_stripe_id).exists():
                raise serializers.ValidationError("invoice_stripe_id Already reported")

        self.checkout_stripe = CheckoutStripe.objects.create(
            checkout_session_id_stripe=checkout_session_id_stripe,
            invoice_stripe_id=invoice_stripe_id,
            metadata=metadata,
            status=CheckoutStripe.FROM_LESPASS,
            asset=self.asset,
            user=self.receiver.user,
        )
        return metadata


    @atomic
    def validate(self, attrs):
        # Création de la transaction.
        request = self.context.get('request')

        crea_transac_dict = {
            "ip": get_request_ip(request),
            "sender": attrs.get('sender'),
            "receiver": attrs.get('sender'),
            "asset": attrs.get('asset'),
            "comment": None,
            "metadata": attrs.get('metadata'),
            "checkout_stripe": self.checkout_stripe,
            "amount": attrs.get('amount'),
            "action": Transaction.CREATION,
            "primary_card": None,
            "card": None,
        }
        crea_transaction = Transaction.objects.create(**crea_transac_dict)

        if not crea_transaction.verify_hash():
            logger.error(
                f"{timezone.localtime()} ERROR NewTransactionWallet2WalletValidator : transaction hash is not valid on CREATION")
            raise serializers.ValidationError("Transaction hash is not valid")

        transaction_dict = {
            "ip": get_request_ip(request),
            "sender": attrs.get('sender'),
            "receiver": attrs.get('receiver'),
            "asset": attrs.get('asset'),
            "comment": None,
            "metadata": attrs.get('metadata'),
            "checkout_stripe": self.checkout_stripe,
            "amount": attrs.get('amount'),
            "action": Transaction.REFILL,
            "primary_card": None,
            "card": None,
            "subscription_start_datetime": None
        }
        transaction = Transaction.objects.create(**transaction_dict)

        if not transaction.verify_hash():
            logger.error(
                f"{timezone.localtime()} ERROR NewTransactionWallet2WalletValidator : transaction hash is not valid")
            raise serializers.ValidationError("Transaction hash is not valid")

        self.transaction = transaction
        return attrs


class TransactionQrCodeSerializer(serializers.Serializer):
    sender = serializers.PrimaryKeyRelatedField(queryset=Wallet.objects.all())
    receiver = serializers.PrimaryKeyRelatedField(queryset=Wallet.objects.all())
    asset_type = serializers.ChoiceField(choices=['EURO', 'GIFT'])
    amount = serializers.IntegerField()

    comment = serializers.CharField(required=False, allow_null=True)
    metadata = serializers.JSONField(required=False, allow_null=True)

    def validate_receiver(self, receiver: Wallet):
        request = self.context.get('request')
        self.place: Place = getattr(request, 'place', None)
        if receiver != self.place.wallet:
            raise serializers.ValidationError("Receiver must be the same as the place")
        logger.info(f"receiver checked OK. Is {receiver}")
        return receiver

    def validate_sender(self, sender: Wallet):
        request = self.context.get('request')
        self.wallet: Wallet = getattr(request, 'wallet', None)
        if sender != self.wallet:
            raise serializers.ValidationError("Sender must be the signed wallet")
        logger.info(f"sender checked OK. Is {sender}")
        return sender

    def validate_asset_type(self, asset_type: str):
        if asset_type not in ['EURO', 'GIFT']:
            raise serializers.ValidationError("Asset type must be either 'EURO' or 'GIFT'")
        # On récupère les asset_type pour savoir avec quels assets on paye
        request = self.context.get('request')
        assets = request.place.accepted_assets_fiat() if request.data.get('asset_type') == 'EURO' else []
        self.assets = assets or []
        logger.info(f"assets checked OK : {self.assets}")
        return asset_type

    def validate_amount(self, value):
        # Positive amount only
        if value <= 0:
            raise serializers.ValidationError("Amount cannot be negative nor zero")
        self.total_tokens_sender = \
            Token.objects.filter(wallet=self.wallet, asset__in=(self.assets or [])).aggregate(total_value=Sum('value'))[
                'total_value'] or 0
        if value > self.total_tokens_sender:
            raise serializers.ValidationError("Amount cannot exceed the total amount")

        logger.info(f"amount checked OK. Total token sender capable {self.total_tokens_sender} > {value}")
        return value

    # Petit itérateur pour indiquer quel asset paie quelle somme
    def _iter_asset_payments(self, total_to_pay: int):
        """
        Itérateur simple et lisible.
        - On parcourt les assets acceptés (self.assets)
        - Pour chacun, on regarde le solde disponible sur le wallet de l'utilisateur
        - On prélève le minimum entre le reste à payer et ce solde
        - On ajoute (asset, montant_utilisé) dans la liste
        """
        # Répartition simple de la somme sur les différents assets acceptés
        allocations = []  # liste de tuples (asset, montant)
        allocated = 0

        remaining = total_to_pay
        for asset in (getattr(self, 'assets', []) or []):
            if remaining <= 0:
                break
            # Solde disponible pour cet asset dans le wallet de l'utilisateur
            token = Token.objects.filter(wallet=self.wallet, asset=asset).first()
            available = token.value if token else 0
            if available <= 0:
                continue
            used = min(available, remaining)
            remaining -= used
            # On indique quel asset paie quelle somme
            allocations.append((asset, used))
            allocated += used

        # Par sécurité, on vérifie qu'on couvre bien le total demandé
        if allocated != total_to_pay:
            logger.error(f"Allocation des assets incomplète: {allocated} != {total_to_pay}")
            raise serializers.ValidationError("Impossible de répartir le montant sur les assets disponibles")

        return allocations

    @atomic
    def validate(self, attrs):
        request = self.context.get('request')
        total_to_pay = attrs['amount']
        total_tokens_sender = self.total_tokens_sender

        # On stocke la répartition pour usage ultérieur (ex: création des transactions par asset)
        self.asset_payments = self._iter_asset_payments(total_to_pay)
        self.transactions = []

        for asset, amount in self.asset_payments:
            # On s'assure que les token existe dans les deux cas
            Token.objects.get_or_create(wallet=attrs.get('sender'), asset=asset)
            Token.objects.get_or_create(wallet=attrs.get('receiver'), asset=asset)

            transaction_dict = {
                "ip": get_request_ip(request),
                "sender": attrs.get('sender'),
                "receiver": attrs.get('receiver'),
                "asset": asset,
                "comment": attrs.get('comment'),
                "metadata": attrs.get('metadata'),
                "checkout_stripe": None,
                "amount": amount,
                "action": Transaction.QRCODE_SALE,
                "primary_card": None,
                "card": None,
                "subscription_start_datetime": None,
            }
            transaction = Transaction.objects.create(**transaction_dict)

            if not transaction.verify_hash():
                logger.error(
                    f"{timezone.localtime()} ERROR NewTransactionWallet2WalletValidator : transaction hash is not valid")
                raise serializers.ValidationError("Transaction hash is not valid")

            self.transactions.append(transaction)

        return attrs


class TransactionW2W(serializers.Serializer):
    amount = serializers.IntegerField()
    sender = serializers.PrimaryKeyRelatedField(queryset=Wallet.objects.all())
    receiver = serializers.PrimaryKeyRelatedField(queryset=Wallet.objects.all())
    asset = serializers.PrimaryKeyRelatedField(queryset=Asset.objects.filter(archive=False))
    subscription_start_datetime = serializers.DateTimeField(required=False)
    action = serializers.ChoiceField(choices=Transaction.TYPE_ACTION, required=False, allow_null=True)

    first_token_uuid = serializers.UUIDField(required=False, allow_null=True)

    comment = serializers.CharField(required=False, allow_null=True)
    metadata = serializers.JSONField(required=False, allow_null=True)
    checkout_stripe = serializers.PrimaryKeyRelatedField(queryset=CheckoutStripe.objects.all(),
                                                         required=False, allow_null=True)

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
        if value < 0:
            raise serializers.ValidationError("Amount cannot be negative")
        return value

    def validate_primary_card(self, value):
        try:
            request = self.context.get('request')
            self.place: Place = getattr(request, 'place', None)
            if self.place not in value.primary_places.all():
                raise serializers.ValidationError("Carte primaire non valide")
            return value
        except Exception as e:
            logger.error(f"TransactionW2W validate_primary_card {e}")
            raise serializers.ValidationError("Carte primaire non valide")

    def validate_primary_card_fisrtTagId(self, value: Card):
        try:
            request = self.context.get('request')
            self.place: Place = getattr(request, 'place', None)
            if self.place not in value.primary_places.all():
                raise serializers.ValidationError("Carte primaire non valide")
            return value
        except Exception as e:
            logger.error(f"TransactionW2W validate_primary_card_fisrtTagId {e}")
            raise serializers.ValidationError("Carte primaire non valide")

    def get_action(self, attrs):
        # Quel type de transaction ?
        action = None

        if (attrs.get('action') == Transaction.REFILL
                and self.checkout_stripe
                and self.sender.is_primary()
                and self.asset.is_stripe_primary()
        ):
            # C'est une recharge stripe
            return Transaction.REFILL

        # Un lieu est le sender, trois cas possibles : Adhésion / Badge / Recharge locale
        if self.place.wallet == self.sender:
            # adhésion / abonnement
            if self.asset.category == Asset.SUBSCRIPTION:
                return Transaction.SUBSCRIBE
            # Badgeuse
            if self.asset.category == Asset.BADGE:
                return Transaction.BADGE

            # ex methode, on ne fait plus qu'une seule requete maintenant.
            if self.sender == self.receiver:
                if self.asset.wallet_origin == self.place.wallet:
                    raise serializers.ValidationError('no longuer implemented for REFILL. Send user wallet instead')
                raise serializers.ValidationError("Unauthorized wallet_origin")

            # C'est une recharge locale, on a besoin de deux cartes
            if not self.primary_card or not self.user_card:
                raise serializers.ValidationError("Primary card and user card are required for refill transaction")
            return Transaction.REFILL

        elif self.place.wallet == self.receiver:
            if not self.primary_card:
                raise serializers.ValidationError("Primary card is required for sale transaction")
            if self.primary_card not in self.place.primary_cards.all():
                raise serializers.ValidationError("Primary card must be in place primary cards")
            if not self.user_card:
                raise serializers.ValidationError("User card is required for sale transaction")
            # Si le lieu du wallet est dans la délégation d'autorité du wallet de la carte
            # if not self.receiver in self.user_card.get_authority_delegation():
            # Place must be in card user wallet authority delegation
            # logger.warning(f"{timezone.localtime()} WARNING sender not in receiver authority delegation")
            # raise serializers.ValidationError("Unauthorized")
            if self.asset not in self.place.accepted_assets():
                raise serializers.ValidationError("Asset not accepted")
            # Toute validation passée, c'est une vente
            return Transaction.SALE


        elif attrs.get('action') == Transaction.FUSION:
            # Liaison entre une carte avec wallet ephemere et un wallet user -> Fusion !
            # Le sender est le wallet ephemere d'une carte sans user
            # Le receiver est le wallet user d'un user déja existant
            # mais dont le wallet est différent du wallet_ephemere de la carte
            # C'est une fusion de deux wallet en faveur de celui de l'user : le receiver
            sender: Wallet = attrs.get('sender')
            receiver: Wallet = attrs.get('receiver')
            if (not getattr(sender, 'user', None)
                    and sender.card_ephemere
                    and receiver.user):

                # Uniquement avec une clé api de place pour le moment.
                # Pour que l'user puisse le faire en autonomie -> auth forte (tel, double auth, etc ...)
                if sender.card_ephemere.origin.place == self.place:
                    return Transaction.FUSION

        raise serializers.ValidationError("No action authorized")

    # @transaction.atomic
    def validate(self, attrs):
        # Récupération de la place grâce à la permission HasKeyAndPlaceSignature
        request = self.context.get('request')
        # get variable
        self.sender: Wallet = attrs.get('sender')
        self.receiver: Wallet = attrs.get('receiver')
        self.asset: Asset = attrs.get('asset')
        self.amount: int = attrs.get('amount')
        self.comment: str = attrs.get('comment')
        self.metadata: str = attrs.get('metadata')
        self.checkout_stripe: CheckoutStripe = attrs.get('checkout_stripe', None)
        # Subscription :
        self.subscription_start_datetime = attrs.get('subscription_start_datetime')

        # Avons nous une carte user et/ou une carte primaire LaBoutik ?
        self.primary_card: Card = attrs.get('primary_card_uuid') or attrs.get('primary_card_fisrtTagId')
        self.user_card: Card = attrs.get('user_card_uuid') or attrs.get('user_card_firstTagId')

        self.place: Place = getattr(request, 'place', None)

        if not self.place:
            # C'est probablement une recharge stripe.
            # Le serializer est appellé par le webhook post paiement, il n'y a pas de place.
            if (attrs.get('action') == Transaction.REFILL
                    and self.checkout_stripe
                    and self.sender.is_primary()
                    and self.asset.is_stripe_primary()):
                # Si c'est une recharge depuis Stripe,
                # on met la place de l'origine de la carte, si on a la carte :
                if self.user_card:
                    self.place: Place = self.user_card.origin.place

            else:
                # Dans tout les autre cas, il nous faut une place
                logger.error(f"{timezone.localtime()} ERROR NewTransactionWallet2WalletValidator : place not found")
                raise serializers.ValidationError("Place not found")

        action = self.get_action(attrs)
        if not action:
            # Si aucune des conditions d'action n'est remplie, c'est une erreur
            logger.error(
                f"{timezone.localtime()} ERROR ZERO ACTION FOUND - {request}")
            raise serializers.ValidationError("Unauthorized")

        # get sender token
        try:
            token_sender = Token.objects.get(wallet=self.sender, asset=self.asset)
            # Check if sender has enough value
            if token_sender.value < self.amount and action in [Transaction.SALE, Transaction.TRANSFER]:
                logger.error(f"\n{timezone.localtime()} ERROR sender not enough value - {request}\n")
                raise serializers.ValidationError("Not enough token on sender wallet")
        except Token.DoesNotExist:
            raise serializers.ValidationError("Sender token does not exist")

        # get or create receiver token
        try:
            self.token_receiver = Token.objects.get(wallet=self.receiver, asset=self.asset)
        except Token.DoesNotExist:
            logger.info(
                f"{timezone.localtime()} INFO NewTransactionWallet2WalletValidator : receiver token does not exist -> create")
            self.token_receiver = Token.objects.create(wallet=self.receiver, asset=self.asset, value=0)

        # On vérifie qu'une transaction CREATION pour refill avec le même checkout id stripe n'existe déja ?
        if Transaction.objects.filter(
                action=Transaction.CREATION,
                checkout_stripe=self.checkout_stripe,
                asset__category=Asset.STRIPE_FED_FIAT,
        ).exists():
            raise serializers.ValidationError("Stripe token creation with this paiement already made")

        ### ALL CHECK OK ###

        # Si c'est un refill, on génère la monnaie avant :
        if action == Transaction.REFILL:

            crea_transac_dict = {
                "ip": get_request_ip(request),
                "sender": self.sender,
                "receiver": self.sender,
                "asset": self.asset,
                "comment": self.comment,
                "metadata": self.metadata,
                "checkout_stripe": self.checkout_stripe,
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
            "sender": self.sender,
            "receiver": self.receiver,
            "asset": self.asset,
            "comment": self.comment,
            "metadata": self.metadata,
            "checkout_stripe": self.checkout_stripe,
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


class CachedTransactionSerializer(serializers.ModelSerializer):
    # Un serializer qui est sensé gérer plusieurs transaction par liste : on utilise le cache
    # Utilisé uniquement pour la vue DERNIERE TRANSACTION de Lespass : my_account
    serialized_asset = serializers.SerializerMethodField()
    serialized_sender = serializers.SerializerMethodField()
    serialized_receiver = serializers.SerializerMethodField()
    card = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = (
            "uuid",
            "action",
            "get_action_display",
            "hash",
            "datetime",
            "subscription_first_datetime",
            "subscription_start_datetime",
            "subscription_type",
            "last_check",
            "sender",
            "receiver",
            "asset",
            "amount",
            "comment",
            "metadata",
            "card",
            "primary_card",
            "previous_transaction",
            "comment",
            "verify_hash",
            "serialized_asset",
            "serialized_sender",
            "serialized_receiver",
            "card",
        )

    def get_card(self, obj):
        if obj.card:
            # get_or_set va toujours faire la fonction callable avant de vérifier le cache.
            # Solution : soit retirer les () dans le callable, soit utiliser lambda si on a besoin de passer des arguments
            return cache.get_or_set(f'serialized_card_{obj.card.uuid}',
                                    lambda: CardSerializer(obj.card, many=False).data,
                                    300)
        return None

    def get_serialized_asset(self, obj):
        if self.context.get('detailed_asset'):
            return cache.get_or_set(f'serialized_asset_{obj.asset.uuid}',
                                    lambda: AssetSerializer(obj.asset).data,
                                    300)
        return None

    def get_serialized_sender(self, obj):
        if self.context.get('serialized_sender'):
            return cache.get_or_set(f'serialized_wallet_{obj.sender.uuid}',
                                    lambda: WalletSerializer(obj.sender).data,
                                    300)
        return None

    def get_serialized_receiver(self, obj):
        if self.context.get('serialized_receiver'):
            return cache.get_or_set(f'serialized_wallet_{obj.receiver.uuid}',
                                    lambda: WalletSerializer(obj.receiver).data,
                                    300)
        return None


class FederationSerializer(serializers.ModelSerializer):
    places = PlaceSerializer(many=True)
    assets = AssetSerializer(many=True)

    class Meta:
        model = Federation
        fields = (
            'uuid',
            'name',
            'places',
            'assets',
            'description',
        )
