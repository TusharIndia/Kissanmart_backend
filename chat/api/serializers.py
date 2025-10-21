from rest_framework import serializers
from chat.models import ChatMessage


class ChatMessageSerializer(serializers.ModelSerializer):
    anonymous_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = ChatMessage
        fields = ['id', 'anonymous_id', 'message', 'timestamp']

