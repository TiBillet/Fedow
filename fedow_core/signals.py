import requests
from django.conf import settings
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from fedow_core.models import Transaction, Place


@receiver(post_save, sender=Transaction)
def transaction_webhook_new_membership(sender, instance: Transaction, created, **kwargs):
    # Webhook vers Lespass pour mettre a jour la liste des adhésions lorsqu'elle est faite depuis LaBoutik
    # Si primary card et pas de chekout stripe, ce n'est pas réalisé depuis Lespass.
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
