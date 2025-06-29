import sys

import requests
from django.conf import settings
from django.core.cache import cache
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from fedow_core.models import Transaction, Place, Asset, Token, logger


@receiver(post_save, sender=Transaction)
def transaction_webhook_new_membership(sender, instance: Transaction, created, **kwargs):
    # Webhook vers Lespass pour mettre a jour la liste des adhésions lorsqu'elle est faite depuis LaBoutik
    # Si primary card et pas de chekout stripe, ce n'est pas réalisé depuis Lespass.
    # if 'loaddata' in sys.argv:
    #     return  # Ne rien faire pendant le loaddata

    if (created and
            instance.action == Transaction.SUBSCRIBE and
            instance.sender.is_place() and
            not instance.checkout_stripe and
            instance.primary_card
    ):
        # Récupération du lieu
        place: Place = instance.sender.place
        url = place.lespass_domain
        requests.get(f"https://{url}/fwh/membership/{instance.uuid}",
                     verify=bool(not settings.DEBUG),
                     timeout=1)


@receiver(post_save, sender=Asset)
def first_block_for_new_asset(sender, instance: Asset, created, **kwargs):
    ## Création d'un nouvel asset ! besoin de faire le plremier block
    # if 'loaddata' in sys.argv:
    #     return  # Ne rien faire pendant le loaddata

    if created :
        asset:Asset = instance
        logger.info(f"############### CREATION FIRST BLOCK {instance.name}")
        wallet_origin = asset.wallet_origin
        # Création du token qui va envoyer et recevoir le premier block
        token = Token.objects.create(
            asset=asset,
            wallet=wallet_origin,
        )

        # Création du premier block
        first_block = Transaction.objects.create(
            ip="0.0.0.0",
            checkout_stripe=None,
            sender=wallet_origin,
            receiver=wallet_origin,
            asset=asset,
            amount=int(0),
            datetime=asset.created_at if asset.created_at else timezone.localtime(),
            action=Transaction.FIRST,
            card=None,
            primary_card=None,
        )

        print(f"First block created for {asset.name}")
        cache.clear()