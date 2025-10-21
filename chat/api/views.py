from rest_framework import generics, permissions
from chat.models import ChatMessage
from .serializers import ChatMessageSerializer


class ChatMessageListView(generics.ListAPIView):
    queryset = ChatMessage.objects.select_related('user').order_by('timestamp')
    serializer_class = ChatMessageSerializer
    permission_classes = [permissions.AllowAny]


class ChatMessageCreateView(generics.CreateAPIView):
    queryset = ChatMessage.objects.all()
    serializer_class = ChatMessageSerializer
    # Allow anonymous clients to post; consumer already enforces auth or uses session token
    permission_classes = [permissions.AllowAny]

    def perform_create(self, serializer):
        # If user is authenticated attach it, otherwise leave user null but
        # set anonymous_id if available from request (optional header/query)
        user = self.request.user if getattr(self.request, 'user', None) and self.request.user.is_authenticated else None
        # Support passing anonymous_id via X-Anonymous-Id header or query param
        anon = self.request.headers.get('X-Anonymous-Id') or self.request.query_params.get('anonymous_id')
        if user:
            # Use the user's persistent anonymous_id for consistency
            serializer.save(user=user, anonymous_id=getattr(user, 'anonymous_id', None))
        else:
            if anon:
                serializer.save(anonymous_id=anon)
            else:
                serializer.save()
