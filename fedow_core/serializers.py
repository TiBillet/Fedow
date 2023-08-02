from rest_framework import serializers

from fedow_core.models import Transaction


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