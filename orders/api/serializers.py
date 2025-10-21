from rest_framework import serializers
from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from datetime import timedelta

from ..models import (
    Order, OrderItem, DeliveryAddress, OrderTracking, 
    OrderStatusHistory, OrderRefund, OrderAnalytics, OrderCancellationRequest
)
from ..models import PaymentModeCharge
from products.models import Product
from cart.models import Cart, CartItem


class DeliveryAddressSerializer(serializers.ModelSerializer):
    """Serializer for delivery addresses"""
    
    class Meta:
        model = DeliveryAddress
        fields = [
            'name', 'phone', 'email', 'address_line_1', 'address_line_2',
            'city', 'state', 'pincode', 'landmark', 'delivery_instructions',
            'latitude', 'longitude'
        ]
    
    def validate_phone(self, value):
        """Validate phone number format"""
        if not value.startswith('+91') and not value.startswith('91'):
            if len(value) == 10 and value.isdigit():
                value = '+91' + value
        return value
    
    def validate_pincode(self, value):
        """Validate pincode format"""
        if not value.isdigit() or len(value) != 6:
            raise serializers.ValidationError("PIN code must be 6 digits")
        return value


class OrderItemSerializer(serializers.ModelSerializer):
    """Serializer for order items"""
    
    product_id = serializers.CharField(source='product.uuid', read_only=True)
    product_image = serializers.SerializerMethodField()
    pexels_image_url = serializers.SerializerMethodField()
    seller_name = serializers.SerializerMethodField()
    
    class Meta:
        model = OrderItem
        fields = [
            'id', 'product_id', 'product_name', 'product_image', 'pexels_image_url',
            'seller_name', 'quantity', 'unit', 'unit_price', 'total_price',
            'farm_details', 'item_status', 'notes'
        ]
        read_only_fields = [
            'id', 'product_name', 'product_image', 'pexels_image_url', 'seller_name', 
            'unit', 'unit_price', 'total_price', 'farm_details'
        ]
    
    def get_product_image(self, obj):
        """Get product image URL"""
        # Return stored product_image if available
        if obj.product_image:
            return obj.product_image
        
        # Fallback to product's current image
        if obj.product:
            # Try to get pexels_image_url first if available
            if obj.product.pexels_image_url:
                return obj.product.pexels_image_url
            
            # Try to get primary image
            primary_image = obj.product.images.filter(is_primary=True).first()
            if primary_image:
                if primary_image.image:
                    return primary_image.image.url
                elif primary_image.url:
                    return primary_image.url
            
            # Get first available image if no primary image
            first_image = obj.product.images.first()
            if first_image:
                if first_image.image:
                    return first_image.image.url
                elif first_image.url:
                    return first_image.url
        
        return None
    
    def get_pexels_image_url(self, obj):
        """Get product pexels image URL"""
        if obj.product and obj.product.pexels_image_url:
            return obj.product.pexels_image_url
        return None
    
    def get_seller_name(self, obj):
        """Get seller name"""
        # Return stored seller_name if available
        if obj.seller_name:
            return obj.seller_name
        
        # Fallback to seller's current full name
        if obj.seller:
            return obj.seller.full_name
        elif obj.product and obj.product.seller:
            return obj.product.seller.full_name
        
        return ""


class OrderItemCreateSerializer(serializers.Serializer):
    """Serializer for creating order items"""
    
    product_id = serializers.CharField(help_text="Product UUID")
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'))
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'), required=False)
    
    def validate_product_id(self, value):
        """Validate product exists and is available"""
        try:
            product = Product.objects.get(uuid=value, is_published=True)
            return product
        except Product.DoesNotExist:
            raise serializers.ValidationError("Product not found or not available")
    
    def validate(self, data):
        """Validate item availability and quantity"""
        product = data['product_id']
        quantity = data['quantity']
        
        # Check stock availability
        if product.quantity_available < quantity:
            raise serializers.ValidationError({
                'quantity': f"Only {product.quantity_available} {product.unit} available"
            })
        
        # Check minimum order quantity
        if product.min_order_quantity and quantity < product.min_order_quantity:
            raise serializers.ValidationError({
                'quantity': f"Minimum order quantity is {product.min_order_quantity} {product.unit}"
            })
        
        # Set unit price from product if not provided
        if 'unit_price' not in data:
            data['unit_price'] = product.price_per_unit
        
        return data


class OrderStatusHistorySerializer(serializers.ModelSerializer):
    """Serializer for order status history"""
    
    class Meta:
        model = OrderStatusHistory
        fields = [
            'status', 'title', 'message', 'location', 'timestamp', 'metadata'
        ]


class OrderTrackingSerializer(serializers.ModelSerializer):
    """Serializer for order tracking information"""
    
    current_location = serializers.ReadOnlyField()
    
    class Meta:
        model = OrderTracking
        fields = [
            'tracking_number', 'delivery_partner', 'delivery_person_name',
            'delivery_person_phone', 'delivery_vehicle_number', 'current_location',
            'distance_from_customer', 'estimated_arrival', 'last_location_update'
        ]


class OrderListSerializer(serializers.ModelSerializer):
    """Serializer for order list view"""
    
    items_count = serializers.ReadOnlyField()
    total_quantity = serializers.ReadOnlyField()
    has_cancellation_request = serializers.SerializerMethodField()
    
    class Meta:
        model = Order
        fields = [
            'id', 'uuid', 'status', 'order_date', 'estimated_delivery',
            'actual_delivery', 'total_amount', 'items_count', 'total_quantity',
            'payment_method', 'payment_status', 'has_cancellation_request'
        ]

    def get_has_cancellation_request(self, obj):
        # Returns True if a related OrderCancellationRequest exists for this order
        try:
            return hasattr(obj, 'cancellation_request') and obj.cancellation_request is not None
        except Exception:
            return False


class OrderDetailSerializer(serializers.ModelSerializer):
    """Serializer for detailed order view"""
    
    items = OrderItemSerializer(many=True, read_only=True)
    delivery_address = DeliveryAddressSerializer(read_only=True)
    tracking = OrderTrackingSerializer(read_only=True)
    status_history = OrderStatusHistorySerializer(source='status_history.all', many=True, read_only=True)
    
    # Computed fields
    items_count = serializers.ReadOnlyField()
    total_quantity = serializers.ReadOnlyField()
    can_be_cancelled = serializers.ReadOnlyField()
    can_be_tracked = serializers.ReadOnlyField()
    can_be_reordered = serializers.ReadOnlyField()
    
    class Meta:
        model = Order
        fields = [
            'id', 'uuid', 'user_id', 'customer_name', 'customer_email', 'customer_phone',
            'status', 'order_date', 'estimated_delivery', 'actual_delivery',
            'payment_method', 'payment_status', 'payment_transaction_id',
            'subtotal', 'shipping_charges', 'discount_amount', 'tax_amount', 'razorpay_fee', 'platform_fee', 'total_amount',
            'coupon_code', 'notes', 'source',
            # Shiprocket fields
            'shiprocket_order_id', 'shiprocket_shipment_id', 'shiprocket_awb_code',
            'shiprocket_courier_id', 'shiprocket_courier_name', 'shiprocket_status',
            'items', 'delivery_address', 'tracking', 'status_history',
            'items_count', 'total_quantity', 'can_be_cancelled', 'can_be_tracked', 'can_be_reordered',
            'created_at', 'updated_at'
        ]


class OrderCreateSerializer(serializers.Serializer):
    """Serializer for creating orders"""
    
    items = OrderItemCreateSerializer(many=True)
    delivery_address = DeliveryAddressSerializer()
    payment_method = serializers.ChoiceField(choices=['upi', 'netbanking', 'card', 'wallet', 'cod'])
    coupon_code = serializers.CharField(max_length=50, required=False, allow_blank=True)
    notes = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    expected_delivery_date = serializers.DateField(required=False)
    clear_cart = serializers.BooleanField(default=True)
    
    def validate_items(self, value):
        """Validate order items"""
        if not value:
            raise serializers.ValidationError("At least one item is required")
        
        # Check for duplicate products
        product_ids = [item['product_id'].uuid for item in value]
        if len(product_ids) != len(set(str(pid) for pid in product_ids)):
            raise serializers.ValidationError("Duplicate products are not allowed")
        
        return value
    
    def validate(self, data):
        """Cross-field validation"""
        # Validate expected delivery date
        if 'expected_delivery_date' in data:
            if data['expected_delivery_date'] <= timezone.now().date():
                raise serializers.ValidationError({
                    'expected_delivery_date': 'Expected delivery date must be in the future'
                })
        
        return data
    
    @transaction.atomic
    def create(self, validated_data):
        """Create order with all related objects"""
        user = self.context['request'].user
        
        # Extract nested data
        items_data = validated_data.pop('items')
        delivery_address_data = validated_data.pop('delivery_address')
        coupon_code = validated_data.pop('coupon_code', None)
        notes = validated_data.pop('notes', '')
        expected_delivery_date = validated_data.pop('expected_delivery_date', None)
        clear_cart = validated_data.pop('clear_cart', True)
        
        # Create delivery address
        delivery_address = DeliveryAddress.objects.create(**delivery_address_data)
        
        # Calculate estimated delivery
        estimated_delivery = None
        if expected_delivery_date:
            estimated_delivery = timezone.make_aware(
                timezone.datetime.combine(expected_delivery_date, timezone.datetime.min.time())
            )
        else:
            # Default to next day 6 PM
            estimated_delivery = timezone.now() + timedelta(days=1)
            estimated_delivery = estimated_delivery.replace(hour=18, minute=0, second=0, microsecond=0)
        
        # Create order
        order = Order.objects.create(
            user=user,
            delivery_address=delivery_address,
            payment_method=validated_data['payment_method'],
            coupon_code=coupon_code,
            notes=notes,
            estimated_delivery=estimated_delivery,
            status='confirmed' if validated_data['payment_method'] == 'cod' else 'pending'
        )
        
        # Create order items and update product quantities
        total_amount = Decimal('0.00')
        for item_data in items_data:
            product = item_data['product_id']
            quantity = item_data['quantity']
            unit_price = item_data.get('unit_price', product.price_per_unit)
            
            # Create order item
            order_item = OrderItem.objects.create(
                order=order,
                product=product,
                quantity=quantity,
                unit_price=unit_price,
                seller=product.seller
            )
            
            total_amount += order_item.total_price
            
            # Update product quantity
            product.quantity_available -= quantity
            product.save()
        
        # Calculate and save order totals
        order.subtotal = total_amount
        order.shipping_charges = Decimal('0.00') if total_amount > 500 else Decimal('50.00')
        
        # Calculate fees if not COD
        # Note: we no longer pass Razorpay gateway fee to the customer. Only platform_fee and
        # an admin-configured payment_mode_charge (portal charge) are applied. razorpay_fee is kept
        # as 0.00 for bookkeeping.
        # Determine platform fee percentage from admin-configured PaymentModeCharge.
        # Platform fee is applied as percentage over (subtotal + shipping_charges).
        from ..models import PaymentModeCharge
        if order.payment_method != 'cod':
            order.razorpay_fee = Decimal('0.00')
            try:
                pct = PaymentModeCharge.get_percentage_for_mode(order.payment_method)
                platform_base = order.subtotal + order.shipping_charges
                order.platform_fee = (platform_base * (Decimal(str(pct)) / Decimal('100.0'))).quantize(Decimal('0.01'))
            except Exception:
                order.platform_fee = Decimal('0.00')
        else:
            order.razorpay_fee = Decimal('0.00')
            order.platform_fee = Decimal('0.00')

        # No separate payment_mode_charge is used in this mode
        order.payment_mode_charge = Decimal('0.00')

        # Final total: subtotal + shipping + tax + platform_fee - discount
        order.total_amount = order.subtotal + order.shipping_charges + order.tax_amount + order.platform_fee - order.discount_amount

        order.save()
        
        # Create initial status history
        OrderStatusHistory.objects.create(
            order=order,
            status=order.status,
            title='Order Placed' if order.status == 'confirmed' else 'Payment Pending',
            message='Your order has been placed successfully' if order.status == 'confirmed' else 'Waiting for payment confirmation',
            location='KissanMart System',
            change_source='api'
        )
        
        # Create tracking record
        OrderTracking.objects.create(
            order=order,
            delivery_partner='KissanMart Delivery',
        )
        
        # Clear cart if requested
        if clear_cart:
            try:
                user.cart.clear()
            except:
                pass  # Cart might not exist
        
        return order


class OrderUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating orders"""
    
    class Meta:
        model = Order
        fields = ['status', 'estimated_delivery', 'admin_notes']
    
    def validate_status(self, value):
        """Validate status transitions"""
        if self.instance:
            current_status = self.instance.status
            valid_transitions = {
                'pending': ['confirmed', 'cancelled'],
                'confirmed': ['processing', 'cancelled'],
                'processing': ['packed', 'cancelled'],
                'packed': ['shipped', 'cancelled'],
                'shipped': ['in_transit'],
                'in_transit': ['delivered', 'cancelled'],
                'delivered': [],
                'cancelled': [],
                'refunded': [],
                'failed': ['pending', 'cancelled']
            }
            
            if value not in valid_transitions.get(current_status, []):
                raise serializers.ValidationError(
                    f"Cannot change status from {current_status} to {value}"
                )
        
        return value
    
    def update(self, instance, validated_data):
        """Update order and create status history"""
        old_status = instance.status
        instance = super().update(instance, validated_data)
        
        # Create status history if status changed
        if 'status' in validated_data and validated_data['status'] != old_status:
            status_titles = {
                'confirmed': 'Order Confirmed',
                'processing': 'Order Processing',
                'packed': 'Order Packed',
                'shipped': 'Order Shipped',
                'in_transit': 'Out for Delivery',
                'delivered': 'Order Delivered',
                'cancelled': 'Order Cancelled'
            }
            
            status_messages = {
                'confirmed': 'Your order has been confirmed and is being prepared',
                'processing': 'Your order is being processed and packed',
                'packed': 'Your order has been packed and is ready for dispatch',
                'shipped': 'Your order has been shipped and is on its way',
                'in_transit': 'Your order is out for delivery',
                'delivered': 'Your order has been delivered successfully',
                'cancelled': 'Your order has been cancelled'
            }
            
            OrderStatusHistory.objects.create(
                order=instance,
                status=validated_data['status'],
                title=status_titles.get(validated_data['status'], 'Status Updated'),
                message=status_messages.get(validated_data['status'], 'Order status has been updated'),
                location='KissanMart System',
                change_source='admin' if self.context.get('is_admin') else 'api'
            )
        
        return instance


class OrderCancelSerializer(serializers.Serializer):
    """Serializer for cancelling orders"""
    
    reason = serializers.CharField(max_length=500, required=True)
    refund_required = serializers.BooleanField(default=True)
    
    def validate(self, data):
        """Validate cancellation request"""
        order = self.context['order']
        # Disallow cancelling Cash on Delivery orders
        if getattr(order, 'payment_method', None) == 'cod':
            raise serializers.ValidationError(
                "Cash on Delivery orders cannot be cancelled"
            )
        
        if not order.can_be_cancelled:
            raise serializers.ValidationError(
                f"Order cannot be cancelled in {order.status} status"
            )
        
        return data


class OrderReorderSerializer(serializers.Serializer):
    """Serializer for reordering items"""
    
    delivery_address = DeliveryAddressSerializer(required=False)
    exclude_items = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True
    )
    payment_method = serializers.ChoiceField(
        choices=['upi', 'netbanking', 'card', 'wallet', 'cod'],
        required=False
    )
    
    def validate_exclude_items(self, value):
        """Validate excluded items exist in original order"""
        order = self.context['order']
        order_item_ids = set(str(item.id) for item in order.items.all())
        
        for item_id in value:
            if str(item_id) not in order_item_ids:
                raise serializers.ValidationError(f"Item {item_id} not found in original order")
        
        return value


class OrderAnalyticsSerializer(serializers.ModelSerializer):
    """Serializer for order analytics"""
    
    class Meta:
        model = OrderAnalytics
        fields = [
            'date', 'total_orders', 'pending_orders', 'confirmed_orders',
            'delivered_orders', 'cancelled_orders', 'total_revenue',
            'average_order_value', 'top_products', 'top_sellers', 'top_cities'
        ]


class OrderStatisticsSerializer(serializers.Serializer):
    """Serializer for order statistics"""
    
    total_orders = serializers.IntegerField()
    orders_today = serializers.IntegerField()
    orders_this_week = serializers.IntegerField()
    orders_this_month = serializers.IntegerField()
    revenue_today = serializers.DecimalField(max_digits=12, decimal_places=2)
    revenue_this_week = serializers.DecimalField(max_digits=12, decimal_places=2)
    revenue_this_month = serializers.DecimalField(max_digits=12, decimal_places=2)
    average_order_value = serializers.DecimalField(max_digits=10, decimal_places=2)
    status_breakdown = serializers.DictField()
    top_products = serializers.ListField()


class PaymentSerializer(serializers.Serializer):
    """Serializer for payment processing"""
    
    payment_method = serializers.ChoiceField(choices=['upi', 'netbanking', 'card', 'cod'])
    payment_details = serializers.DictField()
    billing_address = serializers.DictField(required=False)
    
    def validate_payment_details(self, value):
        """Validate payment details based on method"""
        payment_method = self.initial_data.get('payment_method')
        
        if payment_method == 'card':
            required_fields = ['card_number', 'expiry_month', 'expiry_year', 'cvv', 'cardholder_name']
            for field in required_fields:
                if field not in value:
                    raise serializers.ValidationError(f"{field} is required for card payment")
        
        elif payment_method == 'upi':
            if 'upi_id' not in value:
                raise serializers.ValidationError("UPI ID is required for UPI payment")
        
        return value


class LiveTrackingSerializer(serializers.Serializer):
    """Serializer for live tracking information"""
    
    order_id = serializers.CharField()
    status = serializers.CharField()
    delivery_person = serializers.DictField()
    current_location = serializers.DictField()
    last_updated = serializers.DateTimeField()


class RazorpayOrderCreateSerializer(serializers.Serializer):
    """Serializer for creating Razorpay orders"""
    
    currency = serializers.CharField(default='INR')
    notes = serializers.DictField(required=False)


class RazorpayPaymentVerificationSerializer(serializers.Serializer):
    """Serializer for verifying Razorpay payments"""
    
    razorpay_order_id = serializers.CharField(max_length=255, required=True)
    razorpay_payment_id = serializers.CharField(max_length=255, required=True)
    razorpay_signature = serializers.CharField(max_length=255, required=True)
    
    def validate_razorpay_order_id(self, value):
        """Validate Razorpay order ID format"""
        if not value or not isinstance(value, str):
            raise serializers.ValidationError("Razorpay order ID must be a non-empty string")
        if not value.startswith('order_'):
            raise serializers.ValidationError("Invalid Razorpay order ID format")
        return value.strip()
    
    def validate_razorpay_payment_id(self, value):
        """Validate Razorpay payment ID format"""
        if not value or not isinstance(value, str):
            raise serializers.ValidationError("Razorpay payment ID must be a non-empty string")
        if not value.startswith('pay_'):
            raise serializers.ValidationError("Invalid Razorpay payment ID format")
        return value.strip()
    
    def validate_razorpay_signature(self, value):
        """Validate Razorpay signature"""
        if not value or not isinstance(value, str):
            raise serializers.ValidationError("Razorpay signature must be a non-empty string")
        return value.strip()
    
    def validate(self, attrs):
        """Additional validation"""
        # Log the data being validated
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Validating Razorpay payment data: {attrs}")
        return attrs


class OrderCancellationRequestSerializer(serializers.ModelSerializer):
    """Serializer for order cancellation requests"""
    
    order_id = serializers.CharField(source='order.id', read_only=True)
    customer_name = serializers.CharField(source='order.customer_name', read_only=True)
    order_total = serializers.DecimalField(source='order.total_amount', max_digits=10, decimal_places=2, read_only=True)
    
    class Meta:
        model = OrderCancellationRequest
        fields = [
            'id', 'order_id', 'customer_name', 'order_total',
            'reason', 'reason_description', 'request_status',
            'refund_amount', 'razorpay_fee_deduction', 'platform_fee_deduction', 'final_refund_amount',
            'razorpay_refund_id', 'refund_processed_at',
            'reviewed_by', 'reviewed_at', 'admin_notes',
            'shiprocket_cancelled', 'requested_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'order_id', 'customer_name', 'order_total', 'request_status',
            'refund_amount', 'razorpay_fee_deduction', 'platform_fee_deduction', 'final_refund_amount',
            'razorpay_refund_id', 'refund_processed_at',
            'reviewed_by', 'reviewed_at', 'admin_notes',
            'shiprocket_cancelled', 'requested_at', 'updated_at'
        ]


class OrderCancellationRequestCreateSerializer(serializers.Serializer):
    """Serializer for creating order cancellation requests"""

    # Accept either the choice key (e.g. 'change_of_mind') or the human label
    reason = serializers.CharField(max_length=100, help_text='Cancellation reason (choice key or label)')
    # Make description optional so frontend can submit without it
    reason_description = serializers.CharField(max_length=1000, help_text="Detailed reason for cancellation", required=False, allow_blank=True)
    
    def validate(self, data):
        """Validate cancellation request"""
        order = self.context['order']
        # Normalize reason: allow keys or human labels
        reason_val = data.get('reason')
        if reason_val is None:
            raise serializers.ValidationError({'reason': 'This field is required.'})

        # Map provided value to one of the choice keys
        choices = dict(OrderCancellationRequest.CANCELLATION_REASON_CHOICES)
        # If the user passed the key directly, keep it
        # Normalize potential surrounding quotes and whitespace
        if isinstance(reason_val, str):
            rv_norm = reason_val.strip().strip('"\'')
        else:
            rv_norm = reason_val

        if rv_norm in choices:
            data['reason'] = reason_val
        else:
            # Try matching by label (case-insensitive)
            matched = None
            for k, v in choices.items():
                if str(v).strip().lower() == str(rv_norm).strip().lower():
                    matched = k
                    break
            # Common free-text mapping (helpful for human-entered labels)
            if not matched:
                # Normalize by removing punctuation and lowercasing
                rv = ''.join(ch for ch in str(rv_norm) if ch.isalnum() or ch.isspace()).strip().lower()

                if 'changed my mind' in rv or ('change' in rv and 'mind' in rv) or 'ordered by mistake' in rv or 'ordered mistakenly' in rv:
                    matched = 'change_of_mind'
                elif 'not need' in rv or 'not needed' in rv or 'not needed anymore' in rv:
                    matched = 'product_not_needed'
                elif 'better price' in rv or 'found better' in rv or 'cheaper' in rv:
                    matched = 'found_better_price'
                elif 'delivery' in rv and ('delay' in rv or 'late' in rv or 'taking' in rv):
                    matched = 'delivery_delay'
                elif 'wrong product' in rv or 'wrong item' in rv or 'ordered wrong' in rv:
                    matched = 'wrong_product'
                elif 'payment' in rv or 'paid' in rv and 'issue' in rv:
                    matched = 'payment_issue'
                elif 'other' in rv:
                    matched = 'other'
                else:
                    matched = None

            if matched:
                data['reason'] = matched
            else:
                # Provide helpful message listing allowed human labels
                allowed_labels = ', '.join([str(v) for v in choices.values()])
                raise serializers.ValidationError({'reason': f'"{reason_val}" is not a valid choice. Allowed: {allowed_labels}'})
        
        # Check if order can be cancelled
        if not order.can_be_cancelled:
            raise serializers.ValidationError(
                f"Order cannot be cancelled in {order.status} status or pickup date has passed"
            )
        
        # Ensure reason_description exists (may be optional)
        if 'reason_description' not in data or data.get('reason_description') is None:
            data['reason_description'] = ''

        # Check if cancellation request already exists
        if hasattr(order, 'cancellation_request'):
            raise serializers.ValidationError("Cancellation request already exists for this order")
        
        # Check if order is already cancelled or refunded
        if order.status in ['cancelled', 'refunded']:
            raise serializers.ValidationError("Order is already cancelled or refunded")
        
        # Check if payment was made (only paid orders can request refund)
        if order.payment_status != 'completed':
            raise serializers.ValidationError("Only paid orders can request cancellation with refund")
        
        return data
    
    @transaction.atomic
    def create(self, validated_data):
        """Create cancellation request"""
        order = self.context['order']
        # Compute refund amounts explicitly to ensure DB NOT NULL fields are provided
        refund_amount = getattr(order, 'total_amount', None)
        if refund_amount is None:
            refund_amount = Decimal('0.00')

        razorpay_fee_deduction = getattr(order, 'razorpay_fee', Decimal('0.00')) or Decimal('0.00')
        platform_fee_deduction = getattr(order, 'platform_fee', Decimal('0.00')) or Decimal('0.00')
        final_refund_amount = refund_amount - razorpay_fee_deduction - platform_fee_deduction
        if final_refund_amount < Decimal('0.00'):
            final_refund_amount = Decimal('0.00')

        # Ensure reason_description exists
        reason_desc = validated_data.get('reason_description', '') or ''

        # Create cancellation request with all required financial fields
        cancellation_request = OrderCancellationRequest.objects.create(
            order=order,
            reason=validated_data['reason'],
            reason_description=reason_desc,
            refund_amount=refund_amount,
            razorpay_fee_deduction=razorpay_fee_deduction,
            platform_fee_deduction=platform_fee_deduction,
            final_refund_amount=final_refund_amount
        )
        
        # Create order status history
        OrderStatusHistory.objects.create(
            order=order,
            status=order.status,
            title='Cancellation Requested',
            message=f'Customer requested order cancellation. Reason: {dict(OrderCancellationRequest.CANCELLATION_REASON_CHOICES).get(validated_data["reason"], validated_data["reason"])}',
            location='Customer Portal',
            change_source='customer'
        )
        
        return cancellation_request


class OrderCancellationStatusSerializer(serializers.Serializer):
    """Serializer for checking order cancellation eligibility"""
    
    can_cancel = serializers.BooleanField()
    reason = serializers.CharField()
    pickup_scheduled_date = serializers.DateTimeField(required=False, allow_null=True)
    current_status = serializers.CharField(required=False)
    shiprocket_status = serializers.CharField(required=False)


class AdminRefundProcessSerializer(serializers.Serializer):
    """Serializer for admin to process refunds"""
    
    admin_notes = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    process_refund = serializers.BooleanField(default=True, help_text="Whether to process the refund")
    cancel_in_shiprocket = serializers.BooleanField(default=True, help_text="Whether to cancel order in Shiprocket")
    # Optional admin overrides
    final_refund_amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True,
                                                   help_text="Final amount to refund to customer (optional override)")
    razorpay_fee_deduction = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True,
                                                      help_text="Amount of Razorpay fee to deduct (optional override)")
    platform_fee_deduction = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True,
                                                      help_text="Amount of Platform fee to deduct (optional override)")
    
    def validate(self, data):
        """Validate refund processing request"""
        cancellation_request = self.context['cancellation_request']
        if cancellation_request.request_status != 'pending':
            raise serializers.ValidationError(
                f"Cannot process refund for request in {cancellation_request.request_status} status"
            )

        # Validate numeric overrides if provided
        refund_total = cancellation_request.refund_amount
        rpd = data.get('razorpay_fee_deduction')
        pfd = data.get('platform_fee_deduction')
        final = data.get('final_refund_amount')

        # Ensure non-negative values
        for fld_name in ('razorpay_fee_deduction', 'platform_fee_deduction', 'final_refund_amount'):
            val = data.get(fld_name)
            if val is not None and val < Decimal('0.00'):
                raise serializers.ValidationError({fld_name: 'Must be a non-negative amount'})

        # If final amount provided, ensure it doesn't exceed refund_total
        if final is not None and final > refund_total:
            raise serializers.ValidationError({'final_refund_amount': 'Cannot refund more than order total amount'})

        # If deductions provided, ensure sum of deductions does not exceed refund_total
        if rpd is not None or pfd is not None:
            rpd_val = rpd or Decimal('0.00')
            pfd_val = pfd or Decimal('0.00')
            if (rpd_val + pfd_val) > refund_total:
                raise serializers.ValidationError('Deductions cannot exceed the total refundable amount')

        # If both final and deductions provided, ensure consistency: final == refund_total - (rpd + pfd)
        if final is not None and (rpd is not None or pfd is not None):
            rpd_val = rpd or Decimal('0.00')
            pfd_val = pfd or Decimal('0.00')
            expected_final = refund_total - (rpd_val + pfd_val)
            # Allow small rounding differences
            if abs(expected_final - final) > Decimal('0.10'):
                raise serializers.ValidationError('Provided final_refund_amount does not match deductions; please provide consistent values')

        return data