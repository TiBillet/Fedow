from django.core.management.base import BaseCommand, CommandError
from uuid import UUID

from fedow_core.models import Federation, Asset


class Command(BaseCommand):
    help = 'Federation creation'

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('--asset_uuid', type=str)
        parser.add_argument('--federation_uuid', type=str)

    def handle(self, *args, **options):
        try:
            federation_uuid = UUID(options['federation_uuid'])
            asset_uuid = UUID(options['asset_uuid'])

            asset = Asset.objects.get(uuid=asset_uuid)
            federation = Federation.objects.get(uuid=federation_uuid)
            if asset in federation.assets.all():
                raise CommandError('Asset already in federation')
            federation.assets.add(asset)
            federation.save()

            self.stdout.write(self.style.SUCCESS(
                f"Asset succesfully added."), ending='\n')
        except Exception as e:
            raise CommandError(e)