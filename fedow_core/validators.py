import logging

from django.conf import settings
from rest_framework import serializers

from fedow_core.models import Place, OrganizationAPIKey, get_or_create_user, wallet_creator
from fedow_core.serializers import PlaceSerializer
from fedow_core.utils import get_public_key

logger = logging.getLogger(__name__)


class PlaceValidator(serializers.Serializer):
    place_domain = serializers.CharField(max_length=100)
    place_name = serializers.CharField(max_length=100)
    admin_email = serializers.EmailField()
    admin_pub_pem = serializers.CharField(max_length=500)

    def validate_place_name(self, value):
        if Place.objects.filter(name=value).exists():
            if settings.TEST:
                logger.warning("Place name already exists, mais on est en TEST !!")
            else :
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
        place_domain = self.validated_data['place_domain']

        # Création de l'utilisateur admin
        try :
            user, created = get_or_create_user(admin_email, public_pem=admin_pub_pem)
        except Exception as e:
            raise serializers.ValidationError(f"Error get or create user : {e}")

        # Création de la place
        try :
            place = Place.objects.create(
                name=place_name,
                wallet=wallet_creator(),
                lespass_domain=place_domain,
            )
        except Exception as e :
            raise serializers.ValidationError(f"Error create place : {e}")

        #### RETOUR POUR LESPASS :

        # Ajout de l'admin dans la place
        place.admins.add(user)
        place.save()

        # Création de la clé API
        api_key, key = OrganizationAPIKey.objects.create_key(
            name=f"lespass_{place_name}:{user.email}",
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


