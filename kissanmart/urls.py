from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from users.api.admin_views import AdminAuthView
from django.views.decorators.csrf import csrf_exempt

# Import OAuth views so we can add short alias routes (legacy client URLs)
from users.api.views import OAuthCallbackView, OAuthTokenView, LinkSocialView

def welcome_view(request):
    """Simple welcome endpoint used for health checks."""
    return JsonResponse({"message": "Welcome to Kissanmart server"}, status=200)

urlpatterns = [
    # Lightweight root welcome endpoint for health/welcome checks
    path('admin/', admin.site.urls),
    path('api/users/', include('users.urls')),
    path('api/products/', include('products.api.urls')),
    path('api/cart/', include('cart.urls')),
    path('api/orders/', include('orders.api.urls')),
    # Admin Authentication
    path('api/admin/auth/', AdminAuthView.as_view(), name='admin-auth'),
    # Admin Product APIs
    path('api/admin/products/', include('products.api.admin_urls')),
    # API Documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    path('', welcome_view, name='welcome'),
]

# Backwards-compatible short paths used by some frontends: /api/auth/... -> users app
urlpatterns += [
    path('api/auth/oauth/callback/', csrf_exempt(OAuthCallbackView.as_view()), name='oauth_callback_alias'),
    path('api/auth/oauth/token/', csrf_exempt(OAuthTokenView.as_view()), name='oauth_token_alias'),
    path('api/auth/oauth/link/', (LinkSocialView.as_view()), name='oauth_link_alias'),
]

# Chat API (messages retrieval)
urlpatterns += [
    path('api/chat/', include('chat.api.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
