"""
Serializers for seller-specific order management
"""

from rest_framework import serializers
from decimal import Decimal
from django.utils import timezone

from ..models import (
    Order, OrderItem, DeliveryAddress, OrderStatusHistory
)
from products.models import Product


class SellerOrderItemSerializer(serializers.ModelSerializer):
    """Serializer for order items from seller's perspective"""
    
    product_id = serializers.CharField(source='product.uuid', read_only=True)
    product_image = serializers.SerializerMethodField()
    customer_name = serializers.CharField(source='order.customer_name', read_only=True)
    order_id = serializers.CharField(source='order.id', read_only=True)
    order_status = serializers.CharField(source='order.status', read_only=True)
    
    class Meta:
        model = OrderItem
        fields = [
            'id', 'product_id', 'product_name', 'product_image', 
            'customer_name', 'order_id', 'order_status',
            'quantity', 'unit', 'unit_price', 'total_price',
            'item_status', 'notes', 'farm_details',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'product_id', 'product_name', 'product_image',
            'customer_name', 'order_id', 'order_status',
            'quantity', 'unit', 'unit_price', 'total_price',
            'farm_details', 'created_at', 'updated_at'
        ]
    
    def get_product_image(self, obj):
        """Get product image URL"""
        if obj.product_image:
            return obj.product_image
        
        if obj.product:
            # Try Pexels image first
            if obj.product.pexels_image_url:
                return obj.product.pexels_image_url
            
            # Try uploaded images
            primary_image = obj.product.images.filter(is_primary=True).first()
            if primary_image:
                if primary_image.image:
                    return primary_image.image.url
                elif primary_image.url:
                    return primary_image.url
            
            first_image = obj.product.images.first()
            if first_image:
                if first_image.image:
                    return first_image.image.url
                elif first_image.url:
                    return first_image.url
        
        return None
    
    def validate_item_status(self, value):
        """Validate item status transitions"""
        if self.instance:
            current_status = self.instance.item_status
            
            # Define allowed transitions for sellers
            allowed_transitions = {
                'confirmed': ['processing', 'cancelled'],
                'processing': ['packed', 'cancelled'],
                'packed': ['shipped'],
                'shipped': ['in_transit'],
                'in_transit': ['delivered'],
                'cancelled': [],  # No transitions from cancelled
                'delivered': [],  # No transitions from delivered
            }
            
            if value not in allowed_transitions.get(current_status, []):
                raise serializers.ValidationError(
                    f"Cannot change status from {current_status} to {value}"
                )
        
        return value


class SellerCustomerInfoSerializer(serializers.ModelSerializer):
    """Basic customer information for seller"""
    
    customer_email = serializers.SerializerMethodField()
    customer_phone = serializers.SerializerMethodField()
    
    class Meta:
        model = Order
        fields = ['customer_name', 'customer_email', 'customer_phone']
    
    def get_customer_email(self, obj):
        """Return masked email for privacy"""
        return 'kissansmartconnectinfo@gmail.com'
    
    def get_customer_phone(self, obj):
        """Return masked phone for privacy"""
        return 'XXXXXXXXXX'


class SellerDeliveryAddressSerializer(serializers.ModelSerializer):
    """Delivery address information for seller"""
    
    full_address = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    address_line_1 = serializers.SerializerMethodField()
    address_line_2 = serializers.SerializerMethodField()
    city = serializers.SerializerMethodField()
    state = serializers.SerializerMethodField()
    pincode = serializers.SerializerMethodField()
    landmark = serializers.SerializerMethodField()
    
    class Meta:
        model = DeliveryAddress
        fields = [
            'name', 'phone', 'address_line_1', 'address_line_2',
            'city', 'state', 'pincode', 'landmark', 'full_address'
        ]
    
    def get_full_address(self, obj):
        """Return masked address for privacy"""
        return "KissanSmart Connect Ground, Delhi"
    
    def get_name(self, obj):
        """Return real customer name for delivery purposes"""
        return obj.name
    
    def get_phone(self, obj):
        """Return masked phone for privacy"""
        return "XXXXXXXXXX"
    
    def get_address_line_1(self, obj):
        """Return masked address line 1 for privacy"""
        return "KissanSmart Connect Ground"
    
    def get_address_line_2(self, obj):
        """Return masked address line 2 for privacy"""
        return ""
    
    def get_city(self, obj):
        """Return masked city for privacy"""
        return "Delhi"
    
    def get_state(self, obj):
        """Return masked state for privacy"""
        return "Delhi"
    
    def get_pincode(self, obj):
        """Return masked pincode for privacy"""
        return "110001"
    
    def get_landmark(self, obj):
        """Return masked landmark for privacy"""
        return "Near KissanSmart Office"


class SellerOrderListSerializer(serializers.ModelSerializer):
    """Simplified order list for sellers showing only their items"""
    
    seller_items = serializers.SerializerMethodField()
    seller_items_count = serializers.SerializerMethodField()
    seller_total_value = serializers.SerializerMethodField()
    customer_info = SellerCustomerInfoSerializer(source='*', read_only=True)
    delivery_city = serializers.CharField(source='delivery_address.city', read_only=True)
    delivery_state = serializers.CharField(source='delivery_address.state', read_only=True)
    
    class Meta:
        model = Order
        fields = [
            'id', 'uuid', 'order_date', 'status', 'payment_status',
            'customer_info', 'delivery_city', 'delivery_state',
            'seller_items_count', 'seller_total_value', 'seller_items',
            'estimated_delivery', 'created_at'
        ]
    
    def get_seller_items(self, obj):
        """Get items sold by the current seller"""
        seller = self.context.get('request').user
        seller_items = obj.items.filter(seller=seller)
        return SellerOrderItemSerializer(seller_items, many=True).data
    
    def get_seller_items_count(self, obj):
        """Count of items from this seller"""
        seller = self.context.get('request').user
        return obj.items.filter(seller=seller).count()
    
    def get_seller_total_value(self, obj):
        """Total value of seller's items in this order"""
        seller = self.context.get('request').user
        total = obj.items.filter(seller=seller).aggregate(
            total=serializers.models.Sum('total_price')
        )['total'] or Decimal('0')
        return float(total)


class SellerOrderDetailSerializer(serializers.ModelSerializer):
    """Detailed order information for sellers"""
    
    seller_items = serializers.SerializerMethodField()
    customer_info = SellerCustomerInfoSerializer(source='*', read_only=True)
    delivery_address = SellerDeliveryAddressSerializer(read_only=True)
    seller_total_value = serializers.SerializerMethodField()
    seller_items_summary = serializers.SerializerMethodField()
    order_timeline = serializers.SerializerMethodField()
    
    class Meta:
        model = Order
        fields = [
            'id', 'uuid', 'order_date', 'status', 'payment_status', 'payment_method',
            'customer_info', 'delivery_address', 'estimated_delivery', 'actual_delivery',
            'seller_items', 'seller_total_value', 'seller_items_summary', 
            'order_timeline', 'notes', 'created_at', 'updated_at'
        ]
    
    def get_seller_items(self, obj):
        """Get items sold by the current seller"""
        seller = self.context.get('seller')
        seller_items = obj.items.filter(seller=seller)
        return SellerOrderItemSerializer(seller_items, many=True).data
    
    def get_seller_total_value(self, obj):
        """Total value of seller's items"""
        seller = self.context.get('seller')
        total = obj.items.filter(seller=seller).aggregate(
            total=serializers.models.Sum('total_price')
        )['total'] or Decimal('0')
        return float(total)
    
    def get_seller_items_summary(self, obj):
        """Summary of seller's items by status"""
        seller = self.context.get('seller')
        seller_items = obj.items.filter(seller=seller)
        
        summary = {}
        for choice in OrderItem._meta.get_field('item_status').choices:
            status_key = choice[0]
            status_label = choice[1]
            count = seller_items.filter(item_status=status_key).count()
            if count > 0:
                summary[status_key] = {
                    'label': status_label,
                    'count': count
                }
        
        return summary
    
    def get_order_timeline(self, obj):
        """Get order status history relevant to seller"""
        timeline = []
        for history in obj.status_history.all():
            timeline.append({
                'status': history.status,
                'title': history.title,
                'message': history.message,
                'timestamp': history.timestamp.isoformat(),
                'location': history.location,
                'changed_by': history.changed_by.full_name if history.changed_by else 'System'
            })
        
        return timeline


class SellerOrderUpdateSerializer(serializers.Serializer):
    """Serializer for updating order status by seller"""
    
    status = serializers.ChoiceField(
        choices=['processing', 'packed', 'shipped'],
        required=False,
        help_text="Update overall order status (limited options for sellers)"
    )
    notes = serializers.CharField(
        max_length=1000,
        required=False,
        help_text="Additional notes about the order"
    )
    estimated_delivery = serializers.DateTimeField(
        required=False,
        help_text="Updated estimated delivery time"
    )
    
    def validate_status(self, value):
        """Validate status change permissions"""
        order = self.context.get('order')
        if not order:
            return value
        
        current_status = order.status
        
        # Sellers can only make certain status changes
        allowed_transitions = {
            'confirmed': ['processing'],
            'processing': ['packed'],
            'packed': ['shipped'],
        }
        
        if value not in allowed_transitions.get(current_status, []):
            raise serializers.ValidationError(
                f"Cannot change order status from {current_status} to {value}"
            )
        
        return value
    
    def update(self, instance, validated_data):
        """Update order with seller changes"""
        if 'status' in validated_data:
            instance.status = validated_data['status']
            
            # Create status history
            OrderStatusHistory.objects.create(
                order=instance,
                status=validated_data['status'],
                title=f'Order {validated_data["status"].title()}',
                message=f'Order status updated to {validated_data["status"]} by seller',
                location=f'Seller: {self.context["request"].user.full_name}',
                changed_by=self.context['request'].user,
                change_source='seller'
            )
        
        if 'estimated_delivery' in validated_data:
            instance.estimated_delivery = validated_data['estimated_delivery']
        
        if 'notes' in validated_data:
            instance.admin_notes = f"{instance.admin_notes}\n\nSeller Note ({timezone.now().strftime('%Y-%m-%d %H:%M')}): {validated_data['notes']}"
        
        instance.save()
        return instance


class SellerOrderStatisticsSerializer(serializers.Serializer):
    """Serializer for seller order statistics"""
    
    total_orders = serializers.IntegerField()
    orders_today = serializers.IntegerField()
    orders_this_week = serializers.IntegerField()
    orders_this_month = serializers.IntegerField()
    
    total_revenue = serializers.DecimalField(max_digits=12, decimal_places=2)
    revenue_today = serializers.DecimalField(max_digits=10, decimal_places=2)
    revenue_this_week = serializers.DecimalField(max_digits=10, decimal_places=2)
    revenue_this_month = serializers.DecimalField(max_digits=10, decimal_places=2)
    
    average_item_value = serializers.DecimalField(max_digits=10, decimal_places=2)
    item_status_breakdown = serializers.DictField()
    product_performance = serializers.ListField()
    recent_activity = serializers.ListField()
    monthly_revenue_trend = serializers.ListField()


class ProductInventorySerializer(serializers.Serializer):
    """Serializer for product inventory information"""
    
    product_id = serializers.UUIDField()
    title = serializers.CharField()
    category = serializers.CharField()
    current_quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    unit = serializers.CharField()
    price_per_unit = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_ordered = serializers.DecimalField(max_digits=10, decimal_places=2)
    pending_orders = serializers.DecimalField(max_digits=10, decimal_places=2)
    available_for_sale = serializers.DecimalField(max_digits=10, decimal_places=2)
    low_stock_alert = serializers.BooleanField()
    revenue_potential = serializers.DecimalField(max_digits=12, decimal_places=2)
    last_updated = serializers.DateTimeField()