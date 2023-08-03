from rest_framework_api_key.models import APIKey
from django.contrib.auth.models import AbstractUser

from django.db import models
import uuid
from uuid import uuid4

### USER MODEL

class CustomUser(AbstractUser):
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    email = models.EmailField(max_length=100, unique=True)

###

class Asset(models.Model):
    # One asset per currency
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)

    RTL, G1, T4S, STRIPE = 'RTL', 'G1', 'T4S', 'STR'
    TYPE_ACRONYMS = (
        (RTL, 'Reunion Tiers Lieux Assets'),
        (G1, 'June'),
        (T4S, 'Ti 4 Sous'),
        (STRIPE, 'Stripe'),
    )
    type = models.CharField(max_length=3, choices=TYPE_ACRONYMS, default=RTL, unique=True)

    def name(self):
        return self.get_type_display()


class Wallet(models.Model):
    # One wallet per user
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    name = models.CharField(max_length=100, unique=True, blank=True, null=True)

    key = models.OneToOneField(APIKey,
                               on_delete=models.CASCADE,
                               blank=True, null=True,
                               related_name="api_key"
                               )

    ip = models.GenericIPAddressField(verbose_name="Ip source")

class Token(models.Model):
    # One token per user per currency
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    value = models.DecimalField(max_digits=20, decimal_places=2)
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT)
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT)

    class Meta:
        unique_together = [['wallet', 'asset']]


class Transaction(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    ip = models.GenericIPAddressField(verbose_name="Ip source")

    primary_card_uuid = models.UUIDField(default=uuid4, editable=False)
    card_uuid = models.UUIDField(default=uuid4, editable=False)

    sender = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='transactions_sent')
    receiver = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='transactions_received')

    token = models.ForeignKey(Token, on_delete=models.PROTECT)
    date = models.DateTimeField(auto_now_add=True)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    comment = models.CharField(max_length=100, blank=True)


    class Meta:
        ordering = ['-date']
