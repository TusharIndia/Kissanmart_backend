from django.db import models
from django.contrib.auth import get_user_model
from django.db.models import JSONField
from decimal import Decimal
import uuid
from django.utils import timezone

User = get_user_model()

# Order Status Choices
ORDER_STATUS_CHOICES = [
    ('pending', 'Pending Payment'),
    ('confirmed', 'Confirmed'),
    ('processing', 'Processing'),
    ('packed', 'Packed'),
    ('shipped', 'Shipped'),
    ('in_transit', 'In Transit'),
    ('delivered', 'Delivered'),
    ('cancelled', 'Cancelled'), 
    ('refunded', 'Refunded'),
    ('failed', 'Failed'),
]

# Payment Status Choices
PAYMENT_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('completed', 'Completed'),
    ('failed', 'Failed'),
    ('refunded', 'Refunded'),
]

# Payment Method Choices
PAYMENT_METHOD_CHOICES = [
    ('upi', 'UPI'),
    ('netbanking', 'Net Banking'),
    ('card', 'Credit/Debit Card'),
    ('wallet', 'Digital Wallet'),
    ('cod', 'Cash on Delivery'),
]


class DeliveryAddress(models.Model):
    """Model to store delivery addresses for orders"""
    
    name = models.CharField(max_length=255, help_text="Recipient's full name")
    phone = models.CharField(max_length=15, help_text="Contact phone number")
    email = models.EmailField(blank=True, null=True, help_text="Contact email (optional)")
    address_line_1 = models.CharField(max_length=255, help_text="Street address line 1")
    address_line_2 = models.CharField(max_length=255, blank=True, help_text="Street address line 2 (optional)")
    city = models.CharField(max_length=100, help_text="City")
    state = models.CharField(max_length=100, help_text="State")
    pincode = models.CharField(max_length=10, help_text="PIN code")
    landmark = models.CharField(max_length=255, blank=True, help_text="Nearby landmark (optional)")
    delivery_instructions = models.TextField(blank=True, help_text="Special delivery instructions (optional)")
    
    # Location coordinates for delivery optimization
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Delivery Address"
        verbose_name_plural = "Delivery Addresses"
    
    def __str__(self):
        return f"{self.name} - {self.city}, {self.state} {self.pincode}"
    
    @property
    def full_address(self):
        """Get formatted full address"""
        address_parts = [self.address_line_1]
        if self.address_line_2:
            address_parts.append(self.address_line_2)
        if self.landmark:
            address_parts.append(f"Near {self.landmark}")
        address_parts.extend([self.city, self.state, self.pincode])
        return ", ".join(address_parts)


class Order(models.Model):
    """Main Order model"""
    
    # Primary identifiers
    id = models.CharField(max_length=20, primary_key=True, help_text="Order ID (e.g., KC123456)")
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, help_text="UUID for API operations")
    
    # User and order details
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders', help_text="Customer who placed the order")
    customer_name = models.CharField(max_length=255, help_text="Customer's full name at time of order")
    customer_email = models.EmailField(help_text="Customer's email at time of order")
    customer_phone = models.CharField(max_length=15, help_text="Customer's phone at time of order")
    
    # Order status and tracking
    status = models.CharField(max_length=20, choices=ORDER_STATUS_CHOICES, default='pending', help_text="Current order status")
    order_date = models.DateTimeField(auto_now_add=True, help_text="When the order was placed")
    estimated_delivery = models.DateTimeField(blank=True, null=True, help_text="Estimated delivery date and time")
    actual_delivery = models.DateTimeField(blank=True, null=True, help_text="Actual delivery date and time")
    
    # Payment information
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, help_text="Payment method used")
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending', help_text="Payment status")
    payment_transaction_id = models.CharField(max_length=255, blank=True, null=True, help_text="Payment gateway transaction ID")
    payment_gateway_response = JSONField(default=dict, blank=True, help_text="Full payment gateway response")
    
    # Razorpay specific fields
    razorpay_order_id = models.CharField(max_length=255, blank=True, null=True, help_text="Razorpay order ID")
    razorpay_payment_id = models.CharField(max_length=255, blank=True, null=True, help_text="Razorpay payment ID")
    razorpay_signature = models.CharField(max_length=255, blank=True, null=True, help_text="Razorpay payment signature")
    
    # Shiprocket specific fields
    shiprocket_order_id = models.CharField(max_length=255, blank=True, null=True, help_text="Shiprocket order ID")
    shiprocket_shipment_id = models.CharField(max_length=255, blank=True, null=True, help_text="Shiprocket shipment ID")
    shiprocket_awb_code = models.CharField(max_length=255, blank=True, null=True, help_text="Shiprocket AWB tracking code")
    shiprocket_courier_id = models.CharField(max_length=255, blank=True, null=True, help_text="Selected courier company ID")
    shiprocket_courier_name = models.CharField(max_length=255, blank=True, null=True, help_text="Selected courier company name")
    shiprocket_status = models.CharField(max_length=50, blank=True, null=True, help_text="Shiprocket order status")
    shiprocket_response = JSONField(default=dict, blank=True, help_text="Full Shiprocket API response")
    
    # Financial details
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Sum of all item totals")
    shipping_charges = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Shipping and handling charges")
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Total discount applied")
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Tax amount")
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Final total amount")
    
    # Delivery address
    delivery_address = models.ForeignKey(DeliveryAddress, on_delete=models.PROTECT, help_text="Delivery address for this order")
    
    # Additional fields
    coupon_code = models.CharField(max_length=50, blank=True, null=True, help_text="Applied coupon code")
    notes = models.TextField(blank=True, help_text="Customer notes or special instructions")
    admin_notes = models.TextField(blank=True, help_text="Internal admin notes")
    
    # Metadata and tracking
    metadata = JSONField(default=dict, blank=True, help_text="Additional order metadata")
    source = models.CharField(max_length=50, default='web', help_text="Order source (web, mobile, etc.)")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = "Order"
        verbose_name_plural = "Orders"
    
    def save(self, *args, **kwargs):
        # Generate order ID if not provided
        if not self.id:
            self.id = self.generate_order_id()
        
        # Set customer details from user if not provided
        if not self.customer_name and self.user:
            self.customer_name = self.user.full_name
        if not self.customer_email and self.user:
            self.customer_email = self.user.email or ''
        if not self.customer_phone and self.user:
            self.customer_phone = self.user.mobile_number or ''
        
        # Calculate totals if not provided
        if not self.total_amount:
            self.calculate_totals()
        
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"Order {self.id} - {self.customer_name} ({self.status})"
    
    @staticmethod
    def generate_order_id():
        """Generate unique order ID"""
        import random
        import string
        from django.db import transaction
        
        with transaction.atomic():
            while True:
                # Generate ID like KC123456
                order_id = 'KC' + ''.join(random.choices(string.digits, k=6))
                if not Order.objects.filter(id=order_id).exists():
                    return order_id
    
    def calculate_totals(self):
        """Calculate order totals from items"""
        items = self.items.all()
        self.subtotal = sum(item.total_price for item in items)
        
        # Calculate shipping (free for orders above 500)
        self.shipping_charges = Decimal('0.00') if self.subtotal > 500 else Decimal('50.00')
        
        # Calculate total
        self.total_amount = self.subtotal + self.shipping_charges + self.tax_amount - self.discount_amount
    
    @property
    def items_count(self):
        """Get total number of items in order"""
        return self.items.count()
    
    @property
    def total_quantity(self):
        """Get total quantity of all items"""
        return sum(item.quantity for item in self.items.all())
    
    @property
    def can_be_cancelled(self):
        """Check if order can be cancelled"""
        return self.status in ['confirmed', 'processing', 'packed']
    
    @property
    def can_be_tracked(self):
        """Check if order can be tracked"""
        return self.status in ['shipped', 'in_transit']
    
    @property
    def is_delivered(self):
        """Check if order is delivered"""
        return self.status == 'delivered'
    
    @property
    def can_be_reordered(self):
        """Check if order can be reordered"""
        return self.status in ['delivered', 'cancelled']


class OrderItem(models.Model):
    """Individual items within an order"""
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items', help_text="Order this item belongs to")
    
    # Product information (stored at time of order to preserve history)
    product = models.ForeignKey('products.Product', on_delete=models.PROTECT, help_text="Product being ordered")
    product_name = models.CharField(max_length=255, help_text="Product name at time of order")
    product_image = models.URLField(blank=True, null=True, help_text="Product image URL")
    
    # Seller information
    seller = models.ForeignKey(User, on_delete=models.PROTECT, related_name='sold_items', help_text="Seller of this product")
    seller_name = models.CharField(max_length=255, help_text="Seller name at time of order")
    
    # Quantity and pricing
    quantity = models.DecimalField(max_digits=10, decimal_places=2, help_text="Ordered quantity")
    unit = models.CharField(max_length=20, help_text="Unit of measurement")
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Price per unit at time of order")
    total_price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Total price for this item")
    
    # Farm details for traceability
    farm_details = JSONField(default=dict, blank=True, help_text="Farm and location details")
    
    # Item-specific status and notes
    item_status = models.CharField(max_length=20, choices=ORDER_STATUS_CHOICES, default='confirmed', help_text="Status of this specific item")
    notes = models.TextField(blank=True, help_text="Special notes for this item")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Order Item"
        verbose_name_plural = "Order Items"
        ordering = ['created_at']
    
    def save(self, *args, **kwargs):
        # Set product details from product if not provided
        if self.product and not self.product_name:
            self.product_name = self.product.title
            self.unit = self.product.unit
            if not self.unit_price:
                self.unit_price = self.product.price_per_unit
        
        # Set product image from primary image or first available image
        if self.product and not self.product_image:
            # Try to get primary image first
            primary_image = self.product.images.filter(is_primary=True).first()
            if primary_image:
                if primary_image.image:
                    self.product_image = primary_image.image.url
                elif primary_image.url:
                    self.product_image = primary_image.url
            else:
                # Get first available image if no primary image
                first_image = self.product.images.first()
                if first_image:
                    if first_image.image:
                        self.product_image = first_image.image.url
                    elif first_image.url:
                        self.product_image = first_image.url
        
        # Set seller details
        if self.product:
            try:
                # Check if seller is already set
                current_seller = self.seller
            except:
                # Seller not set, set it from product
                current_seller = None
                
            if not current_seller:
                self.seller = self.product.seller
                self.seller_name = self.product.seller.full_name
            elif not self.seller_name:
                # Ensure seller_name is populated even if seller is already set
                self.seller_name = self.seller.full_name
        
        # Calculate total price
        self.total_price = self.quantity * self.unit_price
        
        # Set farm details
        if self.product and not self.farm_details:
            # Product model does not have a `state` field. Use available location fields
            # (city and pincode) to build a farm_location string. Fall back to an empty string
            # if city is not provided.
            city = self.product.city or ''
            pincode = self.product.pincode or ''
            location_parts = [part for part in [city, pincode] if part]
            farm_location = ', '.join(location_parts) if location_parts else ''

            self.farm_details = {
                'farm_location': farm_location,
                'coordinates': {
                    'latitude': float(self.product.latitude) if self.product.latitude else None,
                    'longitude': float(self.product.longitude) if self.product.longitude else None,
                }
            }
        
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.quantity} x {self.product_name} in Order {self.order.id}"


class OrderTracking(models.Model):
    """Order tracking and status history"""
    
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='tracking', help_text="Order being tracked")
    tracking_number = models.CharField(max_length=100, blank=True, null=True, help_text="Carrier tracking number")
    delivery_partner = models.CharField(max_length=100, blank=True, help_text="Delivery service provider")
    
    # Delivery person details
    delivery_person_name = models.CharField(max_length=255, blank=True, help_text="Delivery person name")
    delivery_person_phone = models.CharField(max_length=15, blank=True, help_text="Delivery person contact")
    delivery_vehicle_number = models.CharField(max_length=20, blank=True, help_text="Delivery vehicle number")
    
    # Current location (for live tracking)
    current_latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    current_longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    current_address = models.CharField(max_length=500, blank=True, help_text="Current location address")
    distance_from_customer = models.CharField(max_length=50, blank=True, help_text="Distance from customer location")
    estimated_arrival = models.CharField(max_length=50, blank=True, help_text="Estimated arrival time")
    
    # Tracking metadata
    tracking_metadata = JSONField(default=dict, blank=True, help_text="Additional tracking information")
    last_location_update = models.DateTimeField(blank=True, null=True, help_text="Last location update time")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Order Tracking"
        verbose_name_plural = "Order Tracking Records"
    
    def __str__(self):
        return f"Tracking for Order {self.order.id}"
    
    @property
    def current_location(self):
        """Get current location coordinates"""
        if self.current_latitude and self.current_longitude:
            return {
                'latitude': float(self.current_latitude),
                'longitude': float(self.current_longitude),
                'address': self.current_address,
                'distance_from_customer': self.distance_from_customer,
                'estimated_arrival': self.estimated_arrival
            }
        return None


class OrderStatusHistory(models.Model):
    """History of order status changes"""
    
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='status_history', help_text="Order whose status changed")
    status = models.CharField(max_length=20, choices=ORDER_STATUS_CHOICES, help_text="Status at this point")
    title = models.CharField(max_length=255, help_text="Human-readable title for this status")
    message = models.TextField(help_text="Detailed message about this status change")
    location = models.CharField(max_length=255, blank=True, help_text="Location where status changed")
    
    # Who made the change
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, help_text="User who made this change")
    change_source = models.CharField(max_length=50, default='system', help_text="Source of the change (system, admin, api, etc.)")
    
    # Metadata
    metadata = JSONField(default=dict, blank=True, help_text="Additional status change metadata")
    
    timestamp = models.DateTimeField(auto_now_add=True, help_text="When this status change occurred")
    
    class Meta:
        verbose_name = "Order Status History"
        verbose_name_plural = "Order Status Histories"
        ordering = ['timestamp']
    
    def __str__(self):
        return f"Order {self.order.id} - {self.status} at {self.timestamp}"


class OrderRefund(models.Model):
    """Order refund information"""
    
    REFUND_STATUS_CHOICES = [
        ('initiated', 'Refund Initiated'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    REFUND_TYPE_CHOICES = [
        ('full', 'Full Refund'),
        ('partial', 'Partial Refund'),
        ('shipping_only', 'Shipping Only'),
        ('product_only', 'Product Only'),
    ]
    
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='refund', help_text="Order being refunded")
    refund_type = models.CharField(max_length=20, choices=REFUND_TYPE_CHOICES, default='full', help_text="Type of refund")
    refund_status = models.CharField(max_length=20, choices=REFUND_STATUS_CHOICES, default='initiated', help_text="Refund status")
    
    # Refund amounts
    refund_amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Amount being refunded")
    processing_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'), help_text="Processing fee deducted")
    final_refund_amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Final amount refunded to customer")
    
    # Refund details
    reason = models.TextField(help_text="Reason for refund")
    refund_transaction_id = models.CharField(max_length=255, blank=True, null=True, help_text="Refund transaction ID")
    estimated_refund_days = models.CharField(max_length=50, default='5-7 business days', help_text="Estimated refund time")
    
    # Timestamps
    initiated_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    
    # Who initiated the refund
    initiated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, help_text="User who initiated refund")
    
    class Meta:
        verbose_name = "Order Refund"
        verbose_name_plural = "Order Refunds"
    
    def __str__(self):
        return f"Refund for Order {self.order.id} - ₹{self.refund_amount}"
    
    def save(self, *args, **kwargs):
        # Calculate final refund amount
        self.final_refund_amount = self.refund_amount - self.processing_fee
        super().save(*args, **kwargs)


class OrderAnalytics(models.Model):
    """Order analytics and statistics"""
    
    date = models.DateField(unique=True, help_text="Date for these analytics")
    
    # Order counts
    total_orders = models.IntegerField(default=0)
    pending_orders = models.IntegerField(default=0)
    confirmed_orders = models.IntegerField(default=0)
    delivered_orders = models.IntegerField(default=0)
    cancelled_orders = models.IntegerField(default=0)
    
    # Revenue
    total_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    average_order_value = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # Product analytics
    top_products = JSONField(default=list, blank=True, help_text="Top selling products")
    top_sellers = JSONField(default=list, blank=True, help_text="Top performing sellers")
    
    # Geographic analytics
    top_cities = JSONField(default=list, blank=True, help_text="Top cities by order volume")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Order Analytics"
        verbose_name_plural = "Order Analytics"
        ordering = ['-date']
    
    def __str__(self):
        return f"Analytics for {self.date} - {self.total_orders} orders"
