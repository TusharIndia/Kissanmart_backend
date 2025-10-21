"""
ASGI config for kissanmart project.

It exposes the ASGI callable as a module-level variable named ``application``.
"""

import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from .ws_auth import QuerySessionAuthMiddleware

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'kissanmart.settings')

# ✅ Initialize Django first
django_asgi_app = get_asgi_application()

# ✅ Import chat routing AFTER Django setup
import chat.routing

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    # Apply QuerySessionAuthMiddleware first so `sessionToken` query param can
    # authenticate sockets. Then pass through AuthMiddlewareStack for fallback
    # session/cookie authentication.
    "websocket": QuerySessionAuthMiddleware(
        AuthMiddlewareStack(
            URLRouter(chat.routing.websocket_urlpatterns)
        )
    ),
})
