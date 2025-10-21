"""
WSGI config for kissanmart project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/wsgi/
"""

import os
from django.core.wsgi import get_wsgi_application

# Keep the original WSGI application available for WSGI servers
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'kissanmart.settings')

# Traditional WSGI application (for servers like Gunicorn in WSGI mode)
wsgi_application = get_wsgi_application()

# Also provide an ASGI application that mirrors the behavior in asgi.py
# so production deployments that expect an ASGI module can import this
# module and get the proper ProtocolTypeRouter for HTTP and WebSocket.
try:
	# Import ASGI components lazily; they may not be installed in pure WSGI environments
	from django.core.asgi import get_asgi_application
	from channels.routing import ProtocolTypeRouter, URLRouter
	from channels.auth import AuthMiddlewareStack
	from .ws_auth import QuerySessionAuthMiddleware

	# Initialize Django ASGI app
	django_asgi_app = get_asgi_application()

	# Import routing after Django setup
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
except Exception:
	# If ASGI/Channels aren't available, fall back to exposing WSGI application
	# as `application` so imports that expect it still work.
	
	application = wsgi_application
