from django.contrib.auth.models import AbstractUser
from django.db import models
import uuid



class Asset(models.Model):
    # One asset per currency
    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_index=True)

    RTL, G1, T4S = 'RTL', 'G1', 'T4S'
    TYPE_ACRONYMS = (
        (RTL, 'Reunion Tiers Lieux Assets'),
        (G1, 'June'),
        (T4S, 'Ti 4 Sous'),
    )
    type = models.CharField(max_length=3, choices=TYPE_ACRONYMS, default=RTL, unique=True)

    def name(self):
        return self.get_type_display()


class Wallet(models.Model):
    # One wallet per user
    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_index=True)


class Token(models.Model):
    # One token per user per currency
    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_index=True)
    value = models.DecimalField(max_digits=20, decimal_places=2)
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT)
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT)

    class Meta:
        unique_together = [['wallet', 'asset']]


class Transaction(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_index=True)
    sender = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='transactions_sent')
    receiver = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='transactions_received')
    token = models.ForeignKey(Token, on_delete=models.PROTECT)
    date = models.DateTimeField(auto_now_add=True)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    comment = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ['-date']
