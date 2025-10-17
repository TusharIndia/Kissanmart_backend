from django.contrib import admin
from .models import Category, Product, ProductImage


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name']


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ['image', 'caption']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'variety', 'seller', 'price_per_unit', 'unit', 
        'quantity_available', 'target_buyers_display', 'status', 'is_published', 'created_at'
    ]
    list_filter = [
        'is_published', 'unit', 'target_mandi_owners', 'target_shopkeepers', 
        'target_communities', 'created_at'
    ]
    search_fields = ['title', 'variety', 'seller__full_name', 'seller__mobile_number', 'description']
    readonly_fields = ['created_at', 'updated_at', 'status', 'target_buyers_display']
    inlines = [ProductImageInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('seller', 'title', 'variety', 'description')
        }),
        ('Pricing & Quantity', {
            'fields': ('price_per_unit', 'unit', 'quantity_available', 'min_order_quantity')
        }),
        ('Target Buyers', {
            'fields': ('target_mandi_owners', 'target_shopkeepers', 'target_communities'),
            'description': 'Select which buyer types can purchase this product'
        }),
        ('Publishing & Status', {
            'fields': ('is_published', 'status', 'target_buyers_display')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('seller').prefetch_related('images')


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ['product', 'image', 'caption', 'is_primary']
    list_filter = ['product__title', 'is_primary']
    search_fields = ['product__title', 'caption']
