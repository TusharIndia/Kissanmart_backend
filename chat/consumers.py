import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from urllib.parse import parse_qs

from .models import ChatMessage
from users.models import UserSession


logger = logging.getLogger(__name__)


def _group_for_user(user):
    """Return the chat group name for a given user or None if invalid."""
    if not user or not getattr(user, 'is_authenticated', False):
        return None
    if getattr(user, 'user_type', None) == 'smart_seller':
        return 'chat_smart_seller'
    if getattr(user, 'user_type', None) == 'smart_buyer':
        buyer_cat = getattr(user, 'buyer_category', None)
        if buyer_cat in ('shopkeeper', 'mandi_owner', 'community'):
            return f'chat_smart_buyer_{buyer_cat}'
    return None


class CommunityChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Accept connection first so we can reply with errors if needed
        await self.accept()

        # Resolve authenticated user from scope (QuerySessionAuthMiddleware or
        # AuthMiddlewareStack should have populated scope['user']). As a
        # defensive fallback the consumer itself can attempt to resolve a
        # sessionToken from the query string, but middleware should already do
        # this in normal operation.
        user = self.scope.get('user')
        if not user or not getattr(user, 'is_authenticated', False):
            try:
                qs = self.scope.get('query_string', b'').decode()
                from urllib.parse import parse_qs
                params = parse_qs(qs)
                token = (params.get('sessionToken') or params.get('session_token') or [None])[0]
            except Exception:
                token = None

            if token:
                user = await database_sync_to_async(self.get_user_from_session)(token)

        # If still not authenticated, inform client and close
        if not user or not getattr(user, 'is_authenticated', False):
            await self.send(json.dumps({'error': 'authentication_required'}))
            await self.close()
            return

        # Determine the chat group for this user and store it
        group_name = _group_for_user(user)
        if not group_name:
            await self.send(json.dumps({'error': 'unauthorized_role_or_category'}))
            await self.close()
            return

        self.user = user
        self.group_name = group_name

        # Log connection for debugging purposes
        try:
            uid = getattr(user, 'id', None)
            logger.info('WS connect: user_id=%s user_type=%s buyer_category=%s joined=%s', uid, getattr(user, 'user_type', None), getattr(user, 'buyer_category', None), self.group_name)
        except Exception:
            logger.exception('Failed logging websocket connect')

        # Add to the resolved group
        await self.channel_layer.group_add(self.group_name, self.channel_name)

    async def disconnect(self, close_code):
        # guard in case connect failed before setting group_name
        if getattr(self, 'group_name', None):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if text_data is None:
            return

        data = json.loads(text_data)
        message = data.get('message')

        # Use the resolved user from connect
        user = getattr(self, 'user', None) or self.scope.get('user')
        if not user or not getattr(user, 'is_authenticated', False):
            await self.send(json.dumps({'error': 'authentication_required'}))
            return

        # Defensive check: ensure the sender's account resolves to the same
        # group the socket joined. This prevents messages from one account from
        # being broadcast into a different role's group if there's a mismatch
        # (e.g. due to frontend sending the wrong session token).
        expected_group = _group_for_user(user)
        if expected_group != getattr(self, 'group_name', None):
            logger.warning('Group mismatch: socket_group=%s sender_expected_group=%s user_id=%s', getattr(self, 'group_name', None), expected_group, getattr(user, 'id', None))
            await self.send(json.dumps({'error': 'group_mismatch'}))
            return
        # Save message to DB. For authenticated users reuse their anonymous_id
        # and tag the message with the resolved channel/group.
        chat = await database_sync_to_async(lambda u=user, m=message, ch=self.group_name: ChatMessage.objects.create(user=u, message=m, anonymous_id=u.anonymous_id, channel=ch))()

        payload = {
            'anonymous_id': str(chat.anonymous_id),
            'message': chat.message,
            'timestamp': chat.timestamp.isoformat(),
        }

        # Broadcast to group
        await self.channel_layer.group_send(self.group_name, {
            'type': 'chat.message',
            'payload': payload,
        })

    async def chat_message(self, event):
        payload = event.get('payload')
        await self.send(text_data=json.dumps(payload))

    @staticmethod
    def get_user_from_session(token):
        try:
            session = UserSession.objects.filter(session_token=token, is_active=True).select_related('user').first()
            if not session:
                return None
            if session.is_expired():
                return None
            return session.user
        except Exception:
            return None
