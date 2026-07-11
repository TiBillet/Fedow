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
        # Le webhook vers Lespass est best-effort : il ne doit JAMAIS bloquer ni
        # faire echouer la transaction Fedow (qui est deja committee et fait foi).
        # Sinon la vente en caisse LaBoutik attend la reponse, timeoute a 5s
        # (read timeout de create_sub) et derive : souscription creee cote Fedow
        # mais aucune vente enregistree cote LaBoutik.
        # Le timeout borne l'attente sous les 5s de LaBoutik ; le try/except evite
        # qu'un Lespass lent ou injoignable ne casse la souscription.
        # (Regression 18d73ed : le timeout=1 avait ete retire ici.)
        # / Best-effort webhook: must never block nor fail the committed Fedow transaction.
        try:
            reponse_webhook = requests.get(
                f"https://{url}/fwh/membership/{instance.uuid}",
                verify=bool(not settings.DEBUG),
                timeout=(1, 2))
            # Un 4xx/5xx de Lespass (500, 404 route/tenant absent) ne leve pas tout seul :
            # on force l'erreur pour rendre l'echec de propagation visible dans Sentry.
            # Le nominal Lespass (200/201/208) est en 2xx -> pas d'impact.
            # / Force error on 4xx/5xx so propagation failures surface in Sentry.
            reponse_webhook.raise_for_status()
        except requests.RequestException:
            # Adhesion NON propagee a Lespass (qui est la source de verite de l'adhesion).
            # logger.exception attache la stacktrace -> event Sentry complet (event_level=ERROR).
            # Rattrapage manuel : rejouer le GET ci-dessous (handler idempotent, 208 si deja la).
            # / Membership NOT propagated to Lespass (source of truth). Manual replay of the GET.
            logger.exception(
                f"transaction_webhook_new_membership : webhook Lespass ECHEC pour la "
                f"transaction {instance.uuid} — adhesion NON propagee a Lespass. "
                f"Rattrapage : GET https://{url}/fwh/membership/{instance.uuid}")


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