from urllib.parse import parse_qs

from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async



class QuerySessionAuthMiddleware(BaseMiddleware):
    """Middleware for Channels that looks for a session token in the WebSocket
    query string. Frontend sends `?sessionToken=...` so we try that first. If a
    valid UserSession is found and not expired, we set `scope['user']` to the
    corresponding user. Otherwise leave default authentication (AnonymousUser)
    so downstream AuthMiddlewareStack can still apply cookie/session auth.
    """

    async def __call__(self, scope, receive, send):
        # scope['query_string'] is bytes
        try:
            qs = scope.get('query_string', b'').decode()
        except Exception:
            qs = ''

        params = parse_qs(qs)
        # Accept either sessionToken (frontend) or session_token (views)
        token_list = params.get('sessionToken') or params.get('session_token') or []
        token = token_list[0] if token_list else None

        if token:
            user = await self.get_user_from_session(token)
            if user:
                scope['user'] = user
            else:
                # Local import to avoid app registry usage at module import time
                from django.contrib.auth.models import AnonymousUser
                scope['user'] = AnonymousUser()

        # If no token, leave scope alone so AuthMiddlewareStack can handle it
        return await super().__call__(scope, receive, send)

    @staticmethod
    @database_sync_to_async
    def get_user_from_session(token):
        try:
            # Import here to avoid accessing Django models at module import time
            from users.models import UserSession
            session = UserSession.objects.filter(session_token=token, is_active=True).select_related('user').first()
            if not session:
                return None
            if session.is_expired():
                return None
            return session.user
        except Exception:
            return None
