from django.urls import path
from .admin_views import (
    AdminProductListView,
    AdminProductDetailView,
    AdminProductStatsView,
    AdminProductUpdateView,
    AdminProductDeleteView,
    AdminSellerProductsView,
    AdminCategoryProductsView,
)
from users.api.admin_views import AdminAuthView

app_name = 'products_admin_api'

urlpatterns = [
    # Product management endpoints
    path('', AdminProductListView.as_view(), name='admin-product-list'),
    path('stats/', AdminProductStatsView.as_view(), name='admin-product-stats'),
    path('<uuid:product_uuid>/', AdminProductDetailView.as_view(), name='admin-product-detail'),
    path('<uuid:product_uuid>/update/', AdminProductUpdateView.as_view(), name='admin-product-update'),
    path('<uuid:product_uuid>/delete/', AdminProductDeleteView.as_view(), name='admin-product-delete'),
    
    # Seller-specific product endpoints
    path('sellers/<int:seller_id>/', AdminSellerProductsView.as_view(), name='admin-seller-products'),
    
    # Category-specific product endpoints
    path('categories/<str:category>/', AdminCategoryProductsView.as_view(), name='admin-category-products'),
]