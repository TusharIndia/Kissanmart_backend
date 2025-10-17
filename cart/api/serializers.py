from rest_framework import serializers
from decimal import Decimal
from cart.models import Cart, CartItem
from products.models import Product
from products.api.serializers import ProductListSerializer


class CartItemSerializer(serializers.ModelSerializer):
    """Serializer for cart items"""
    product = ProductListSerializer(read_only=True)
    product_id = serializers.UUIDField(write_only=True)
    subtotal = serializers.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        read_only=True
    )
    availability_status = serializers.CharField(read_only=True)
    is_available = serializers.BooleanField(read_only=True)
    unit_price = serializers.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        read_only=True
    )

    class Meta:
        model = CartItem
        fields = [
            'id', 'product', 'product_id', 'quantity', 'unit_price', 
            'subtotal', 'availability_status', 'is_available', 
            'added_at', 'updated_at'
        ]
        read_only_fields = ['id', 'added_at', 'updated_at']

    def validate_product_id(self, value):
        """Validate that the product exists and is available"""
        try:
            product = Product.objects.get(uuid=value, is_published=True)
            return value
        except Product.DoesNotExist:
            raise serializers.ValidationError("Product not found or not available")

    def validate_quantity(self, value):
        """Validate quantity is positive"""
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than 0")
        return value

    def validate(self, attrs):
        """Validate that requested quantity is available"""
        if 'product_id' in attrs:
            try:
                product = Product.objects.get(uuid=attrs['product_id'])
                quantity = attrs.get('quantity', Decimal('1'))
                
                # Check if enough quantity is available
                if product.quantity_available < quantity:
                    raise serializers.ValidationError({
                        'quantity': f"Only {product.quantity_available} {product.unit} available"
                    })
                
                # Check minimum order quantity
                if product.min_order_quantity and quantity < product.min_order_quantity:
                    raise serializers.ValidationError({
                        'quantity': f"Minimum order quantity is {product.min_order_quantity} {product.unit}"
                    })
                    
            except Product.DoesNotExist:
                pass  # This will be caught by product_id validation
                
        return attrs


class CartSerializer(serializers.ModelSerializer):
    """Serializer for shopping cart"""
    items = CartItemSerializer(many=True, read_only=True)
    total_items = serializers.IntegerField(read_only=True)
    total_amount = serializers.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        read_only=True
    )
    items_count = serializers.IntegerField(read_only=True)
    user_info = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = [
            'user_info', 'items', 'total_items', 'total_amount', 
            'items_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_user_info(self, obj):
        """Get basic user information"""
        return {
            'id': obj.user.id,
            'identifier': obj.user.get_identifier(),
            'full_name': obj.user.full_name
        }


class AddToCartSerializer(serializers.Serializer):
    """Serializer for adding items to cart"""
    product_id = serializers.UUIDField()
    quantity = serializers.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=Decimal('1')
    )

    def validate_product_id(self, value):
        """Validate that the product exists and is available"""
        try:
            product = Product.objects.get(uuid=value, is_published=True)
            return value
        except Product.DoesNotExist:
            raise serializers.ValidationError("Product not found or not available")

    def validate_quantity(self, value):
        """Validate quantity is positive"""
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than 0")
        return value

    def validate(self, attrs):
        """Validate product availability and quantity"""
        try:
            product = Product.objects.get(uuid=attrs['product_id'])
            quantity = attrs['quantity']
            
            # Get user's cart and check existing quantity
            user = self.context['request'].user
            cart, _ = Cart.objects.get_or_create(user=user)
            
            existing_item = cart.items.filter(product=product).first()
            total_quantity = quantity
            if existing_item:
                total_quantity += existing_item.quantity
            
            # Check if enough quantity is available
            if product.quantity_available < total_quantity:
                available = product.quantity_available
                if existing_item:
                    available -= existing_item.quantity
                raise serializers.ValidationError({
                    'quantity': f"Only {available} {product.unit} more can be added to cart"
                })
            
            # Check minimum order quantity
            if product.min_order_quantity and total_quantity < product.min_order_quantity:
                raise serializers.ValidationError({
                    'quantity': f"Minimum order quantity is {product.min_order_quantity} {product.unit}"
                })
                
        except Product.DoesNotExist:
            pass  # This will be caught by product_id validation
            
        return attrs

    def create(self, validated_data):
        """Add item to cart"""
        user = self.context['request'].user
        product = Product.objects.get(uuid=validated_data['product_id'])
        quantity = validated_data['quantity']
        
        cart, _ = Cart.objects.get_or_create(user=user)
        
        # Check if item already exists in cart
        cart_item, created = CartItem.objects.get_or_create(
            cart=cart,
            product=product,
            defaults={
                'quantity': quantity,
                'unit_price': product.price_per_unit
            }
        )
        
        if not created:
            # Update quantity if item already exists
            cart_item.quantity += quantity
            cart_item.save()
        
        return cart_item


