from django.core.management.base import BaseCommand, CommandError
from rest_framework_api_key.models import APIKey

from fedow_core.models import Federation


class Command(BaseCommand):
    help = 'Federation creation'

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('--name', type=str)
        parser.add_argument('--description', type=str)

    def handle(self, *args, **options):
        try:
            federation_name = options['name']
            description = options.get('description', None)

            if not federation_name:
                raise CommandError('Please provide a federation name')
            # if Federation.objects.filter(name=federation_name).exists():
            #     raise CommandError('Federation already exists')

            try:
                federation = Federation.objects.get(name=federation_name)
                self.stdout.write(self.style.WARNING(
                    f"Federation already exist : {federation.name}"), ending='\n')
            except Federation.DoesNotExist:
                federation = Federation.objects.create(name=federation_name, description=description)
                self.stdout.write(self.style.SUCCESS(
                    f"Federation succesfully created.\nNAME : {federation.name}\nUUID : {federation.uuid}"),
                    ending='\n')

        except Exception as e:
            raise CommandError(e)
