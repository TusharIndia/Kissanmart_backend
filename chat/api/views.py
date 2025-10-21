from rest_framework import generics, permissions
from chat.models import ChatMessage
from users.models import UserSession
from .serializers import ChatMessageSerializer
from django.db.models import Q


class ChatMessageListView(generics.ListAPIView):
    serializer_class = ChatMessageSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        # Prefer explicit channel query param
        channel = self.request.query_params.get('channel')
        qs = ChatMessage.objects.select_related('user').order_by('timestamp')
        if channel:
            # Include legacy messages that have no channel only if their
            # originating user matches the same role/category as the
            # requested channel. This prevents legacy messages from other
            # user types appearing in this channel.
            group = channel
            # derive role filter from group name
            if group == 'chat_smart_seller':
                legacy_user_q = Q(user__user_type='smart_seller')
            elif group.startswith('chat_smart_buyer_'):
                cat = group.split('chat_smart_buyer_', 1)[1]
                legacy_user_q = Q(user__user_type='smart_buyer') & Q(user__buyer_category=cat)
            else:
                legacy_user_q = Q()

            # Only include legacy messages that have a user and match the
            # role/category for this group
            return qs.filter(Q(channel=group) | (Q(channel__isnull=True) & Q(user__isnull=False) & legacy_user_q))

        # If no explicit channel provided, try to resolve from authenticated
        # user or sessionToken query param (mirrors websocket behavior).
        user = self.request.user if getattr(self.request, 'user', None) and self.request.user.is_authenticated else None
        if not user:
            token = self.request.query_params.get('sessionToken') or self.request.query_params.get('session_token')
            if token:
                try:
                    session = UserSession.objects.filter(session_token=token, is_active=True).select_related('user').first()
                    if session and not session.is_expired():
                        user = session.user
                except Exception:
                    user = None

        if user:
            from chat.consumers import _group_for_user
            group = _group_for_user(user)
            if group:
                # derive role filter from group
                if group == 'chat_smart_seller':
                    legacy_user_q = Q(user__user_type='smart_seller')
                elif group.startswith('chat_smart_buyer_'):
                    cat = group.split('chat_smart_buyer_', 1)[1]
                    legacy_user_q = Q(user__user_type='smart_buyer') & Q(user__buyer_category=cat)
                else:
                    legacy_user_q = Q()

                # Only include legacy messages that have a user and match the
                # role/category for this group
                return qs.filter(Q(channel=group) | (Q(channel__isnull=True) & Q(user__isnull=False) & legacy_user_q))

        # If we couldn't infer a channel or authenticate the requester,
        # don't return all messages (that would leak other user-type chats).
        # Require the frontend to pass an explicit `channel` or a valid
        # sessionToken so we can resolve the proper channel.
        return qs.none()


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

        # Resolve user from sessionToken query param if needed (mirror websocket auth)
        if not user:
            token = self.request.query_params.get('sessionToken') or self.request.query_params.get('session_token')
            if token:
                try:
                    session = UserSession.objects.filter(session_token=token, is_active=True).select_related('user').first()
                    if session and not session.is_expired():
                        user = session.user
                except Exception:
                    user = None

        # Determine channel: prefer explicit channel param, otherwise infer from user
        channel = self.request.query_params.get('channel')
        if not channel and user:
            try:
                from chat.consumers import _group_for_user
                channel = _group_for_user(user)
            except Exception:
                channel = None

        save_kwargs = {}
        if user:
            save_kwargs['user'] = user
            save_kwargs['anonymous_id'] = getattr(user, 'anonymous_id', None)
        elif anon:
            save_kwargs['anonymous_id'] = anon

        if channel:
            save_kwargs['channel'] = channel

        serializer.save(**save_kwargs)


class ChatMessageChannelView(generics.ListAPIView):
    """Strict channel history endpoint. Requires `?channel=` and returns only
    messages for that channel (including legacy messages authored by users of
    the same role/category). This endpoint should be used by the frontend when
    displaying a particular channel's history.
    """
    serializer_class = ChatMessageSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        channel = self.request.query_params.get('channel')
        if not channel:
            return ChatMessage.objects.none()

        qs = ChatMessage.objects.select_related('user').order_by('timestamp')

        # derive role filter from group name
        if channel == 'chat_smart_seller':
            legacy_user_q = Q(user__user_type='smart_seller')
        elif channel.startswith('chat_smart_buyer_'):
            cat = channel.split('chat_smart_buyer_', 1)[1]
            legacy_user_q = Q(user__user_type='smart_buyer') & Q(user__buyer_category=cat)
        else:
            legacy_user_q = Q()

        return qs.filter(Q(channel=channel) | (Q(channel__isnull=True) & Q(user__isnull=False) & legacy_user_q))
