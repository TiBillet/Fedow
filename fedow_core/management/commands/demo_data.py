import logging

from django.core.management import call_command
from django.core.management.base import BaseCommand

from fedow_core.models import Place, Asset, Card, Origin

logger = logging.getLogger(__name__)

# test : https://demo.tibillet.localhost/qr/0c9e2d94-0628-45df-b30d-c974ee4cc3e4/
class Command(BaseCommand):
    def handle(self, *args, **options):
        call_command("places",
                     '--create',
                     '--name', 'TestPlace',
                     '--email', 'jturbeaux@pm.me',
                     '--description', 'Un lieu pour lancer des test')

        testplace = Place.objects.get(name='TestPlace')

        call_command("assets",
                     '--create',
                     '--name', 'TestPlaceAsset',
                     '--currency_code', 'TPA',
                     '--wallet_origin', f'{testplace.wallet.uuid}',
                     '--category', Asset.TOKEN_LOCAL_FIAT)

        origin, created = Origin.objects.get_or_create(
            place=testplace,
            generation=1
        )


        card1, created = Card.objects.get_or_create(
            number_printed='2c9e2d94'.upper(),
            qrcode_uuid='2c9e2d94-0628-45df-b30d-c974ee4cc3e4',
            first_tag_id='2b69895a'.upper(),
            complete_tag_id_uuid='2b69895a-ade5-4a4b-aa9b-5caaa5492ab7',
            origin=origin,
        )

        card2, created = Card.objects.get_or_create(
            number_printed='1c9e2d94'.upper(),
            qrcode_uuid='1c9e2d94-0628-45df-b30d-c974ee4cc3e4',
            first_tag_id='1b69895a'.upper(),
            complete_tag_id_uuid='1b69895a-ade5-4a4b-aa9b-5caaa5492ab7',
            origin=origin,
        )

        # card.primary_places

