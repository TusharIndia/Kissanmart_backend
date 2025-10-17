from django.urls import path, include
from rest_framework.routers import DefaultRouter
from cart.api.views import CartViewSet

# Create router for ViewSets
router = DefaultRouter()
router.register(r'cart', CartViewSet, basename='cart')

urlpatterns = [
    path('api/', include(router.urls)),
]