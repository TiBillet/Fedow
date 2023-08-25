import stripe
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models.signals import pre_save
from django.dispatch import receiver
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

    # Primary and federated asset send to cashless on new connection
    # One by instance.
    federated_primary = models.BooleanField(default=False, editable=False)

    # key = models.OneToOneField(APIKey,
    #                            on_delete=models.CASCADE,
    #                            related_name="asset_key"
    #                            )

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        if self.federated_primary:
            try:
                primary = Asset.objects.get(federated_primary=True)
                if primary != self:
                    raise Exception("Federated primary already exist")
            except Asset.DoesNotExist:
                pass
            except Exception as e:
                raise Exception(f"Federated primary error : {e}")

        super().save(force_insert, force_update, using, update_fields)


class Wallet(models.Model):
    # One wallet per user
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    name = models.CharField(max_length=100, blank=True, null=True)

    private_rsa_key = models.CharField(max_length=2048, editable=False)
    public_rsa_key = models.CharField(max_length=512, editable=False)

    ip = models.GenericIPAddressField(verbose_name="Ip source", default='0.0.0.0')

    # user = RelatedName FedowUser


class Token(models.Model):
    # One token per user per currency
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    value = models.DecimalField(max_digits=20, decimal_places=2)
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='tokens')
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name='tokens')

    class Meta:
        unique_together = [['wallet', 'asset']]


class CheckoutStripe(models.Model):
    # Si recharge, alors un paiement stripe doit être lié
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    checkout_session_id_stripe = models.CharField(max_length=80, unique=True)

    NON, OPEN, PENDING, EXPIRE, PAID, VALID, NOTSYNC, CANCELED = 'N', 'O', 'W', 'E', 'P', 'V', 'S', 'C'
    STATUT_CHOICES = (
        (OPEN, 'A vérifier'),
        (PENDING, 'En attente de paiement'),
        (EXPIRE, 'Expiré'),
        (PAID, 'Payée'),
        (VALID, 'Payée et validée'),  # envoyé sur serveur cashless
        (NOTSYNC, 'Payée mais problème de synchro cashless'),  # envoyé sur serveur cashless qui retourne une erreur
        (CANCELED, 'Annulée'),
    )
    status = models.CharField(max_length=1, choices=STATUT_CHOICES, default=NON, verbose_name="Statut de la commande")

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


class Transaction(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
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
def where_we_do_the_thing(sender, instance, **kwargs):
    token_receiver, created_r = Token.objects.get_or_create(wallet=instance.receiver, asset=instance.asset)

    if instance.action == Transaction.CREATION:
        assert instance.sender == instance.receiver
        assert instance.asset.federated_primary == True
        token_receiver.value += instance.amount
    else:
        token_sender, created_s = Token.objects.get_or_create(wallet=instance.sender, asset=instance.asset)
        token_sender.value -= instance.amount
        token_sender.save()
        token_receiver.value += instance.amount

    token_receiver.save()


class Configuration(SingletonModel):
    name = models.CharField(max_length=100)
    domain = models.URLField()
    # Wallet used to create money
    primary_wallet = models.OneToOneField(Wallet, on_delete=models.PROTECT, related_name='primary')

    # def primary_key(self):
    #     return self.primary_wallet.key

    def get_stripe_api(self):
        if settings.STRIPE_TEST:
            return settings.STRIPE_KEY_TEST
        else:
            return settings.STRIPE_KEY


class FedowUser(AbstractUser):
    """
    User model with email as unique identifier
    """
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    email = models.EmailField(max_length=100, unique=True)

    # customer standard user
    stripe_customer_id = models.CharField(max_length=21, blank=True, null=True)

    wallet = models.OneToOneField(Wallet, on_delete=models.PROTECT, related_name='user', blank=True, null=True)

    key = models.OneToOneField(APIKey,
                               on_delete=models.CASCADE,
                               blank=True, null=True,
                               related_name="wallet_key"
                               )


class Place(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    name = models.CharField(max_length=100, unique=True)

    # User with Stripe connect and cashless federated server
    wallet = models.OneToOneField(Wallet, on_delete=models.PROTECT, related_name='place')

    stripe_connect_account = models.CharField(max_length=21, blank=True, null=True, editable=False)
    stripe_connect_valid = models.BooleanField(default=False)

    cashless_server_ip = models.GenericIPAddressField(blank=True, null=True, editable=False)
    cashless_server_url = models.URLField(blank=True, null=True, editable=False)
    cashless_server_key = models.CharField(max_length=100, blank=True, null=True, editable=False)

    admin = models.ManyToManyField(FedowUser, related_name='admin_places')

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
    nfc_tag_id = models.CharField(max_length=8, editable=False, db_index=True)
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