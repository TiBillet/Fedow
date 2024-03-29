
import logging
from collections import OrderedDict
from time import sleep

import stripe
from cryptography.hazmat.primitives.asymmetric import rsa
from django.utils import timezone
from rest_framework import serializers
from rest_framework.generics import get_object_or_404

from fedow_core.models import Place, FedowUser, Card, Wallet, Transaction, OrganizationAPIKey, Asset, Token, \
    get_or_create_user, Origin, asset_creator, Configuration, Federation, CheckoutStripe, wallet_creator
from fedow_core.serializers import PlaceSerializer
from fedow_core.utils import get_request_ip, get_public_key, dict_to_b64, verify_signature, dict_to_b64_utf8

logger = logging.getLogger(__name__)


class PlaceValidator(serializers.Serializer):
    place_name = serializers.CharField(max_length=100)
    admin_email = serializers.EmailField()
    admin_pub_pem = serializers.CharField(max_length=500)

    def validate_place_name(self, value):
        if Place.objects.filter(name=value).exists():
            raise serializers.ValidationError("Place name already exists")
        return value

    def validate_admin_pub_pem(self, value):
        try :
            pub = get_public_key(value)
            if pub.key_size < 2048:
                raise serializers.ValidationError("Public key size too small")
        except Exception as e:
            raise serializers.ValidationError("Public key not valid, must be 2048 min rsa key")
        return value

    def create_place(self):
        place_name = self.validated_data['place_name']
        admin_email = self.validated_data['admin_email']
        admin_pub_pem = self.validated_data['admin_pub_pem']

        # Création de l'utilisateur admin
        try :
            user, created = get_or_create_user(admin_email, public_pem=admin_pub_pem)
        except Exception as e:
            raise serializers.ValidationError(f"Error get or create user : {e}")

        # Création de la place
        place = Place.objects.create(
            name=place_name,
            wallet=wallet_creator(),
        )
        # Ajout de l'admin dans la place
        place.admins.add(user)
        # Création de la clé API
        api_key, key = OrganizationAPIKey.objects.create_key(
            name=f"tibillet_{place_name}:{user.email}",
            place=place,
            user=user,
        )

        # Serialization de la place :
        seralized_place = PlaceSerializer(place).data
        seralized_place.update({
            "key": key,
        })

        return seralized_place


    def validate(self, attrs):
        return attrs


