from rest_framework import serializers
from rest_framework_api_key.models import APIKey
from django.contrib.auth.hashers import make_password, check_password
from fedow_core.models import Transaction, Place, FedowUser, Card, Wallet
from fedow_core.utils import get_client_ip


def get_or_create_fedowuser(email):
    try:
        user = FedowUser.objects.get(email=email.lower())
        created = False
    except FedowUser.DoesNotExist:
        user = FedowUser.objects.create(
            email=email.lower()
        )
        created = True
    return user, created

class PlaceSerializer(serializers.Serializer):
    class Meta:
        model = Place
        fields = (
            'name'
        )


class WalletCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    uuid_card = serializers.UUIDField()

    def validate_email(self, value):
        self.user, created = get_or_create_fedowuser(email=value)
        if not created:
            raise serializers.ValidationError("User already exists")

        return self.user.email

    def validate_uuid_card(self, value):
        try:
            self.card = Card.objects.get(uuid=value)
        except Card.DoesNotExist:
            raise serializers.ValidationError("Card does not exist")

        if self.card.user:
            raise serializers.ValidationError("Card not available")

        return self.card.uuid

    def validate(self, attrs):
        # Get ip
        ip = get_client_ip(self.context.get('request'))

        # Link card to user
        self.card.user = self.user
        self.card.save()

        # Api key generation
        api_key, self.key = APIKey.objects.create_key(name=self.user.email[:50])

        # Create wallet
        self.wallet =Wallet.objects.create(
            key = api_key,
            ip = ip,
            user = self.user
        )

        return attrs

class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = (
            "uuid",
            "sender",
            "receiver",
            "token",
            "date",
            "amount",
            "comment",
        )