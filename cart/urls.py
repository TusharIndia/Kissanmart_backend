from django.urls import path, include

app_name = 'cart'

urlpatterns = [
    path('', include('cart.api.urls')),
]