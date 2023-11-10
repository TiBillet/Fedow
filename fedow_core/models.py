import hashlib
import json
import os

import stripe
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import UniqueConstraint, Q
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.utils import timezone
from rest_framework_api_key.models import AbstractAPIKey
from django.contrib.auth.models import AbstractUser
from solo.models import SingletonModel
from django.db import models
from uuid import uuid4

from stdimage import JPEGField
from stdimage.validators import MaxSizeValidator, MinSizeValidator

from fedow_core.utils import get_public_key, get_private_key, fernet_decrypt, fernet_encrypt, rsa_generator

import logging

logger = logging.getLogger(__name__)


### STRIPE


class CheckoutStripe(models.Model):
    # Si recharge, alors un paiement stripe doit être lié
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    datetime = models.DateTimeField(auto_now_add=True)
    checkout_session_id_stripe = models.CharField(max_length=80, unique=True)
    asset = models.ForeignKey('Asset', on_delete=models.PROTECT,
                              related_name='checkout_stripe')
    OPEN, EXPIRE, PAID, WALLET_PRIMARY_OK, WALLET_USER_OK, CANCELED = 'O', 'E', 'P', 'W', 'V', 'C'
    STATUT_CHOICES = (
        (OPEN, 'En attente de paiement'),
        (EXPIRE, 'Expiré'),
        (PAID, 'Payé'),
        (WALLET_PRIMARY_OK, 'Wallet primaire chargé'),  # wallet primaire chargé
        (WALLET_USER_OK, 'Wallet user chargé'),  # wallet chargé
        (CANCELED, 'Annulée'),
    )
    status = models.CharField(max_length=1, choices=STATUT_CHOICES, default=OPEN, verbose_name="Statut de la commande")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='checkout_stripe')
    metadata = models.CharField(editable=False, db_index=False, max_length=500)

    def __str__(self):
        self.user: FedowUser
        return f"{self.user.email} {self.status}"


## BLOCKCHAIN PART

class Asset(models.Model):
    # One asset per currency
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=False)
    name = models.CharField(max_length=100, unique=True)
    currency_code = models.CharField(max_length=3)

    created_at = models.DateTimeField(default=timezone.now)
    last_update = models.DateTimeField(auto_now=True, verbose_name="Dernière modification des informations de l'asset")

    img = JPEGField(upload_to='assets/',
                    validators=[
                        MinSizeValidator(480, 480),
                        MaxSizeValidator(1920, 1920)
                    ],
                    variations={
                        'med': (480, 480),
                        'thumbnail': (150, 150),
                        'crop': (150, 150, True),
                    },
                    delete_orphans=True,
                    verbose_name='logo',
                    blank=True, null=True,
                    )

    comment = models.TextField(blank=True, null=True)

    origin = models.ForeignKey('Wallet', on_delete=models.PROTECT,
                               # related_name='primary_asset',
                               related_name='assets_created',
                               help_text="Lieu ou configuration d'origine",
                               editable=False,
                               )

    TOKEN_LOCAL_FIAT = 'TLF'
    TOKEN_LOCAL_NOT_FIAT = 'TNF'
    STRIPE_FED_FIAT = 'FED'
    SUBSCRIPTION = 'SUB'

    CATEGORIES = [
        (TOKEN_LOCAL_FIAT, 'Fiduciary local token'),
        (TOKEN_LOCAL_NOT_FIAT, 'Token local non fiduciaire'),
        (STRIPE_FED_FIAT, 'Fiduciary and federated token on stripe'),
        (SUBSCRIPTION, 'Membership or subscription'),
    ]

    category = models.CharField(
        max_length=3,
        choices=CATEGORIES
    )

    # Primary and federated asset send to cashless on new connection
    # On token of this asset is equivalent to 1 euro
    # A Stripe Chekcout must be associated to the transaction creation money
    id_price_stripe = models.CharField(max_length=30, blank=True, null=True, editable=False)

    def total_token_value(self):
        return sum([token.value for token in self.tokens.all()])

    def is_stripe_primary(self):
        if (self.origin == Configuration.get_solo().primary_wallet
                and self.id_price_stripe != None
                and self.category == Asset.STRIPE_FED_FIAT):
            return True
        return False

    def get_id_price_stripe(self,
                            force=False,
                            stripe_key=None,
                            ):

        if self.id_price_stripe and not force:
            return self.id_price_stripe

        if stripe_key == None:
            stripe_key = Configuration.get_solo().get_stripe_api()
        stripe.api_key = stripe_key

        # noinspection PyUnresolvedReferences
        images = []
        if self.img:
            images = [f"https://{os.environ.get('DOMAIN')}{self.img.med.url}", ]

        product = stripe.Product.create(
            name=f"Recharge {self.name}",
            images=images
        )

        data_stripe = {
            'nickname': f"{self.name}",
            "billing_scheme": "per_unit",
            "currency": "eur",
            "tax_behavior": "inclusive",
            "custom_unit_amount": {
                "enabled": "true",
            },
            "metadata": {
                "asset": f'{self.name}',
                "asset_uuid": f'{self.uuid}',
                "currency_code": f'{self.currency_code}',
            },
            "product": product.id,
        }
        price = stripe.Price.create(**data_stripe)
        self.id_price_stripe = price.id
        self.save()

    def __str__(self):
        return f"{self.name} {self.currency_code}"

    class Meta:
        # Only one can be true :
        constraints = [UniqueConstraint(fields=["category"],
                                        condition=Q(category='FED'),
                                        name="unique_stripe_primary_asset")]


class Wallet(models.Model):
    # One wallet per user
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=False)
    name = models.CharField(max_length=100, blank=True, null=True)

    private_pem = models.CharField(max_length=2048, editable=False)
    public_pem = models.CharField(max_length=512, editable=False)

    ip = models.GenericIPAddressField(verbose_name="Ip source", default='0.0.0.0')

    def get_name(self):
        if self.name:
            return self.name
        elif getattr(self, 'place', None):
            return self.place.name
        elif getattr(self, 'user', None):
            return self.user.email
        elif getattr(self, 'primary', None):
            return "Primary"
        return f"{str(self.uuid)[:8]}"

    def is_primary(self):
        # primary is the related name of the Wallet Configuration foreign key
        # On peux récupérer cet object dans les controleurs de cette façon : Wallet.objects.get(primary__isnull=False)
        if getattr(self, 'primary', None):
            # le self.primary devrait suffire (config est un singleton),
            # mais on vérifie quand même
            if self.primary == Configuration.get_solo():
                return True
        return False

    def is_place(self):
        if getattr(self, 'place', None):
            return True
        return False

    def public_key(self) -> rsa.RSAPublicKey:
        return get_public_key(self.public_pem)

    def private_key(self) -> rsa.RSAPrivateKey:
        return get_private_key(self.private_pem)

    def __str__(self):
        return f"{self.get_name()} - {[(token.asset.name, token.value) for token in self.tokens.all()]}"


class Token(models.Model):
    # One token per user per currency
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=False)
    value = models.PositiveIntegerField(default=0, help_text="Valeur, en centimes.")
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='tokens')
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name='tokens')

    def name(self):
        return self.asset.name

    def asset_name(self):
        return self.asset.name

    # def __str__(self):
    #     return f"{self.wallet.name} {self.asset.name} {self.value}"
    def is_primary_stripe_token(self):
        if self.asset.is_stripe_primary() and self.wallet.is_primary():
            return True
        return False

    def __str__(self):
        return f"{self.wallet.get_name()} - {self.asset.name} {self.value}"

    class Meta:
        unique_together = [['wallet', 'asset']]


class Transaction(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=False)
    hash = models.CharField(max_length=64, unique=True, editable=False)

    ip = models.GenericIPAddressField(verbose_name="Ip source")
    checkout_stripe = models.ForeignKey(CheckoutStripe, on_delete=models.PROTECT, related_name='checkout_stripe',
                                        blank=True, null=True)

    sender = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='transactions_sent')
    receiver = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='transactions_received')
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name='transactions')

    card = models.ForeignKey('Card', on_delete=models.PROTECT, related_name='transactions', blank=True, null=True)
    primary_card = models.ForeignKey('Card', on_delete=models.PROTECT,
                                     related_name='associated_primarycard_transactions', blank=True, null=True)

    previous_transaction = models.ForeignKey('self', on_delete=models.PROTECT, related_name='next_transaction')
    datetime = models.DateTimeField()

    amount = models.PositiveIntegerField()
    comment = models.TextField(blank=True, null=True)

    subscription_start_datetime = models.DateTimeField(blank=True, null=True)

    FIRST, SALE, CREATION, REFILL, TRANSFER, SUBSCRIBE = 'F', 'S', 'C', 'R', 'T', 'B'
    TYPE_ACTION = (
        (FIRST, "Premier bloc"),
        (SALE, "Vente d'article"),
        (CREATION, 'Creation monétaire'),
        (REFILL, 'Recharge'),
        (TRANSFER, 'Transfert'),
        (SUBSCRIBE, 'Abonnement ou adhésion'),
    )
    action = models.CharField(max_length=1, choices=TYPE_ACTION, default=SALE)

    def dict_for_hash(self):
        dict_for_hash = {
            'sender': f"{self.sender.uuid}",
            'receiver': f"{self.receiver.uuid}",
            'asset': f"{self.asset.uuid}",
            'amount': f"{self.amount}",
            'date': f"{self.datetime.isoformat()}",
            'subscription_start_datetime': f"{self.subscription_start_datetime.isoformat()}" if self.subscription_start_datetime else None,
            'action': f"{self.action}",
            'card': f"{self.card.uuid}" if self.card else None,
            'primary_card': f"{self.primary_card.uuid}" if self.primary_card else None,
            'comment': f"{self.comment}",
            'checkoupt_stripe': f"{self._checkout_session_id_stripe()}",
            'previous_asset_transaction_uuid': f"{self.previous_transaction.uuid}",
            'previous_asset_transaction_hash': f"{self.previous_transaction.hash}",
        }
        return dict_for_hash

    def _checkout_session_id_stripe(self):
        if self.checkout_stripe:
            return self.checkout_stripe.checkout_session_id_stripe
        return None

    def _previous_asset_transaction(self):
        # Return self if it's the first transaction of the asset
        # Order by date. The newest is the last wrote in database.
        return self.asset.transactions.all().order_by('datetime').last() or self

    def create_hash(self):
        dict_for_hash = self.dict_for_hash()
        encoded_block = json.dumps(dict_for_hash, sort_keys=True).encode('utf-8')
        return hashlib.sha256(encoded_block).hexdigest()

    def verify_hash(self):
        if self.action == Transaction.FIRST:
            return True
        dict_for_hash = self.dict_for_hash()
        encoded_block = json.dumps(dict_for_hash, sort_keys=True).encode('utf-8')
        return hashlib.sha256(encoded_block).hexdigest() == self.hash

    def save(self, *args, **kwargs):
        if not self.datetime:
            self.datetime = timezone.localtime()
        token_sender, created = Token.objects.get_or_create(wallet=self.sender, asset=self.asset)
        token_receiver, created = Token.objects.get_or_create(wallet=self.receiver, asset=self.asset)

        ## Check previous transaction
        # Le hash ne peut se faire que si la transaction précédente est validée
        self.previous_transaction = self._previous_asset_transaction()
        assert self.previous_transaction.verify_hash(), "Previous transaction hash is not valid."
        assert self.previous_transaction.datetime <= self.datetime, "Datetime must be after previous transaction."

        # Validator FIRST : First must be unique
        if self.action == Transaction.FIRST:
            assert not self.asset.transactions.filter(
                action=Transaction.FIRST).exists(), "First transaction already exists."

        # Validator CREATION
        elif self.action == Transaction.CREATION:
            assert self.sender == self.receiver, "Sender and receiver must be the same for creation money."
            if self.asset.is_stripe_primary():
                # Pas besoin de carte primaire, mais besoin d'un checkout stripe
                # TODO: Chekout stripe must be unique
                assert self.checkout_stripe != None, "Checkout stripe must be set for create federated money."
            else:
                # besoin d'une carte primaire pour création monétaire
                assert self.primary_card, "Primary card must be set for creation money."
                assert self.primary_card in self.receiver.place.primary_cards.all(), \
                    "Primary card must be set for place"
            # FILL TOKEN WALLET
            token_receiver.value += self.amount

        # Validatr 4 : IF SUBSCRIBE
        elif self.action == Transaction.SUBSCRIBE:
            # Pas besoin de création monétaire, on charge directement le wallet client
            assert self.asset.category == Asset.SUBSCRIPTION, "Asset must be a subscription asset"
            assert self.sender.is_place(), "Sender must be a place wallet"
            assert self.sender.place.wallet == self.asset.origin, "Subscription origin must be the place"
            assert self.receiver.user, "Receiver must be a user wallet"

            # On ajoute le montant de l'abonnement au wallet du client
            token_receiver.value += self.amount

        # Validator 2 : IF REFILL
        if self.action == Transaction.REFILL:
            # On vérifie que la transaction précédente soit bien une création monétaire
            assert self.previous_transaction.action == Transaction.CREATION, "Previous transaction of Refill must be a creation money."

            # Nous avons besoin que le sender possède assez de token
            if not token_sender.value >= self.amount:
                raise ValueError("amount too high")
            assert not self.receiver.is_primary(), "Receiver must be a user wallet"
            if self.card:
                assert self.card.get_wallet() == self.receiver, "Card must be associated to receiver wallet"
                if not self.card.wallet_ephemere:
                    assert self.receiver.user, "Receiver must be a user wallet"
            assert not self.receiver.is_place(), "Receiver must be a user wallet"
            if self.asset.is_stripe_primary():
                assert self.checkout_stripe != None, "Checkout stripe must be set for refill."

            # FILL TOKEN WALLET
            token_sender.value -= self.amount
            token_receiver.value += self.amount

        # Validator 3 : IF SALE
        if self.action == Transaction.SALE:
            # Nous avons besoin que le sender ait assez de token
            if not token_sender.value >= self.amount:
                raise ValueError("amount too high")

            assert self.receiver.is_place(), "Receiver must be a place wallet"
            assert self.receiver.place, "Receiver must be a place wallet"
            assert not self.receiver.is_primary(), "Receiver must be a place wallet"
            assert not self.sender.is_place(), "Sender must be a user wallet"

            assert self.card, "Card must be set for sale."
            assert self.card.get_wallet() == self.sender, "Card must be associated to sender wallet"
            if not self.card.wallet_ephemere:
                assert self.sender.user, "Sender must be a user wallet"

            assert not self.sender.is_primary(), "Sender must be a user wallet"

            assert self.primary_card, "Primary card must be set for sale."
            assert self.primary_card in self.receiver.place.primary_cards.all(), \
                "Primary card must be set for place"

            # FILL TOKEN WALLET
            token_sender.value -= self.amount
            token_receiver.value += self.amount

        # ALL VALIDATOR PASSED : HASH CREATION
        if not self.hash:
            self.hash = self.create_hash()

        if self.verify_hash():
            token_sender.save()
            token_receiver.save()
            print(f"*** {self.action} : {token_sender} -> {token_receiver}")
            super(Transaction, self).save(*args, **kwargs)
        else:
            raise Exception("Transaction hash already set.")

    class Meta:
        ordering = ['-datetime']


"""
@receiver(pre_save, sender=Transaction)
def inspector(sender, instance, **kwargs):
    token_receiver = Token.objects.get(wallet=instance.receiver, asset=instance.asset)
"""


class Federation(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=False)
    name = models.CharField(max_length=100, unique=True)
    places = models.ManyToManyField('Place', related_name='federations')

    def __str__(self):
        return f"{self.name} : {','.join([place.name for place in self.places.all()])}"


class Configuration(SingletonModel):
    name = models.CharField(max_length=100)
    domain = models.URLField()
    # Wallet used to create money

    primary_wallet = models.OneToOneField(Wallet, on_delete=models.PROTECT, related_name='primary')
    stripe_endpoint_secret_enc = models.CharField(max_length=100, blank=True, null=True, editable=False)

    # def primary_key(self):
    #     return self.primary_wallet.key

    def get_stripe_api(self):
        if settings.STRIPE_TEST:
            return settings.STRIPE_KEY_TEST
        else:
            return settings.STRIPE_KEY

    def set_stripe_endpoint_secret(self, string):
        self.stripe_endpoint_secret_enc = fernet_encrypt(string)
        self.save()
        return True

    def get_stripe_endpoint_secret(self):
        if settings.STRIPE_TEST:
            return os.environ.get("STRIPE_ENDPOINT_SECRET_TEST")
        return fernet_decrypt(self.stripe_endpoint_secret_enc)


class FedowUser(AbstractUser):
    """
    User model with email as unique identifier
    """
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=False)
    email = models.EmailField(max_length=100, unique=True, db_index=True)

    # customer standard user
    stripe_customer_id = models.CharField(max_length=21, blank=True, null=True)

    wallet = models.OneToOneField(Wallet, on_delete=models.PROTECT, related_name='user', blank=True, null=True)

    # key = models.OneToOneField(APIKey,
    #                            on_delete=models.SET_NULL,
    #                            blank=True, null=True,
    #                            related_name="fedow_user"
    #                            )


class Place(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=False)
    name = models.CharField(max_length=100, unique=True)

    # User with Stripe connect and cashless federated server
    wallet = models.OneToOneField(Wallet, on_delete=models.PROTECT, related_name='place')

    stripe_connect_account = models.CharField(max_length=21, blank=True, null=True, editable=False)
    stripe_connect_valid = models.BooleanField(default=False)

    cashless_server_ip = models.GenericIPAddressField(blank=True, null=True, editable=False)
    cashless_server_url = models.URLField(blank=True, null=True, editable=False)
    cashless_rsa_pub_key = models.CharField(max_length=512, blank=True, null=True, editable=False,
                                            help_text="Public rsa Key of cashless server for signature.")
    cashless_admin_apikey = models.CharField(max_length=256, blank=True, null=True, editable=False,
                                             help_text="Encrypted API key of cashless server admin.")

    admins = models.ManyToManyField(FedowUser, related_name='admin_places')

    logo = JPEGField(upload_to='images/',
                     validators=[
                         MinSizeValidator(720, 720),
                         MaxSizeValidator(1920, 1920)
                     ],
                     variations={
                         'hdr': (720, 720),
                         'med': (480, 480),
                         'thumbnail': (150, 90),
                         'crop': (480, 270, True),
                     },
                     delete_orphans=True,
                     verbose_name='logo',
                     blank=True, null=True,
                     )

    def federated_with(self):
        places = []
        for federation in self.federations.all():
            for place in federation.places.all():
                places.append(place)
        return places

    def wallet_federated_with(self):
        wallets = []
        for place in self.federated_with():
            wallets.append(place.wallet)
        return wallets

    def logo_variations(self):
        return self.logo.variations

    def cashless_public_key(self) -> rsa.RSAPublicKey:
        if self.cashless_rsa_pub_key:
            return get_public_key(self.cashless_rsa_pub_key)
        else:
            raise Exception("Cashless public key empty.")

    def __str__(self):
        return self.name


class Origin(models.Model):
    place = models.ForeignKey(Place, on_delete=models.PROTECT, related_name='origins')
    generation = models.IntegerField()
    img = JPEGField(upload_to='images/',
                    validators=[
                        MinSizeValidator(720, 720),
                        MaxSizeValidator(1920, 1920)
                    ],
                    blank=True, null=True,
                    variations={
                        'hdr': (720, 720),
                        'med': (480, 480),
                        'thumbnail': (150, 90),
                        'crop': (480, 270, True),
                    },
                    delete_orphans=True,
                    verbose_name='img',
                    )

    def __str__(self):
        return f"{self.place.name} - V{self.generation}"


class Card(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid4, db_index=False)

    first_tag_id = models.CharField(max_length=8, unique=True, db_index=True)
    complete_tag_id_uuid = models.UUIDField(blank=True, null=True)

    qrcode_uuid = models.UUIDField(unique=True)
    number_printed = models.CharField(max_length=8, unique=True, db_index=True)

    user = models.ForeignKey(FedowUser, on_delete=models.PROTECT, related_name='cards', blank=True, null=True)
    origin = models.ForeignKey(Origin, on_delete=models.PROTECT, related_name='cards')
    primary_places = models.ManyToManyField(Place, related_name='primary_cards')

    # Dette technique pour les cartes qui ne possèdent pas d'utilisateur
    # TODO : Dès qu'un user se manifeste, fusionner les wallet
    wallet_ephemere = models.OneToOneField(Wallet, on_delete=models.PROTECT, related_name='card_ephemere', blank=True,
                                           null=True)

    def get_wallet(self):
        if self.user:
            return self.user.wallet
        if self.wallet_ephemere:
            return self.wallet_ephemere

        # Si nous n'avons pas de user, nous créons un wallet éphémère
        # pour les cartes de festivals anonymes
        else:
            wallet_ephemere = wallet_creator()
            self.wallet_ephemere = wallet_ephemere
            self.save()
            return self.wallet_ephemere

    def get_authority_delegation(self):
        card: Card = self
        place_origin = card.origin.place
        return place_origin.wallet_federated_with()


class OrganizationAPIKey(AbstractAPIKey):
    place = models.ForeignKey(
        Place,
        on_delete=models.CASCADE,
        related_name="api_keys",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_keys",
    )

    class Meta:
        ordering = ("-created",)
        verbose_name = "API key"
        verbose_name_plural = "API keys"
        unique_together = [['place', 'user']]


### CREATORS TOOLS


def wallet_creator(ip=None, name=None):
    if ip is None:
        ip = "0.0.0.0"

    private_pem, public_pem = rsa_generator()
    wallet = Wallet.objects.create(
        name=name,
        ip=ip,
        private_pem=private_pem,
        public_pem=public_pem,
    )
    return wallet


def asset_creator(name: str = None,
                  currency_code: str = None,
                  category: str = None,
                  origin: Wallet = None,
                  original_uuid: uuid4 = None,
                  created_at: timezone = None,
                  ip=None, ):
    """
    Create an asset with a first block
    Can be outdated if the creation date if before the creation of fedow instance
    """

    if created_at is None:
        created_at = timezone.localtime()

    if ip is None:
        ip = "0.0.0.0"

    # Code Currency must be 3 char max
    if len(currency_code) > 3:
        raise ValueError('Max 3 char for currency code')

    # Check catégorie. Si stripe : unique, sinon vérification que la catégorie est dans les choix
    if category == Asset.STRIPE_FED_FIAT:
        # Il ne peut y avoir qu'un seul asset de type STRIPE_FED_FIAT
        if Asset.objects.filter(category=Asset.STRIPE_FED_FIAT).exists():
            raise ValueError('Only one asset of type STRIPE_FED_FIAT can exist')
    elif category not in [Asset.TOKEN_LOCAL_FIAT, Asset.TOKEN_LOCAL_NOT_FIAT, Asset.SUBSCRIPTION]:
        raise ValueError('Category not in choices')

    # Vérification que l'asset et/ou le code n'existe pas
    try:
        Asset.objects.get(name=name)
        raise ValueError('Asset name already exist')
    except Asset.DoesNotExist:
        pass
    try:
        Asset.objects.get(currency_code=currency_code)
        raise ValueError('Asset currency_code already exist')
    except Asset.DoesNotExist:
        pass

    asset = Asset.objects.create(
        uuid=original_uuid if original_uuid else uuid4(),
        name=name,
        currency_code=currency_code,
        origin=origin,
        category=category,
        created_at=created_at,
    )

    # Création du premier block
    first_block = Transaction.objects.create(
        ip=ip,
        checkout_stripe=None,
        sender=origin,
        receiver=origin,
        asset=asset,
        amount=int(0),
        datetime=created_at,
        action=Transaction.FIRST,
        card=None,
        primary_card=None,
    )
    print(f"First block created for {asset.name}")
    return asset


def get_or_create_user(email, ip=None):
    User: FedowUser = get_user_model()
    try:
        user = User.objects.get(email=email.lower())
        created = False
        return user, created
    except User.DoesNotExist:
        user = User.objects.create(
            email=email.lower(),
            username=email.lower(),
            wallet=wallet_creator(ip=ip),
        )
        created = True

        return user, created
