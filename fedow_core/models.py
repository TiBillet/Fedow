import hashlib
import json
import logging
import os
from unicodedata import category
from uuid import uuid4

import stripe
from cryptography.hazmat.primitives.asymmetric import rsa
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser
from django.core.cache import cache
from django.core.signing import Signer
from django.db import models
from django.db.models import UniqueConstraint, Q, Sum
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from rest_framework_api_key.models import AbstractAPIKey
from solo.models import SingletonModel
from stdimage import JPEGField
from stdimage.validators import MaxSizeValidator, MinSizeValidator
from stripe import InvalidRequestError

from fedow_core.utils import get_public_key, fernet_decrypt, fernet_encrypt, rsa_generator, utf8_b64_to_dict

logger = logging.getLogger(__name__)


### STRIPE


class CheckoutStripe(models.Model):
    # Si recharge, un paiement stripe doit être lié
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=True)
    datetime = models.DateTimeField(auto_now_add=True)
    checkout_session_id_stripe = models.CharField(max_length=80, editable=False, blank=True, null=True)
    asset = models.ForeignKey('Asset', on_delete=models.PROTECT,
                              related_name='checkout_stripe')
    CREATED, OPEN, PROGRESS, EXPIRE, PAID, WALLET_PRIMARY_OK, WALLET_USER_OK, CANCELED, ERROR = (
        'N', 'O', 'G', 'E', 'P', 'W', 'V', 'C', 'R')
    STATUT_CHOICES = (
        (CREATED, 'Créée'),
        (OPEN, 'En attente de paiement'),
        (PROGRESS, 'En cours de traitement'),
        (PAID, 'Payé'),
        (EXPIRE, 'Expiré'),
        (WALLET_PRIMARY_OK, 'Wallet primaire chargé'),  # wallet primaire chargé
        (WALLET_USER_OK, 'Wallet user chargé'),  # wallet chargé
        (CANCELED, 'Annulée'),
        (ERROR, 'en erreur'),
    )
    status = models.CharField(max_length=1, choices=STATUT_CHOICES, default=CREATED,
                              verbose_name="Statut de la commande")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='checkout_stripe')
    metadata = models.CharField(editable=False, db_index=False, max_length=500)

    def unsign_metadata(self):
        signer = Signer()
        return utf8_b64_to_dict(signer.unsign(self.metadata))

    def get_stripe_checkout(self):
        config = Configuration.get_solo()
        stripe.api_key = config.get_stripe_api()
        checkout = stripe.checkout.Session.retrieve(self.checkout_session_id_stripe)
        return checkout

    def refund_payment_intent(self, amount):
        if not amount :
            raise Exception(f"CheckoutStripe Refund : {self.uuid} without amount")
        config = Configuration.get_solo()
        stripe.api_key = config.get_stripe_api()
        checkout = stripe.checkout.Session.retrieve(self.checkout_session_id_stripe)
        payment_intent = checkout.payment_intent
        try :
            refund = stripe.Refund.create(
                payment_intent=payment_intent,
                reason='requested_by_customer',
                amount=amount,
            )
        except InvalidRequestError as e:
            logger.error(f"CheckoutStripe Refund InvalidRequestError {e}")
            raise Exception(f"CheckoutStripe Refund InvalidRequestError {e}")
        except Exception as e:
            logger.error(f"CheckoutStripe Refund Exception : {e}")
            raise e

        return refund


    def __str__(self):
        self.user: FedowUser
        return f"{self.user.email} {self.status}"


## BLOCKCHAIN PART

class Asset(models.Model):
    # One asset per currency
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=False)
    name = models.CharField(max_length=100, unique=True)
    currency_code = models.CharField(max_length=3)
    archive = models.BooleanField(default=False)

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

    wallet_origin = models.ForeignKey('Wallet', on_delete=models.PROTECT,
                                      related_name='assets_created',
                                      help_text="Lieu ou configuration d'origine",
                                      )

    def place_origin(self):
        if self.wallet_origin.is_place():
            return self.wallet_origin.place
        return None

    STRIPE_FED_FIAT = 'FED'
    TOKEN_LOCAL_FIAT = 'TLF'
    TOKEN_LOCAL_NOT_FIAT = 'TNF'
    TIME = 'TIM'
    FIDELITY = 'FID'
    BADGE = 'BDG'
    SUBSCRIPTION = 'SUB'

    CATEGORIES = [
        (TOKEN_LOCAL_FIAT, _('Fiduciaire')),
        (TOKEN_LOCAL_NOT_FIAT, _('Cadeau')),
        (STRIPE_FED_FIAT, _('Fiduciaire fédérée')),
        (TIME, _("Monnaie temps")),
        (FIDELITY, _("Points de fidélité")),
        (BADGE, _("Badgeuse/Pointeuse")),
        (SUBSCRIPTION, _('Adhésion ou abonnement')),
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
        return self.tokens.aggregate(total_value=Sum('value'))['total_value'] or 0

    def total_in_place(self):
        return self.tokens.filter(wallet__place__isnull=False).aggregate(total_value=Sum('value'))['total_value'] or 0

    def total_in_wallet_not_place(self):
        return self.tokens.filter(wallet__place__isnull=True).aggregate(total_value=Sum('value'))['total_value'] or 0

    # def total_in_wallet_by_card_origin(self):
    #     return Token.objects.filter(
    #         wallet__place__isnull=True,
    #         asset__category=Asset.STRIPE_FED_FIAT,
    #         value__gt=0).filter(
    #         Q(wallet__user__cards__isnull = False) | Q(wallet__card_ephemere__isnull=False)
    #     ).values('wallet__user__cards__origin__place__name')

    # Retourne uns string de nom
    def place_federated_with(self):
        places = set()
        for fed in self.federations.all():
            for place in fed.places.all():
                places.add(place)
        if len(places) > 0:
            places_name = [place.name for place in places]
            return ", ".join(places_name)
        else:
            return _("No place federated with this asset")

    # Retourne une list d'uuid place
    def place_uuid_federated_with(self):
        places = set()
        for fed in self.federations.all():
            for place in fed.places.all():
                places.add(place)
        return [place.uuid for place in places]

    def is_stripe_primary(self):
        if (self.wallet_origin == Configuration.get_solo().primary_wallet
                and self.id_price_stripe != None
                and self.category == Asset.STRIPE_FED_FIAT):
            return True
        return False

    def get_id_price_stripe(self,
                            force_create=False,
                            ):

        if self.id_price_stripe and not force_create:
            return self.id_price_stripe

        stripe_key = Configuration.get_solo().get_stripe_api()
        if not stripe_key:
            logger.warning("No stripe key for create refill product")
            return None

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

        return self.id_price_stripe

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

    #Todo: plus utile, private stockée dans Lespass
    private_pem = models.CharField(max_length=2048, editable=False, null=True, blank=True)

    public_pem = models.CharField(max_length=512, editable=False, null=True, blank=True)

    ip = models.GenericIPAddressField(verbose_name="Ip source", default='0.0.0.0')

    def get_name(self):
        if self.name:
            return self.name
        elif getattr(self, 'place', None):
            return self.place.name
        elif getattr(self, 'primary', None):
            return "Primary"
        return f"{str(self.uuid)[:8]}"

    def is_primary(self):
        # primary is the related name of the Wallet Configuration foreign key
        # On peux récupérer cet object dans les controleurs de cette façon : Wallet.objects.get(primary__isnull=False)
        if getattr(self, 'primary', False):
            # le self.primary devrait suffire (config est un singleton),
            # mais on vérifie quand même
            if self.primary == Configuration.get_solo():
                return True
        return False

    def is_place(self):
        if getattr(self, 'place', False):
            return True
        return False

    def public_key(self) -> rsa.RSAPublicKey:
        return get_public_key(self.public_pem)

    def has_user_card(self) -> bool:
        if hasattr(self, 'user'):
            return self.user.cards.count() > 0
        return False

    # LA PRIVATE DOIT ETRE EXTERIEUR A FEDOW !
    # def private_key(self) -> rsa.RSAPrivateKey:
    #     return get_private_key(self.private_pem)

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

    def asset_uuid(self):
        return self.asset.uuid

    def asset_name(self):
        return self.asset.name

    def asset_category(self):
        return self.asset.category

    def is_primary_stripe_token(self):
        if self.asset.is_stripe_primary() and self.wallet.is_primary():
            return True
        return False

    def last_transaction(self):
        # The transaction the most recent of the wallet.
        # exclude transaction Fusion
        #TODO: mettre en cache, souvent appelé
        return self.asset.transactions.filter(
            Q(sender=self.wallet) | Q(receiver=self.wallet)
        ).order_by('datetime').last()

    def last_transaction_datetime(self):
        last_transaction = self.last_transaction()
        if last_transaction:
            return last_transaction.datetime
        return None

    def start_membership_date(self):
        # Only for membership asset
        if self.asset.category == Asset.SUBSCRIPTION :
            last_transaction: Transaction = self.last_transaction()
            if last_transaction:
                if last_transaction.subscription_start_datetime:
                    return last_transaction.subscription_start_datetime
                return last_transaction.datetime
        return None

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
    metadata = models.JSONField(blank=True, null=True)

    NONE, ANNUAL, CIVIL, MONTHLY, WEEKLY, DAILY, HOURLY = 'NO', 'YEA', 'CIV', 'MON', 'WEK', 'DAY', 'HOR'
    TYPE_SUB = (
        (NONE, 'None'),
        (ANNUAL, 'Annuel'),
        (CIVIL, 'Civil'),
        (MONTHLY, 'Mensuel'),
        (WEEKLY, 'Hebdomadaire'),
        (DAILY, 'Journalier'),
        (HOURLY, 'Horaire'),
    )

    subscription_type = models.CharField(max_length=3, choices=TYPE_SUB, default=NONE)
    subscription_first_datetime = models.DateTimeField(blank=True, null=True)
    subscription_start_datetime = models.DateTimeField(blank=True, null=True)

    # auto_now dans la fonction save. Si on utilise auto_now, le verify hash n'aura pas la même date car il est créé après le save, donc après le hash.
    last_check = models.DateTimeField(blank=True, null=True)

    FIRST, SALE, CREATION, REFILL, TRANSFER, SUBSCRIBE, BADGE, FUSION, REFUND, VOID = 'FST', 'SAL', 'CRE', 'REF', 'TRF', 'SUB', 'BDG', 'FUS', 'RFD', 'VID'
    TYPE_ACTION = (
        (FIRST, "Premier bloc"),
        (SALE, "Vente d'article"),
        (CREATION, 'Creation monétaire'),
        (REFILL, 'Recharge'),
        (TRANSFER, 'Transfert'),
        (SUBSCRIBE, 'Abonnement ou adhésion'),
        (BADGE, 'Badgeuse'),
        (FUSION, 'Fusion de deux wallets'),
        (REFUND, 'Remboursement'),
        (VOID, 'Dissocciation de la carte et du wallet user'),
    )
    action = models.CharField(max_length=3, choices=TYPE_ACTION, default=SALE)

    def dict_for_hash(self):
        dict_for_hash = {
            'sender': f"{self.sender.uuid}",
            'receiver': f"{self.receiver.uuid}",
            'asset': f"{self.asset.uuid}",
            'amount': f"{self.amount}",
            'datetime': f"{self.datetime.isoformat()}",
            'subscription_type': f"{self.subscription_type}",
            'subscription_first_datetime': f"{self.subscription_first_datetime.isoformat()}" if self.subscription_first_datetime else None,
            'subscription_start_datetime': f"{self.subscription_start_datetime.isoformat()}" if self.subscription_start_datetime else None,
            'last_check': f"{self.last_check.isoformat()}" if self.last_check else None,
            'action': f"{self.action}",
            'card': f"{self.card.uuid}" if self.card else None,
            'primary_card': f"{self.primary_card.uuid}" if self.primary_card else None,
            'comment': f"{self.comment}",
            'metadata': f"{self.metadata}",
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
        # TODO: Checker le lancement via update et create. Utiliser les nouveaux validateur en db de django 5 ?
        if settings.DEBUG:
            logger.info(f"SAVE TRANSACTION {self.action}")
        if not self.datetime:
            self.datetime = timezone.localtime()

        # auto_now simulé dans la fonction save pour lash check.
        # Si on utilise auto_now, le verify hash n'aura pas la même date car il est créé après le save, donc après le hash.
        self.last_check = timezone.localtime()

        token_sender = Token.objects.get(wallet=self.sender, asset=self.asset)

        token_receiver = Token.objects.get(wallet=self.receiver, asset=self.asset)

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
                # TODO: Chekout stripe must be unique and not used
                assert self.checkout_stripe != None, "Checkout stripe must be set for create federated money."
            else:
                # besoin d'une carte primaire pour création monétaire
                assert self.asset.wallet_origin == self.sender, "Asset wallet_origin must be the place"
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
            assert self.sender.place.wallet == self.asset.wallet_origin, "Subscription wallet_origin must be the place"

            # L'abonnement peut se faire sur une carte avec wallet epehemere
            # assert self.receiver.user, "Receiver must be a user wallet"

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
                # TODO: Chekout stripe must be unique and not used
                assert self.checkout_stripe != None, "Checkout stripe must be set for refill."
            else:
                assert self.asset.wallet_origin == self.sender, "Asset wallet_origin must be the place"
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
            assert self.asset in self.receiver.place.accepted_assets(), "Asset must be accepted by place"
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

        if self.action == Transaction.FUSION:
            assert self.amount == token_sender.value, "Amount must be equal to token sender value, we clear the ephemeral wallet"
            assert self.card.wallet_ephemere, "Card must be associated to ephemeral wallet"
            assert not hasattr(self.card.wallet_ephemere, 'user'), "Wallet ephemere must not be associated to user"
            assert not self.card.user, "Card must not be associated to user"
            assert self.receiver.user, "Receiver must be a user wallet"

            token_sender.value -= self.amount
            token_receiver.value += self.amount
            # import ipdb; ipdb.set_trace()

        if self.action == Transaction.REFUND:
            assert self.amount == token_sender.value, "Amount must be equal to token sender value, we clear the ephemeral wallet"

            # Pour les assets locaux et cadeaux :
            if self.asset.category != Asset.STRIPE_FED_FIAT:
                assert self.receiver.is_place(), "Receiver must be a place wallet"
                assert self.asset.wallet_origin == self.receiver, "Asset wallet_origin must be the place"

            # Decrement token user qui se fait rembourser
            token_sender.value -= self.amount
            # Ne pas incrémenter le wallet place si c'est un remboursement d'asset locale,
            # le lieu a remboursé en espèce, il ne stocke plus l'asset

            # Si c'est un asset fédéré et un lieu qui rembourse, on incrémente le wallet du lieu
            # pour pouvoir le rembourser dans un deuxième temps : il a remboursé en espèce l'user
            # Si c'est STRIPE FED mais pas lieu : c'est un remboursement d'user en ligne
            if (self.asset.category == Asset.STRIPE_FED_FIAT
                    and self.receiver.is_place())\
                    and not self.receiver.is_primary() :
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


# #
# #
# class Passage(models.Model):
#     employee = models.ForeignKey(User, on_delete=models.CASCADE)
#     timestamp = models.DateTimeField(auto_now_add=True)
#
#     @classmethod
#     def work_periods(cls, employee, date):
#         passages = list(cls.objects.filter(employee=employee, timestamp__date=date).order_by('timestamp'))
#         if len(passages) % 2 != 0:
#             # Ajoute un passage de sortie fictif à l'heure de fermeture du bureau
#             closing_time = time(23, 59)  # Heure de fermeture du bureau
#             closing_datetime = datetime.combine(date, closing_time)
#             passages.append(Passage(employee=employee, timestamp=closing_datetime))
#         return zip(passages[::2], passages[1::2])
#
#     @classmethod
#     def work_hours(cls, employee, date):
#         periods = cls.work_periods(employee, date)
#         return sum((end.timestamp - start.timestamp).total_seconds() / 3600 for start, end in periods)
#
#     @classmethod
#     def is_half_day(cls, employee, date):
#         return cls.work_hours(employee, date) < 4
#

class Federation(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=False)
    name = models.CharField(max_length=100, unique=True)
    places = models.ManyToManyField('Place', related_name='federations')
    assets = models.ManyToManyField('Asset', related_name='federations')
    description = models.TextField(blank=True, null=True)

    def get_assets_names(self):
        return " - ".join([asset.name for asset in self.assets.all()])

    def get_places_names(self):
        return " - ".join([place.name for place in self.places.all()])

    def __str__(self):
        return f"{self.name} : {','.join([place.name for place in self.places.all()])}"

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        cache.clear()
        logger.info(f'CLEAR cache')
        super().save(force_insert, force_update, using, update_fields)


# class ReadOnlyAPIKey(AbstractAPIKey):
#     class meta():
#         verbose_name = "Read only Api Key"
#         verbose_name_plural = "Read only Api Key"


class CreatePlaceAPIKey(AbstractAPIKey):
    class meta():
        verbose_name = "Place creator API key"
        verbose_name_plural = "Place creator API keys"


class Configuration(SingletonModel):
    name = models.CharField(max_length=100)
    domain = models.URLField()

    # Clé API dans le moteur billetterie/adhésion
    # A Créer à la main,
    # puis l'entrer dans la billetterie ave la fonction : set_fedow_create_place_apikey
    create_place_apikey = models.OneToOneField(CreatePlaceAPIKey,
                                               on_delete=models.CASCADE,
                                               null=True,
                                               related_name='configuration',
                                               help_text="Clé API root de la billetterie qui permet de créer des nouveau lieux")

    # Wallet pour monnaie fédérée
    primary_wallet = models.OneToOneField(Wallet, on_delete=models.PROTECT, related_name='primary')
    stripe_endpoint_secret_enc = models.CharField(max_length=100, blank=True, null=True, editable=False)
    stripe_api_key = models.CharField(max_length=100, blank=True, null=True, editable=False)

    def set_stripe_api(self, string):
        self.stripe_api_key = fernet_encrypt(string)
        cache.clear()
        self.save()
        return True

    def get_stripe_api(self):
        if settings.STRIPE_TEST:
            return os.environ.get('STRIPE_KEY_TEST')
        else:
            # The stripe api key is not set
            # You have to set it mannualy with self.set_stripe_api(api_key)
            if not self.stripe_api_key:
                stripe_key_from_env = os.environ.get("STRIPE_KEY")
                if not stripe_key_from_env:
                    logger.error("No stripe key provided on .env > Return None")
                    return None
                self.set_stripe_api(stripe_key_from_env)

            return fernet_decrypt(self.stripe_api_key)

    def set_stripe_endpoint_secret(self, string):
        self.stripe_endpoint_secret_enc = fernet_encrypt(string)
        cache.clear()
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


class Place(models.Model):
    uuid = models.UUIDField(primary_key=True, default=uuid4, editable=False, db_index=False)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    # User with Stripe connect and cashless federated server
    wallet = models.OneToOneField(Wallet, on_delete=models.PROTECT, related_name='place')

    dokos_id = models.CharField(max_length=100, blank=True, null=True, editable=False)

    stripe_connect_account = models.CharField(max_length=21, blank=True, null=True, editable=False)
    stripe_connect_valid = models.BooleanField(default=False)

    cashless_server_ip = models.GenericIPAddressField(blank=True, null=True, editable=False)
    cashless_server_url = models.URLField(blank=True, null=True, editable=False)
    cashless_rsa_pub_key = models.CharField(max_length=512, blank=True, null=True, editable=False,
                                            help_text="Public rsa Key of cashless server for signature.")
    cashless_admin_apikey = models.CharField(max_length=256, blank=True, null=True, editable=False,
                                             help_text="Encrypted API key of cashless server admin.")

    lespass_domain = models.CharField(max_length=100, blank=True, null=True, editable=False)

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
        # logger.info(f'federated_with_{self.uuid} called')
        # print(f'federated_with_{self.uuid} called')
        places, assets, wallets = set(), set(), set()
        for federation in self.federations.all():
            places.update(federation.places.all())
            assets.update(federation.assets.filter(archive=False))
            wallets.update([place.wallet for place in federation.places.all()])

        # On a joute automatiquement l'asset stripe primaire
        assets.add(Asset.objects.get(category=Asset.STRIPE_FED_FIAT))

        # Les assets créé par le lieu
        assets.update(self.wallet.assets_created.filter(archive=False))
        # Soi-même
        wallets.add(self.wallet)
        places.add(self)

        # Mise en cache :
        feds = places, assets, wallets
        cache.set(f'federated_with_{self.uuid}', feds, 120)
        logger.debug(f'federated_with_{self.uuid} SET in cache')

        return feds

    def cached_federated_with(self):
        feds = cache.get(f'federated_with_{self.uuid}')
        if feds:
            logger.debug(f'federated_with_{self.uuid} GET from cache')
        else:
            feds = self.federated_with()

        places, assets, wallets = feds
        return places, assets, wallets

    def accepted_assets(self):
        place, assets, wallets = self.cached_federated_with()
        # import ipdb; ipdb.set_trace()
        return assets

    def wallet_federated_with(self):
        place, assets, wallets = self.cached_federated_with()
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

    # Pour les cartes qui ne possèdent pas encore d'utilisateur. Fusion avec le wallet de l'user lorsqu'il se déclare.
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

    def is_wallet_ephemere(self):
        if self.wallet_ephemere and not self.user:
            return True
        return False

    # def get_authority_delegation(self):
        # Le lieu d'origine doit faire parti de la fédération du lieu de la carte
        # card: Card = self
        # place_origin = card.origin.place
        # wallets = place_origin.wallet_federated_with()
        # return wallets

    def __str__(self):
        return f"{self.origin} : {self.number_printed}"

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
        # unique_together = [['place', 'user', 'name']]


### CREATORS TOOLS


def wallet_creator(ip=None, name=None, public_pem=None, generate_rsa=None):
    if ip is None:
        ip = "0.0.0.0"

    # Les clés ne sont pas stockée par default
    prv = None
    pub = None
    if generate_rsa:
        prv, pub = rsa_generator()
    elif public_pem:
        pub = public_pem

    wallet = Wallet.objects.create(
        name=name,
        ip=ip,
        private_pem=prv,
        public_pem=pub,
    )
    return wallet


def asset_creator(name: str = None,
                  currency_code: str = None,
                  category: str = None,
                  wallet_origin: Wallet = None,
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

    categories = [category_code for category_code, category_name in Asset.CATEGORIES]
    if category not in categories:
        raise ValueError('Category not in choices')

    # Vérification que l'asset et/ou le code n'existe pas
    try:
        Asset.objects.get(name=name)
        raise ValueError('Asset name already exist')
    except Asset.DoesNotExist:
        pass
    # try:
    #     Asset.objects.get(currency_code=currency_code)
    #     raise ValueError('Asset currency_code already exist')
    # except Asset.DoesNotExist:
    #     pass

    asset = Asset.objects.create(
        uuid=original_uuid if original_uuid else uuid4(),
        name=name,
        currency_code=currency_code,
        wallet_origin=wallet_origin,
        category=category,
        created_at=created_at,
    )

    # print(f"First block created for {asset.name}")
    # cache.clear()
    # print(f"cache cleared")
    return asset


def get_or_create_user(email, ip=None, wallet_uuid=None, public_pem=None):
    User: FedowUser = get_user_model()
    try:
        user = User.objects.get(email=email.lower())
        created = False

        # On vérifie la clé publique du wallet
        # Si elle est différente, on lève une erreur
        # Si la clé n'existe pas, c'est un user créé par le cashless, on la renseigne
        if public_pem and user.wallet:
            if not user.wallet.public_pem:
                user.wallet.public_pem = public_pem
                user.wallet.save()
            if user.wallet.public_pem != public_pem:
                raise ValueError('Public pem not match')

    except User.DoesNotExist:
        # Si on nous envoie le wallet dans la fonction (pour liaison de carte existante, par exemple)
        wallet = Wallet.objects.get(pk=wallet_uuid) if wallet_uuid \
            else wallet_creator(ip=ip, public_pem=public_pem)

        user = User.objects.create(
            email=email.lower(),
            username=email.lower(),
            wallet=wallet,
        )
        created = True

    return user, created
