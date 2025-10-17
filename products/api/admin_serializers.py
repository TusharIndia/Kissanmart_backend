from rest_framework import serializers
from ..models import Product, ProductImage
from users.models import CustomUser
from django.utils import timezone


class AdminProductSellerSerializer(serializers.ModelSerializer):
    """Serializer for seller information in admin product views"""
    userId = serializers.CharField(source='id', read_only=True)
    fullName = serializers.CharField(source='full_name', read_only=True)
    mobileNumber = serializers.CharField(source='mobile_number', read_only=True)
    userType = serializers.CharField(source='user_type', read_only=True)
    city = serializers.CharField(read_only=True)
    state = serializers.CharField(read_only=True)
    pincode = serializers.CharField(read_only=True)
    registrationMethod = serializers.CharField(source='registration_method', read_only=True)
    isMobileVerified = serializers.BooleanField(source='is_mobile_verified', read_only=True)
    isProfileComplete = serializers.BooleanField(source='is_profile_complete', read_only=True)
    isActive = serializers.BooleanField(source='is_active', read_only=True)
    joinedAt = serializers.DateTimeField(source='created_at', read_only=True)
    lastUpdated = serializers.DateTimeField(source='updated_at', read_only=True)

    class Meta:
        model = CustomUser
        fields = [
            'userId', 'fullName', 'mobileNumber', 'userType', 'city', 'state', 
            'pincode', 'registrationMethod', 'isMobileVerified', 'isProfileComplete', 
            'isActive', 'joinedAt', 'lastUpdated'
        ]


class AdminProductImageSerializer(serializers.ModelSerializer):
    """Serializer for product images in admin views"""
    imageUrl = serializers.SerializerMethodField()
    
    class Meta:
        model = ProductImage
        fields = ['id', 'imageUrl', 'url', 'is_primary', 'caption']
    
    def get_imageUrl(self, obj):
        if obj.url:
            return obj.url
        try:
            return obj.image.url if obj.image else None
        except Exception:
            return None


class AdminProductListSerializer(serializers.ModelSerializer):
    """Serializer for product listing in admin dashboard with essential information"""
    productId = serializers.CharField(source='uuid', read_only=True)
    seller = AdminProductSellerSerializer(read_only=True)
    
    # Product details
    title = serializers.CharField(read_only=True)
    category = serializers.CharField(read_only=True)
    crop = serializers.CharField(read_only=True)
    variety = serializers.CharField(read_only=True)
    grade = serializers.CharField(read_only=True)
    pexelsImageUrl = serializers.CharField(source='pexels_image_url', read_only=True)
    
    # Quantity and pricing
    availableQuantity = serializers.DecimalField(source='quantity_available', max_digits=12, decimal_places=3, read_only=True)
    quantityUnit = serializers.CharField(source='unit', read_only=True)
    pricePerUnit = serializers.DecimalField(source='price_per_unit', max_digits=12, decimal_places=2, read_only=True)
    totalValue = serializers.DecimalField(source='total_value', max_digits=15, decimal_places=2, read_only=True)
    
    # Location
    location = serializers.SerializerMethodField()
    
    # Status and visibility
    status = serializers.CharField(read_only=True)
    isPublished = serializers.BooleanField(source='is_published', read_only=True)
    targetBuyers = serializers.CharField(source='target_buyers_display', read_only=True)
    
    # Primary image
    primaryImage = serializers.SerializerMethodField()
    
    # Timestamps
    uploadedAt = serializers.DateTimeField(source='created_at', read_only=True)
    lastUpdated = serializers.DateTimeField(source='updated_at', read_only=True)
    
    # Analytics
    daysListed = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'productId', 'seller', 'title', 'category', 'crop', 'variety', 'grade',
            'availableQuantity', 'quantityUnit', 'pricePerUnit', 'totalValue',
            'location', 'status', 'isPublished', 'targetBuyers', 'primaryImage',
            'uploadedAt', 'lastUpdated', 'daysListed', 'pexelsImageUrl'
        ]

    def get_location(self, obj):
        if obj.latitude is None or obj.longitude is None:
            return None
        return {
            'latitude': float(obj.latitude) if obj.latitude else None,
            'longitude': float(obj.longitude) if obj.longitude else None,
            'city': obj.city,
            'pincode': obj.pincode
        }

    def get_primaryImage(self, obj):
        primary_image = obj.images.filter(is_primary=True).first()
        if not primary_image:
            primary_image = obj.images.first()
        
        if primary_image:
            return AdminProductImageSerializer(primary_image).data
        return None

    def get_daysListed(self, obj):
        """Calculate how many days the product has been listed"""
        if obj.created_at:
            delta = timezone.now() - obj.created_at
            return delta.days
        return 0


class AdminProductDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for individual product view in admin"""
    productId = serializers.CharField(source='uuid', read_only=True)
    seller = AdminProductSellerSerializer(read_only=True)
    
    # Product details
    title = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    category = serializers.CharField(read_only=True)
    crop = serializers.CharField(read_only=True)
    variety = serializers.CharField(read_only=True)
    grade = serializers.CharField(read_only=True)
    pexelsImageUrl = serializers.CharField(source='pexels_image_url', read_only=True)
    
    # Quantity and pricing details
    availableQuantity = serializers.DecimalField(source='quantity_available', max_digits=12, decimal_places=3, read_only=True)
    quantityUnit = serializers.CharField(source='unit', read_only=True)
    pricePerUnit = serializers.DecimalField(source='price_per_unit', max_digits=12, decimal_places=2, read_only=True)
    priceCurrency = serializers.CharField(source='price_currency', read_only=True)
    priceType = serializers.CharField(source='price_type', read_only=True)
    marketPriceSource = serializers.CharField(source='market_price_source', read_only=True)
    mandiPriceReference = serializers.JSONField(source='mandi_price_reference', read_only=True)
    totalValue = serializers.DecimalField(source='total_value', max_digits=15, decimal_places=2, read_only=True)
    minOrderQuantity = serializers.DecimalField(source='min_order_quantity', max_digits=10, decimal_places=2, read_only=True)
    
    # Location details
    location = serializers.SerializerMethodField()
    
    # Target buyers
    targetBuyers = serializers.SerializerMethodField()
    buyerCategoryVisibility = serializers.JSONField(source='buyer_category_visibility', read_only=True)
    
    # Images  
    images = AdminProductImageSerializer(many=True, read_only=True)
    totalImages = serializers.SerializerMethodField()
    
    # Status and publishing
    status = serializers.CharField(read_only=True)
    isPublished = serializers.BooleanField(source='is_published', read_only=True)
    
    # Metadata
    metadata = serializers.JSONField(read_only=True)
    
    # Timestamps and analytics
    uploadedAt = serializers.DateTimeField(source='created_at', read_only=True)
    lastUpdated = serializers.DateTimeField(source='updated_at', read_only=True)
    daysListed = serializers.SerializerMethodField()
    
    class Meta:
        model = Product
        fields = [
            'productId', 'seller', 'title', 'description', 'category', 'crop', 'variety', 'grade',
            'availableQuantity', 'quantityUnit', 'pricePerUnit', 'priceCurrency', 'priceType',
            'marketPriceSource', 'mandiPriceReference', 'totalValue', 'minOrderQuantity',
            'location', 'targetBuyers', 'buyerCategoryVisibility', 'images', 'totalImages',
            'status', 'isPublished', 'metadata', 'uploadedAt', 'lastUpdated', 'daysListed', 'pexelsImageUrl'
        ]

    def get_location(self, obj):
        return {
            'latitude': float(obj.latitude) if obj.latitude else None,
            'longitude': float(obj.longitude) if obj.longitude else None,
            'city': obj.city,
            'state': obj.seller.state if obj.seller else None,
            'pincode': obj.pincode,
            'address': obj.seller.address if obj.seller else None
        }

    def get_targetBuyers(self, obj):
        targets = []
        if obj.target_mandi_owners:
            targets.append({
                'type': 'mandi_owner',
                'displayName': 'Mandi Owners',
                'enabled': True
            })
        if obj.target_shopkeepers:
            targets.append({
                'type': 'shopkeeper', 
                'displayName': 'Shopkeepers',
                'enabled': True
            })
        if obj.target_communities:
            targets.append({
                'type': 'community',
                'displayName': 'Communities',
                'enabled': True
            })
        
        return targets if targets else [{
            'type': 'all',
            'displayName': 'All Buyers',
            'enabled': True
        }]

    def get_totalImages(self, obj):
        return obj.images.count()

    def get_daysListed(self, obj):
        if obj.created_at:
            delta = timezone.now() - obj.created_at
            return delta.days
        return 0


class AdminProductStatsSerializer(serializers.Serializer):
    """Serializer for product statistics in admin dashboard"""
    totalProducts = serializers.IntegerField()
    activeProducts = serializers.IntegerField()
    inactiveProducts = serializers.IntegerField()
    soldOutProducts = serializers.IntegerField()
    totalValue = serializers.DecimalField(max_digits=20, decimal_places=2)
    averagePrice = serializers.DecimalField(max_digits=12, decimal_places=2)
    topCategories = serializers.ListField()
    topCities = serializers.ListField()
    recentUploads = serializers.IntegerField()  # Products uploaded in last 7 days
    
    
class AdminProductUpdateSerializer(serializers.ModelSerializer):
    """Serializer for admin to update product status"""
    isPublished = serializers.BooleanField(source='is_published', required=False)
    
    class Meta:
        model = Product
        fields = ['isPublished']
    
    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance