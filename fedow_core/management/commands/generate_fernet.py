from django.core.management.base import BaseCommand, CommandError
import os, base64


from cryptography.fernet import Fernet

class Command(BaseCommand):
    help = 'Salt generation'

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS(
                f"{Fernet.generate_key().decode('utf-8')}"
            ), ending='\n')
