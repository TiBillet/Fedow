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
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    name = models.CharField(max_length=100, unique=True)
    currency_code = models.CharField(max_length=3, unique=True)
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
    # Primary and federated asset send to cashless on new connection
    # On token of this asset is equivalent to 1 euro
    # A Stripe Chekcout must be associated to the transaction creation money
    stripe_primary = models.BooleanField(default=False, editable=False, help_text="Asset primaire équivalent euro.")
    id_price_stripe = models.CharField(max_length=30, blank=True, null=True, editable=False)


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

    class Meta:
        # Only one can be true :
        constraints = [UniqueConstraint(fields=["stripe_primary"],
                                        condition=Q(stripe_primary=True),
                                        name="unique_stripe_primary_asset")]


class Wallet(models.Model):
    # One wallet per user
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    name = models.CharField(max_length=100, blank=True, null=True)

    private_pem = models.CharField(max_length=2048, editable=False)
    public_pem = models.CharField(max_length=512, editable=False)

    # Déléguation d'autorité à un autre wallet
    # qui permet de prélever sur ce wallet vers/depuis le sien.
    # La symmetrie n'est pas obligatoire.
    authority_delegation = models.ManyToManyField('self', related_name='delegations', symmetrical=False, blank=True)

    ip = models.GenericIPAddressField(verbose_name="Ip source", default='0.0.0.0')

    def is_primary(self):
        if getattr(self, 'primary', None):
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


class Token(models.Model):
    # One token per user per currency
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    value = models.PositiveIntegerField(default=0, help_text="Valeur, en centimes.")
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='tokens')
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name='tokens')

    # def __str__(self):
    #     return f"{self.wallet.name} {self.asset.name} {self.value}"
    def is_primary_stripe_token(self):
        if self.asset.stripe_primary and self.wallet.is_primary():
            return True
        return False

    class Meta:
        unique_together = [['wallet', 'asset']]


class Transaction(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    hash = models.CharField(max_length=64, unique=True, editable=False)

    ip = models.GenericIPAddressField(verbose_name="Ip source")
    checkout_stripe = models.ForeignKey(CheckoutStripe, on_delete=models.PROTECT, related_name='checkout_stripe',
                                        blank=True, null=True)

    sender = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='transactions_sent')
    receiver = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='transactions_received')
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name='transactions')

    card = models.ForeignKey('Card', on_delete=models.PROTECT, related_name='transactions', blank=True, null=True)
    primary_card = models.ForeignKey('Card', on_delete=models.PROTECT, related_name='associated_primarycard_transactions', blank=True, null=True)

    previous_transaction = models.ForeignKey('self', on_delete=models.PROTECT, related_name='next_transaction')
    datetime = models.DateTimeField()
    amount = models.PositiveIntegerField()
    comment = models.CharField(max_length=100, blank=True)

    FIRST, SALE, CREATION, REFILL, TRANSFER = 'F', 'S', 'C', 'R', 'T'
    TYPE_ACTION = (
        (FIRST, "Premier bloc"),
        (SALE, "Vente d'article"),
        (CREATION, 'Creation monétaire'),
        (REFILL, 'Recharge Cashless'),
        (TRANSFER, 'Transfert'),
    )
    action = models.CharField(max_length=1, choices=TYPE_ACTION, default=SALE)

    def dict_for_hash(self):
        dict_for_hash = {
            'sender': f"{self.sender.uuid}",
            'receiver': f"{self.receiver.uuid}",
            'asset': f"{self.asset.uuid}",
            'amount': f"{self.amount}",
            'date': f"{self.datetime.isoformat()}",
            'action': f"{self.action}",
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
        self.datetime = timezone.localtime()
        token_sender, created = Token.objects.get_or_create(wallet=self.sender, asset=self.asset)
        token_receiver, created = Token.objects.get_or_create(wallet=self.receiver, asset=self.asset)

        # Validator 0 : First must be unique
        if self.action == Transaction.FIRST:
            assert not self.asset.transactions.filter(action=Transaction.FIRST).exists(), "First transaction already exists."

        # Validator 1 : IF CREATION
        if self.action == Transaction.CREATION:
            assert self.sender == self.receiver, "Sender and receiver must be the same for creation money."
            assert self.asset.stripe_primary == True, "Asset must be federated primary for creation money."
            if self.asset.stripe_primary:
                assert self.checkout_stripe != None, "Checkout stripe must be set for creation money."

            # FILL TOKEN WALLET
            token_receiver.value += self.amount
            token_receiver.save()

        # Vlidator 2 : IF REFILL
        if self.action == Transaction.REFILL:
            assert not self.receiver.is_primary(), "Receiver must be a user wallet"
            assert not self.receiver.is_place(), "Receiver must be a user wallet"
            assert self.checkout_stripe != None, "Checkout stripe must be set for refill."
            assert token_sender.value >= self.amount, "Sender must have enough for refill the user wallet."

            # FILL TOKEN WALLET
            token_sender.value -= self.amount
            token_sender.save()
            token_receiver.value += self.amount
            token_receiver.save()

        # ALL VALIDATOR PASSED : HASH CREATION
        if not self.hash:
            self.previous_transaction = self._previous_asset_transaction()
            self.hash = self.create_hash()
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
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    email = models.EmailField(max_length=100, unique=True)

    # customer standard user
    stripe_customer_id = models.CharField(max_length=21, blank=True, null=True)

    wallet = models.OneToOneField(Wallet, on_delete=models.PROTECT, related_name='user', blank=True, null=True)

    # key = models.OneToOneField(APIKey,
    #                            on_delete=models.SET_NULL,
    #                            blank=True, null=True,
    #                            related_name="fedow_user"
    #                            )


class Place(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
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

    def logo_variations(self):
        return self.logo.variations

    def cashless_public_key(self) -> rsa.RSAPublicKey:
        if self.cashless_rsa_pub_key:
            return get_public_key(self.cashless_rsa_pub_key)
        else :
            raise Exception("Cashless public key empty.")

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


class Card(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)

    first_tag_id = models.CharField(max_length=8, editable=False, db_index=True)
    nfc_uuid = models.UUIDField(editable=False)

    qr_code_printed = models.UUIDField(editable=False)
    number = models.CharField(max_length=8, editable=False, db_index=True)

    user = models.ForeignKey(FedowUser, on_delete=models.PROTECT, related_name='cards', blank=True, null=True)
    origin = models.ForeignKey(Origin, on_delete=models.PROTECT, related_name='cards', blank=True, null=True)



def get_or_create_user(email, ip=None):
    User: FedowUser = get_user_model()
    try:
        user = User.objects.get(email=email.lower())
        created = False
        return user, created
    except User.DoesNotExist:
        private_pem, public_pem = rsa_generator()

        if ip == None:
            ip = '0.0.0.0'

        wallet = Wallet.objects.create(
            ip=ip,
            private_pem=private_pem,
            public_pem=public_pem,
        )

        user = User.objects.create(
            email=email.lower(),
            username=email.lower(),
            wallet=wallet,
        )
        created = True

        return user, created


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
