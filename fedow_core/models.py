from rest_framework_api_key.models import APIKey
from django.contrib.auth.models import AbstractUser
from solo.models import SingletonModel
from django.db import models
from uuid import uuid4
from stdimage import JPEGField
from stdimage.validators import MaxSizeValidator, MinSizeValidator


class Asset(models.Model):
    # One asset per currency
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    name = models.CharField(max_length=100, unique=True)
    currency_code = models.CharField(max_length=3, unique=True)

    key = models.OneToOneField(APIKey,
                               on_delete=models.CASCADE,
                               related_name="asset_key"
                               )

class Wallet(models.Model):
    # One wallet per user
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    name = models.CharField(max_length=100, unique=True, blank=True, null=True)

    key = models.OneToOneField(APIKey,
                               on_delete=models.CASCADE,
                               blank=True, null=True,
                               related_name="wallet_key"
                               )

    ip = models.GenericIPAddressField(verbose_name="Ip source")


class Token(models.Model):
    # One token per user per currency
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    value = models.DecimalField(max_digits=20, decimal_places=2)
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='tokens')
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name='tokens')

    class Meta:
        unique_together = [['wallet', 'asset']]


class Transaction(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    ip = models.GenericIPAddressField(verbose_name="Ip source")

    primary_card_uuid = models.UUIDField(default=uuid4, editable=False)
    card_uuid = models.UUIDField(default=uuid4, editable=False)

    sender = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='transactions_sent')
    receiver = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='transactions_received')
    token = models.ForeignKey(Token, on_delete=models.PROTECT, related_name='transactions')

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


class Configuration(SingletonModel):
    instance_name = models.CharField(max_length=100, unique=True)
    # Wallet used to create money
    primary_wallet = models.OneToOneField(Wallet, on_delete=models.PROTECT, related_name='primary')

    def primary_key(self):
        return self.primary_wallet.key

    stripe_api_key = models.CharField(max_length=110, blank=True, null=True)
    stripe_test_api_key = models.CharField(max_length=110, blank=True, null=True)

    stripe_mode_test = models.BooleanField(default=True)

    def get_stripe_api(self):
        if self.stripe_mode_test:
            return self.stripe_test_api_key
        else:
            return self.stripe_api_key

class FedowUser(AbstractUser):
    """
    User model with email as unique identifier
    """
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    email = models.EmailField(max_length=100, unique=True)

    # customer standard user
    stripe_customer_id = models.CharField(max_length=21, blank=True, null=True)

    wallet = models.OneToOneField(Wallet, on_delete=models.PROTECT, related_name='user')


class Place(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    name = models.CharField(max_length=100, unique=True)

    # User with Stripe connect and cashless federated server
    wallet = models.OneToOneField(Wallet, on_delete=models.PROTECT, related_name='place')
    stripe_connect_account = models.CharField(max_length=21, blank=True, null=True)
    cashless_server_url = models.URLField(blank=True, null=True)
    cashless_server_key = models.CharField(max_length=100, blank=True, null=True)

    admin = models.ManyToManyField(FedowUser, related_name='places')

    logo = JPEGField(upload_to='images/',
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
                     verbose_name='logo',
                     )


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


class NFCCard(models.Model):
    uuid = models.UUIDField(primary_key=True, editable=False, db_index=True)
    first_tag_id = models.CharField(max_length=8, editable=False, db_index=True)
    nfc_tag_id = models.UUIDField(max_length=8, editable=False, db_index=True)
    number = models.CharField(max_length=8, editable=False, db_index=True)
    user = models.ForeignKey(FedowUser, on_delete=models.PROTECT, related_name='cards', blank=True, null=True)
    origin = models.ForeignKey(Origin, on_delete=models.PROTECT, related_name='cards', blank=True, null=True)
