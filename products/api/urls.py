from django.urls import path
from .views import (
    get_seller_products,
    add_product,
    update_product,
    delete_product,
    get_products_by_buyer_type,
    get_product_detail,
    list_products,
    get_mandi_prices,
    get_product_distance,
)

app_name = 'products_api'

urlpatterns = [
    # Seller Product endpoints (authenticated sellers)
    path('products/', get_seller_products, name='seller-products'),
    path('products/create/', add_product, name='add-product'),
    path('products/<uuid:uuid>/', get_product_detail, name='product-detail'),
    path('products/<uuid:uuid>/update/', update_product, name='update-product'),
    path('products/<uuid:uuid>/delete/', delete_product, name='delete-product'),
    path('products-by-buyer-type/', get_products_by_buyer_type, name='products-by-buyer-type'),

    # Image management removed: images handled via create/update payloads

    # Public product listing and mandi price
    path('products/list/', list_products, name='product-list'),
    path('products/mandi-price/', get_mandi_prices, name='mandi-prices'),
    path('products/<uuid:uuid>/distance/', get_product_distance, name='product-distance'),
]
