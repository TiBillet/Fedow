from django.utils import timezone
from rest_framework import serializers
from rest_framework_api_key.models import APIKey
from fedow_core.models import Place, FedowUser, Card, Wallet, Transaction
from fedow_core.utils import get_request_ip
import logging

logger = logging.getLogger(__name__)


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


class ConnectPlaceCashless(serializers.Serializer):
    uuid = serializers.PrimaryKeyRelatedField(queryset=Place.objects.all())
    ip = serializers.IPAddressField()
    url = serializers.URLField()
    apikey = serializers.CharField(max_length=41, min_length=41)

    def validate_uuid(self, value):
        place: Place = value
        self.place = place
        # Si place à déja été configuré, on renvoie un 400
        if place.cashless_server_ip or place.cashless_server_url or place.cashless_server_key:
            logger.error(f"{timezone.localtime()} Place already configured {self.context.get('request').data}")
            raise serializers.ValidationError("Place already configured")
        return value

    def validate_ip(self, value):
        request = self.context.get('request')
        if value != get_request_ip(request):
            logger.error(f"{timezone.localtime()} ERROR Place create Invalid IP {get_request_ip(request)}")
            raise serializers.ValidationError("Invalid IP")
        return value

    def validate(self, attrs):
        request = self.context.get('request')
        # Check if key is the temp given by the manual creation.
        key = request.META["HTTP_AUTHORIZATION"].split()[1]
        api_key = APIKey.objects.get_from_key(key)
        if self.place.wallet.key != api_key or 'temp_' not in api_key.name:
            logger.error(f"{timezone.localtime()} ERROR Place create Unauthorized {request.data}")
            raise serializers.ValidationError("Unauthorized")

        import ipdb; ipdb.set_trace()
        return attrs


class PlaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Place
        fields = (
            'uuid',
            'name',
        )

    def validate(self, attrs):
        return attrs


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
        ip = get_request_ip(self.context.get('request'))

        # Link card to user
        self.card.user = self.user
        self.card.save()

        # Api key generation
        api_key, self.key = APIKey.objects.create_key(name=self.user.email[:50])

        # Create wallet
        self.wallet = Wallet.objects.create(
            key=api_key,
            ip=ip,
            user=self.user
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
