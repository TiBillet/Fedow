import os

from rest_framework_api_key.models import APIKey

from fedow_core.models import Configuration, Wallet

try:
    config = Configuration.get_solo()
    print('Configuration and master wallet already exists')
except Configuration.DoesNotExist:

    instance_name = os.environ.get('DOMAIN','fedow.betabillet.tech')
    primary_key, key = APIKey.objects.create_key(name=instance_name)

    primary_wallet = Wallet.objects.create(
        name="Primary",
        ip="127.0.0.1",
        key=primary_key,
    )

    print(key)
