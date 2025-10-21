from rest_framework import serializers
from chat.models import ChatMessage


class ChatMessageSerializer(serializers.ModelSerializer):
    anonymous_id = serializers.UUIDField(read_only=True)
    channel = serializers.CharField(read_only=True)
    author_type = serializers.SerializerMethodField(read_only=True)
    author_category = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ChatMessage
        fields = ['id', 'anonymous_id', 'message', 'timestamp', 'channel', 'author_type', 'author_category']

    def get_author_type(self, obj):
        return getattr(obj.user, 'user_type', None) if getattr(obj, 'user', None) else None

    def get_author_category(self, obj):
        return getattr(obj.user, 'buyer_category', None) if getattr(obj, 'user', None) else None

