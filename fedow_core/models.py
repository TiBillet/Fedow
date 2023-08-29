import os

import stripe
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import UniqueConstraint, Q
from django.db.models.signals import pre_save
from django.dispatch import receiver
from rest_framework_api_key.models import AbstractAPIKey
from django.contrib.auth.models import AbstractUser
from solo.models import SingletonModel
from django.db import models
from uuid import uuid4
from stdimage import JPEGField
from stdimage.validators import MaxSizeValidator, MinSizeValidator

from fedow_core.utils import get_public_key, get_private_key, fernet_decrypt, fernet_encrypt

import logging

logger = logging.getLogger(__name__)


### STRIPE


class CheckoutStripe(models.Model):
    # Si recharge, alors un paiement stripe doit être lié
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    checkout_session_id_stripe = models.CharField(max_length=80, unique=True)
    asset = models.ForeignKey('Asset', on_delete=models.PROTECT,
                              related_name='checkout_stripe')
    OPEN, PENDING, EXPIRE, PAID, VALID, NOTSYNC, CANCELED = 'O', 'W', 'E', 'P', 'V', 'S', 'C'
    STATUT_CHOICES = (
        (OPEN, 'A vérifier'),
        (PENDING, 'En attente de paiement'),
        (EXPIRE, 'Expiré'),
        (PAID, 'Payée'),
        (VALID, 'Payée et validée'),  # envoyé sur serveur cashless
        (NOTSYNC, 'Payée mais problème de synchro cashless'),  # envoyé sur serveur cashless qui retourne une erreur
        (CANCELED, 'Annulée'),
    )
    status = models.CharField(max_length=1, choices=STATUT_CHOICES, default=OPEN, verbose_name="Statut de la commande")

    def create_change_payment_link(self, asset):
        pass

    def is_valid(self):
        if self.status == self.VALID:
            # Déja validé, on renvoie None
            return None

        stripe.api_key = Configuration.get_solo().get_stripe_api()
        checkout_session = stripe.checkout.Session.retrieve(
            self.checkout_session_id_stripe,
            # stripe_account=config.get_stripe_connect_account()
        )
        if checkout_session.payment_status == "paid":
            self.status = self.PAID
            self.save()
            return True

        return False


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
    federated_primary = models.BooleanField(default=False, editable=False, help_text="Asset primaire équivalent euro.")
    id_price_stripe = models.CharField(max_length=30)

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
        constraints = [UniqueConstraint(fields=["federated_primary"], condition=Q(federated_primary=True),
                                        name="unique_federated_primary_asset")]


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

    class Meta:
        unique_together = [['wallet', 'asset']]


class Transaction(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    hash = models.CharField(max_length=64, unique=True, editable=False)

    ip = models.GenericIPAddressField(verbose_name="Ip source")
    checkoupt_stripe = models.ForeignKey(CheckoutStripe, on_delete=models.PROTECT, related_name='checkout_stripe',
                                         blank=True, null=True)
    primary_card_uuid = models.UUIDField(default=uuid4, editable=False, blank=True, null=True)
    card_uuid = models.UUIDField(default=uuid4, editable=False, blank=True, null=True)

    sender = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='transactions_sent')
    receiver = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='transactions_received')
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name='transactions')

    date = models.DateTimeField(auto_now_add=True)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    comment = models.CharField(max_length=100, blank=True)

    SALE, CREATION, REFILL, TRANSFER = 'S', 'C', 'R', 'T'
    TYPE_ACTION = (
        (SALE, "Vente d'article"),
        (CREATION, 'Creation monétaire'),
        (REFILL, 'Recharge Cashless'),
        (TRANSFER, 'Transfert'),
    )
    action = models.CharField(max_length=1, choices=TYPE_ACTION, default=SALE, unique=True)

    class Meta:
        ordering = ['-date']


@receiver(pre_save, sender=Transaction)
def inspector(sender, instance, **kwargs):
    token_receiver, created_r = Token.objects.get(wallet=instance.receiver, asset=instance.asset)

    if instance.action == Transaction.CREATION:
        assert instance.sender == instance.receiver, "Sender and receiver must be the same for creation money."
        assert instance.asset.federated_primary == True, "Asset must be federated primary for creation money."
        if instance.asset.federated_primary:
            assert instance.checkoupt_stripe != None, "Checkout stripe must be set for creation money."


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
        return get_public_key(self.cashless_rsa_pub_key)


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
    uuid = models.UUIDField(primary_key=True, editable=False, db_index=True)
    first_tag_id = models.CharField(max_length=8, editable=False, db_index=True)
    nfc_uuid = models.UUIDField(editable=False)
    qr_code_printed = models.UUIDField(editable=False)
    number = models.CharField(max_length=8, editable=False, db_index=True)
    user = models.ForeignKey(FedowUser, on_delete=models.PROTECT, related_name='cards', blank=True, null=True)
    origin = models.ForeignKey(Origin, on_delete=models.PROTECT, related_name='cards', blank=True, null=True)


def get_or_create_user(email):
    User = get_user_model()
    try:
        user = User.objects.get(email=email.lower())
        created = False
        return user, created
    except User.DoesNotExist:
        user = User.objects.create(
            email=email.lower(),
            username=email.lower()
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
