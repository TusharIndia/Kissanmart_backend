from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import (
    Order, OrderItem, DeliveryAddress, OrderTracking, 
    OrderStatusHistory, OrderRefund, OrderAnalytics
)


class OrderItemInline(admin.TabularInline):
    """Inline admin for order items"""
    model = OrderItem
    extra = 0
    readonly_fields = ['total_price', 'farm_details']
    fields = [
        'product', 'product_name', 'seller', 'quantity', 
        'unit', 'unit_price', 'total_price', 'item_status'
    ]


class OrderStatusHistoryInline(admin.TabularInline):
    """Inline admin for order status history"""
    model = OrderStatusHistory
    extra = 0
    readonly_fields = ['timestamp']
    fields = ['status', 'title', 'message', 'location', 'timestamp']


@admin.register(DeliveryAddress)
class DeliveryAddressAdmin(admin.ModelAdmin):
    """Admin for delivery addresses"""
    list_display = [
        'name', 'phone', 'city', 'state', 'pincode', 'created_at'
    ]
    list_filter = ['city', 'state', 'created_at']
    search_fields = ['name', 'phone', 'address_line_1', 'city', 'pincode']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Contact Information', {
            'fields': ('name', 'phone', 'email')
        }),
        ('Address Details', {
            'fields': (
                'address_line_1', 'address_line_2', 'city', 'state', 
                'pincode', 'landmark', 'delivery_instructions'
            )
        }),
        ('Location Coordinates', {
            'fields': ('latitude', 'longitude'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """Admin for orders"""
    list_display = [
        'id', 'customer_name', 'status', 'total_amount', 
        'payment_status', 'order_date', 'estimated_delivery'
    ]
    list_filter = [
        'status', 'payment_status', 'payment_method', 
        'order_date', 'created_at'
    ]
    search_fields = [
        'id', 'customer_name', 'customer_phone', 'customer_email'
    ]
    readonly_fields = [
        'id', 'uuid', 'created_at', 'updated_at', 'items_count', 
        'total_quantity', 'can_be_cancelled', 'can_be_tracked'
    ]
    inlines = [OrderItemInline, OrderStatusHistoryInline]
    
    fieldsets = (
        ('Order Information', {
            'fields': ('id', 'uuid', 'user', 'status', 'source')
        }),
        ('Customer Details', {
            'fields': (
                'customer_name', 'customer_email', 'customer_phone'
            )
        }),
        ('Financial Details', {
            'fields': (
                'subtotal', 'shipping_charges', 'discount_amount', 
                'tax_amount', 'total_amount'
            )
        }),
        ('Payment Information', {
            'fields': (
                'payment_method', 'payment_status', 'payment_transaction_id'
            )
        }),
        ('Delivery Information', {
            'fields': ('delivery_address', 'estimated_delivery', 'actual_delivery')
        }),
        ('Additional Information', {
            'fields': ('coupon_code', 'notes', 'admin_notes'),
            'classes': ('collapse',)
        }),
        ('Computed Fields', {
            'fields': (
                'items_count', 'total_quantity', 'can_be_cancelled', 'can_be_tracked'
            ),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('order_date', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def get_queryset(self, request):
        """Optimize queryset with related objects"""
        return super().get_queryset(request).select_related(
            'user', 'delivery_address'
        ).prefetch_related('items')
    
    actions = ['mark_as_confirmed', 'mark_as_processing', 'mark_as_shipped']
    
    def mark_as_confirmed(self, request, queryset):
        """Action to mark orders as confirmed"""
        updated = queryset.update(status='confirmed')
        self.message_user(request, f'{updated} orders marked as confirmed.')
    mark_as_confirmed.short_description = "Mark selected orders as confirmed"
    
    def mark_as_processing(self, request, queryset):
        """Action to mark orders as processing"""
        updated = queryset.update(status='processing')
        self.message_user(request, f'{updated} orders marked as processing.')
    mark_as_processing.short_description = "Mark selected orders as processing"
    
    def mark_as_shipped(self, request, queryset):
        """Action to mark orders as shipped"""
        updated = queryset.update(status='shipped')
        self.message_user(request, f'{updated} orders marked as shipped.')
    mark_as_shipped.short_description = "Mark selected orders as shipped"


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    """Admin for order items"""
    list_display = [
        'order', 'product_name', 'seller_name', 'quantity', 
        'unit_price', 'total_price', 'item_status'
    ]
    list_filter = ['item_status', 'unit', 'created_at']
    search_fields = [
        'order__id', 'product_name', 'seller_name', 'order__customer_name'
    ]
    readonly_fields = ['total_price', 'farm_details', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Order Information', {
            'fields': ('order', 'item_status')
        }),
        ('Product Information', {
            'fields': ('product', 'product_name', 'product_image')
        }),
        ('Seller Information', {
            'fields': ('seller', 'seller_name')
        }),
        ('Quantity & Pricing', {
            'fields': ('quantity', 'unit', 'unit_price', 'total_price')
        }),
        ('Additional Information', {
            'fields': ('farm_details', 'notes'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )


@admin.register(OrderTracking)
class OrderTrackingAdmin(admin.ModelAdmin):
    """Admin for order tracking"""
    list_display = [
        'order', 'delivery_partner', 'delivery_person_name', 
        'tracking_number', 'last_location_update'
    ]
    list_filter = ['delivery_partner', 'last_location_update']
    search_fields = [
        'order__id', 'tracking_number', 'delivery_person_name'
    ]
    readonly_fields = ['created_at', 'updated_at', 'current_location']
    
    fieldsets = (
        ('Order Information', {
            'fields': ('order',)
        }),
        ('Delivery Partner', {
            'fields': ('delivery_partner', 'tracking_number')
        }),
        ('Delivery Person', {
            'fields': (
                'delivery_person_name', 'delivery_person_phone', 
                'delivery_vehicle_number'
            )
        }),
        ('Location Information', {
            'fields': (
                'current_latitude', 'current_longitude', 'current_address',
                'distance_from_customer', 'estimated_arrival', 'current_location'
            ),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('last_location_update', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )


@admin.register(OrderStatusHistory)
class OrderStatusHistoryAdmin(admin.ModelAdmin):
    """Admin for order status history"""
    list_display = [
        'order', 'status', 'title', 'timestamp', 'change_source'
    ]
    list_filter = ['status', 'change_source', 'timestamp']
    search_fields = ['order__id', 'title', 'message']
    readonly_fields = ['timestamp']
    
    fieldsets = (
        ('Order Information', {
            'fields': ('order', 'status')
        }),
        ('Status Details', {
            'fields': ('title', 'message', 'location')
        }),
        ('Change Information', {
            'fields': ('changed_by', 'change_source', 'timestamp')
        }),
        ('Additional Data', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        })
    )


@admin.register(OrderRefund)
class OrderRefundAdmin(admin.ModelAdmin):
    """Admin for order refunds"""
    list_display = [
        'order', 'refund_type', 'refund_status', 'refund_amount', 
        'final_refund_amount', 'initiated_at'
    ]
    list_filter = ['refund_type', 'refund_status', 'initiated_at']
    search_fields = ['order__id', 'reason', 'refund_transaction_id']
    readonly_fields = ['final_refund_amount', 'initiated_at']
    
    fieldsets = (
        ('Order Information', {
            'fields': ('order',)
        }),
        ('Refund Details', {
            'fields': (
                'refund_type', 'refund_status', 'reason',
                'refund_amount', 'processing_fee', 'final_refund_amount'
            )
        }),
        ('Transaction Information', {
            'fields': (
                'refund_transaction_id', 'estimated_refund_days'
            )
        }),
        ('Timestamps', {
            'fields': ('initiated_at', 'completed_at', 'initiated_by')
        })
    )


@admin.register(OrderAnalytics)
class OrderAnalyticsAdmin(admin.ModelAdmin):
    """Admin for order analytics"""
    list_display = [
        'date', 'total_orders', 'delivered_orders', 'cancelled_orders',
        'total_revenue', 'average_order_value'
    ]
    list_filter = ['date', 'created_at']
    search_fields = ['date']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Date Information', {
            'fields': ('date',)
        }),
        ('Order Statistics', {
            'fields': (
                'total_orders', 'pending_orders', 'confirmed_orders',
                'delivered_orders', 'cancelled_orders'
            )
        }),
        ('Revenue Statistics', {
            'fields': ('total_revenue', 'average_order_value')
        }),
        ('Top Performers', {
            'fields': ('top_products', 'top_sellers', 'top_cities'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
