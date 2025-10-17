from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from cart.models import Cart, CartItem


class CartItemInline(admin.TabularInline):
    """Inline for cart items in cart admin"""
    model = CartItem
    extra = 0
    readonly_fields = ['id', 'unit_price', 'subtotal_display', 'added_at']
    fields = ['product', 'quantity', 'unit_price', 'subtotal_display', 'added_at']
    
    def subtotal_display(self, obj):
        if obj.id:
            return f"₹{obj.subtotal:,.2f}"
        return "-"
    subtotal_display.short_description = "Subtotal"


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    """Admin for shopping carts"""
    list_display = [
        'user_info', 'items_count', 'total_items', 'total_amount_display', 
        'created_at', 'updated_at'
    ]
    list_filter = ['created_at', 'updated_at']
    search_fields = ['user__mobile_number', 'user__full_name', 'user__email']
    readonly_fields = [
        'user', 'total_items', 'total_amount_display', 'items_count',
        'created_at', 'updated_at'
    ]
    inlines = [CartItemInline]
    
    def user_info(self, obj):
        return f"{obj.user.full_name} ({obj.user.get_identifier()})"
    user_info.short_description = "User"
    user_info.admin_order_field = 'user__full_name'
    
    def total_amount_display(self, obj):
        return f"₹{obj.total_amount:,.2f}"
    total_amount_display.short_description = "Total Amount"
    total_amount_display.admin_order_field = 'total_amount'
    
    def has_add_permission(self, request):
        return False  # Carts are created automatically


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    """Admin for cart items"""
    list_display = [
        'user_info', 'product_link', 'quantity', 'unit_price', 
        'subtotal_display', 'availability_status', 'added_at'
    ]
    list_filter = [
        'added_at', 'updated_at', 'product__is_published',
        'product__category', 'cart__user__user_type'
    ]
    search_fields = [
        'cart__user__mobile_number', 'cart__user__full_name',
        'product__title', 'product__category'
    ]
    readonly_fields = [
        'id', 'cart', 'unit_price', 'subtotal_display', 
        'availability_status', 'added_at', 'updated_at'
    ]
    fields = [
        'id', 'cart', 'product', 'quantity', 'unit_price', 
        'subtotal_display', 'availability_status', 'added_at', 'updated_at'
    ]
    
    def user_info(self, obj):
        return f"{obj.cart.user.full_name} ({obj.cart.user.get_identifier()})"
    user_info.short_description = "User"
    user_info.admin_order_field = 'cart__user__full_name'
    
    def product_link(self, obj):
        url = reverse('admin:products_product_change', args=[obj.product.id])
        return format_html('<a href="{}">{}</a>', url, obj.product.title)
    product_link.short_description = "Product"
    product_link.admin_order_field = 'product__title'
    
    def subtotal_display(self, obj):
        return f"₹{obj.subtotal:,.2f}"
    subtotal_display.short_description = "Subtotal"
    
    def has_add_permission(self, request):
        return False  # Cart items are added through API


# Custom admin site configurations
admin.site.site_header = "KissanMart Admin"
admin.site.site_title = "KissanMart Admin Portal"
admin.site.index_title = "Welcome to KissanMart Administration"
