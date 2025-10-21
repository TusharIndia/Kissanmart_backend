import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from urllib.parse import parse_qs

from .models import ChatMessage
from users.models import UserSession


class CommunityChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.group_name = 'community_chat'

        # Accept connection
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if text_data is None:
            return

        data = json.loads(text_data)
        message = data.get('message')

        # Ensure only authenticated users can send. If the scope user is not
        # authenticated, try to read a sessionToken from the websocket query
        # string (frontend sends ?sessionToken=...)
        user = self.scope.get('user')
        if not user or not getattr(user, 'is_authenticated', False):
            # try to parse query string for sessionToken
            try:
                qs = self.scope.get('query_string', b'').decode()
                params = parse_qs(qs)
                token = (params.get('sessionToken') or params.get('session_token') or [None])[0]
            except Exception:
                token = None

            if token:
                user = await database_sync_to_async(self.get_user_from_session)(token)

            if not user or not getattr(user, 'is_authenticated', False):
                # ignore or optionally send error
                await self.send(json.dumps({'error': 'authentication_required'}))
                return

        # Save message to DB. If we have an authenticated user, reuse their
        # persistent anonymous_id so the same user shows the same anon id.
        if user and getattr(user, 'is_authenticated', False):
            chat = await database_sync_to_async(lambda u=user, m=message: ChatMessage.objects.create(user=u, message=m, anonymous_id=u.anonymous_id))()
        else:
            chat = await database_sync_to_async(lambda m=message: ChatMessage.objects.create(message=m))()

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
