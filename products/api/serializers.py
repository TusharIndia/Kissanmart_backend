from rest_framework import serializers
from ..models import Category, Product, ProductImage
from django.core.validators import URLValidator
from django.utils import timezone
import math
from django.core.files.base import ContentFile
import requests
from urllib.parse import urlparse
import os
from django.core.files.uploadedfile import InMemoryUploadedFile, TemporaryUploadedFile
from decimal import Decimal

# helper to normalize unit strings to canonical values used in the Product model
def _normalize_unit(unit_val):
    if unit_val is None:
        return unit_val
    s = str(unit_val).strip().lower()
    if not s:
        return unit_val
    # common mappings and fuzzy matches
    if 'quint' in s:
        return 'QUINTAL'
    if s in ('kg', 'kilogram', 'kilograms') or 'kg' == s:
        return 'KG'
    if 'ton' in s or 'tonne' in s:
        return 'TON'
    if 'dozen' in s:
        return 'DOZEN'
    if s in ('unit', 'piece', 'pieces'):
        return 'UNIT'
    # If the value already looks like an uppercase canonical value, return uppercase
    up = str(unit_val).strip().upper()
    return up

# Allowed buyer categories for visibility (match users.models CustomUser.BUYER_CATEGORY_CHOICES)
ALLOWED_BUYER_CATEGORIES = {'mandi_owner', 'shopkeeper', 'community'}


def download_remote_image(url, timeout=10):
    """Download a remote image and return a Django ContentFile suitable for ImageField.

    Returns None on failure.
    """
    if not url:
        return None
    # Quick validation
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return None
    except Exception:
        return None

    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code != 200:
            return None
        content_type = resp.headers.get('Content-Type', '')
        if not content_type.startswith('image'):
            return None

        # derive a filename
        filename = os.path.basename(parsed.path) or 'image'
        # ensure we have an extension
        if not os.path.splitext(filename)[1]:
            # try to infer extension from content-type
            ext = content_type.split('/')[-1].split(';')[0]
            filename = f"{filename}.{ext}"

        return ContentFile(resp.content, name=filename)
    except Exception:
        return None


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'description']


class ProductImageSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = ProductImage
        fields = ['id', 'url', 'caption', 'is_primary']

    def get_url(self, obj):
        if obj.url:
            return obj.url
        try:
            return obj.image.url
        except Exception:
            return None


class ImageOrUrlField(serializers.Field):
    """Accept either a dict with {'url': 'http...', 'isPrimary': bool} or an uploaded file object.

    This is used as the child of the `images` ListField so clients can send
    either JSON objects with remote URLs or multipart file uploads from the frontend.
    """
    def to_internal_value(self, data):
        # Dict containing a URL
        if isinstance(data, dict):
            if data.get('url'):
                return data
            raise serializers.ValidationError('dict image must contain "url"')

        # Uploaded files from multipart/form-data will generally be
        # InMemoryUploadedFile or TemporaryUploadedFile instances.
        if isinstance(data, (InMemoryUploadedFile, TemporaryUploadedFile)) or hasattr(data, 'read'):
            return data

        raise serializers.ValidationError('Expected an uploaded file or a dict with "url"')

    def to_representation(self, value):
        # Not used for write-only images, but provide a sensible repr if needed
        try:
            return {'url': value.url}
        except Exception:
            return None


class ProductListSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source='uuid', read_only=True)
    farmerId = serializers.CharField(source='seller.id', read_only=True)
    # Keep names matching the read-model expected by clients; avoid redundant `source` where name==field
    title = serializers.CharField()
    description = serializers.CharField()
    # Return category as a nested object (if a Category exists with that name),
    # otherwise return the raw category string for backwards compatibility.
    category = serializers.SerializerMethodField()
    crop = serializers.CharField()
    variety = serializers.CharField()
    grade = serializers.CharField()
    availableQuantity = serializers.DecimalField(source='quantity_available', max_digits=12, decimal_places=3)
    quantityUnit = serializers.SerializerMethodField()
    pricePerUnit = serializers.DecimalField(source='price_per_unit', max_digits=12, decimal_places=2)
    priceCurrency = serializers.CharField(source='price_currency', allow_null=True, required=False)
    priceType = serializers.CharField(source='price_type', allow_null=True, required=False)
    marketPriceSource = serializers.CharField(source='market_price_source', allow_null=True, required=False)
    mandiPriceReference = serializers.JSONField(source='mandi_price_reference', allow_null=True, required=False)
    location = serializers.SerializerMethodField()
    buyerCategoryVisibility = serializers.JSONField(source='buyer_category_visibility', allow_null=True, required=False)
    images = ProductImageSerializer(many=True, read_only=True)
    pexelsImageUrl = serializers.URLField(source='pexels_image_url', read_only=True)
    status = serializers.CharField(read_only=True)
    createdAt = serializers.DateTimeField(source='created_at')
    updatedAt = serializers.DateTimeField(source='updated_at')
    distanceMeters = serializers.IntegerField(read_only=True)
    # Include seller details (id/uuid, name, mobile) for frontend to display/contact seller
    seller = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'farmerId', 'title', 'description', 'category', 'crop', 'variety', 'grade',
            'availableQuantity', 'quantityUnit', 'pricePerUnit', 'priceCurrency', 'priceType',
            'marketPriceSource', 'mandiPriceReference', 'location', 'buyerCategoryVisibility',
            'images', 'pexelsImageUrl', 'status', 'createdAt', 'updatedAt', 'distanceMeters', 'seller'
        ]

    def get_location(self, obj):
        if obj.latitude is None or obj.longitude is None or obj.latitude == 0.0 or obj.longitude == 0.0:
            return None
        return {
            'latitude': obj.latitude,
            'longitude': obj.longitude,
            'city': obj.city,
            'pincode': obj.pincode
        }

    def get_category(self, obj):
        # If the project actually stores category as a string on Product (legacy),
        # try to resolve it to a Category model instance by name. If found,
        # return the serialized Category object; otherwise return the raw string.
        try:
            if not obj.category:
                return None
            cat = Category.objects.filter(name__iexact=str(obj.category)).first()
            if cat:
                return CategorySerializer(cat).data
            return obj.category
        except Exception:
            return obj.category

    def get_seller(self, obj):
        try:
            s = obj.seller
            # prefer uuid if user model has it, else use pk
            seller_id = getattr(s, 'uuid', None) or getattr(s, 'id', None)
            return {
                'id': seller_id,
                'full_name': getattr(s, 'full_name', None),
                'mobile_number': getattr(s, 'mobile_number', None),
            }
        except Exception:
            return None

    def get_quantityUnit(self, obj):
        try:
            u = getattr(obj, 'unit', None)
            if not u:
                return None
            # return lowercase kg for KG and otherwise lowercase of canonical
            if str(u).upper() == 'KG':
                return 'kg'
            return str(u).lower()
        except Exception:
            return getattr(obj, 'unit', None)


class ProductCreateSerializer(serializers.ModelSerializer):
    # location is required for product creation
    location = serializers.DictField(write_only=True, required=True)
    # Validate buyer categories against the allowed set in validate()
    buyerCategoryVisibility = serializers.ListField(child=serializers.CharField(), required=False)
    # Accept JSON objects for images (e.g. {"url": "https://..."}).
    # Note: uploaded file uploads (multipart) are still supported by providing
    # file objects in the request data; the create/update logic handles both types.
    images = serializers.ListField(child=ImageOrUrlField(), write_only=True, required=False)
    # CamelCase aliases accepted from some clients (write-only aliases mapped in create())
    availableQuantity = serializers.DecimalField(write_only=True, max_digits=12, decimal_places=3, required=False)
    quantityUnit = serializers.CharField(write_only=True, required=False)
    pricePerUnit = serializers.DecimalField(write_only=True, max_digits=12, decimal_places=2, required=False)
    priceCurrency = serializers.CharField(write_only=True, required=False)
    priceType = serializers.CharField(write_only=True, required=False)
    # allow null when clients send null for non-market_linked price types
    marketPriceSource = serializers.CharField(write_only=True, required=False, allow_null=True, allow_blank=True)
    # NOTE: do not add a separate capitalized `Category` field; the model-level
    # `category` field (string) is already present and included in `fields`.

    class Meta:
        model = Product
        fields = [
            'title', 'description', 'category', 'crop', 'variety', 'grade',
            'available_quantity', 'availableQuantity', 'quantity_unit', 'quantityUnit',
            'price_per_unit', 'pricePerUnit', 'price_currency', 'priceCurrency',
            'price_type', 'priceType', 'market_price_source', 'marketPriceSource',
            'location', 'buyerCategoryVisibility', 'images', 'metadata'
        ]
        extra_kwargs = {
            'price_type': {'required': False},
        }

    def validate(self, data):
        # Validate required fields per frontend doc
        location = data.get('location')
        if 'latitude' not in location or 'longitude' not in location or 'city' not in location:
            raise serializers.ValidationError({'location': 'location.city, location.latitude and location.longitude are required'})

        price_type = data.get('price_type') or data.get('priceType') or 'fixed'
        market_source = data.get('market_price_source') or data.get('marketPriceSource')
        if price_type == 'market_linked' and not market_source:
            raise serializers.ValidationError({'marketPriceSource': 'required when priceType is market_linked'})

        # Basic validation for numeric fields
        # availableQuantity should be >= 0
        aq = data.get('available_quantity') or data.get('availableQuantity')
        if aq is None:
            raise serializers.ValidationError({'availableQuantity': 'This field is required'})
        try:
            if float(aq) < 0:
                raise serializers.ValidationError({'availableQuantity': 'must be >= 0'})
        except (TypeError, ValueError):
            raise serializers.ValidationError({'availableQuantity': 'invalid number'})

        pp = data.get('price_per_unit') or data.get('pricePerUnit')
        if pp is None:
            raise serializers.ValidationError({'pricePerUnit': 'This field is required'})
        try:
            if float(pp) < 0:
                raise serializers.ValidationError({'pricePerUnit': 'must be >= 0'})
        except (TypeError, ValueError):
            raise serializers.ValidationError({'pricePerUnit': 'invalid number'})

        # latitude/longitude ranges if provided
        if location is not None and location:
            lat = location.get('latitude')
            lon = location.get('longitude')
            if lat is not None and lon is not None:
                if not (-90 <= float(lat) <= 90) or not (-180 <= float(lon) <= 180):
                    raise serializers.ValidationError({'location': 'latitude must be -90..90 and longitude -180..180'})

        # Validate buyerCategoryVisibility values if present
        bcv = data.get('buyerCategoryVisibility')
        if bcv is not None:
            if not isinstance(bcv, (list, tuple)):
                raise serializers.ValidationError({'buyerCategoryVisibility': 'must be a list of allowed categories'})
            invalid = [v for v in bcv if v not in ALLOWED_BUYER_CATEGORIES]
            if invalid:
                raise serializers.ValidationError({'buyerCategoryVisibility': f'invalid categories: {invalid}. allowed: {sorted(ALLOWED_BUYER_CATEGORIES)}'})

        return data

    def create(self, validated_data, seller=None):
        images = validated_data.pop('images', [])
        location = validated_data.pop('location', {})
        buyer_visibility = validated_data.pop('buyerCategoryVisibility', None)

        # Normalize fields and map aliases
        # Map camelCase to snake_case where user may have passed camelCase
        # Map camelCase aliases to actual model DB fields
        if 'availableQuantity' in validated_data:
            validated_data['quantity_available'] = validated_data.pop('availableQuantity')
        if 'quantityUnit' in validated_data:
            validated_data['unit'] = _normalize_unit(validated_data.pop('quantityUnit'))
        if 'pricePerUnit' in validated_data:
            validated_data['price_per_unit'] = validated_data.pop('pricePerUnit')
        if 'priceCurrency' in validated_data:
            validated_data['price_currency'] = validated_data.pop('priceCurrency')
        if 'priceType' in validated_data:
            validated_data['price_type'] = validated_data.pop('priceType')
        if 'marketPriceSource' in validated_data:
            validated_data['market_price_source'] = validated_data.pop('marketPriceSource')

        # Allow caller to pass seller via serializer.save(seller=user)
        # Prefer explicit seller kwarg passed to serializer.save(seller=...)
        if seller is None:
            seller = getattr(self, 'context', {}).get('seller')
        # some callers pass seller as kwarg to save(); DRF passes these to serializer.create via **kwargs
        # but to keep compatibility, also accept self._kwargs if present
        try:
            # serializer.save(seller=...) will place seller in self.validated_data? no - DRF passes kwargs to create as second param
            pass
        except Exception:
            pass

        # If a seller kwarg was provided to create, it'll be in self.context['seller'] by our view wrapper
        if seller is not None:
            validated_data['seller'] = seller

        # Normalize units: if seller provided quantity in quintals, convert to kilograms.
        # Accept fuzzy matches (case-insensitive substring 'quint').
        unit_val = validated_data.get('unit')
        # normalize any unit string we received
        if unit_val is not None:
            unit_val = _normalize_unit(unit_val)
            validated_data['unit'] = unit_val

        if unit_val and unit_val == 'QUINTAL':
            # convert available quantity (quintals -> kg)
            aq = validated_data.get('quantity_available')
            if aq is not None:
                try:
                    validated_data['quantity_available'] = Decimal(str(aq)) * Decimal('100')
                except Exception:
                    pass

            # convert price_per_unit (price per quintal -> price per kg)
            pp = validated_data.get('price_per_unit')
            if pp is not None:
                try:
                    # keep two decimal places for price
                    validated_data['price_per_unit'] = (Decimal(str(pp)) / Decimal('100')).quantize(Decimal('0.01'))
                except Exception:
                    pass

            # convert min_order_quantity if provided
            moq = validated_data.get('min_order_quantity')
            if moq is not None:
                try:
                    validated_data['min_order_quantity'] = Decimal(str(moq)) * Decimal('100')
                except Exception:
                    pass

            # store normalized unit as kilograms
            validated_data['unit'] = 'KG'

        product = Product.objects.create(**validated_data)

        # attach location - location is required, so always provided
        product.latitude = location.get('latitude')
        product.longitude = location.get('longitude')
        product.city = location.get('city')
        product.pincode = location.get('pincode')
        if buyer_visibility is not None:
            product.buyer_category_visibility = buyer_visibility
        product.save()

        # Create images. Support two types for each entry:
        # - Uploaded file objects (ImageField) or
        # - Dicts with {'url': '<http(s)://...>', 'isPrimary': bool} as provided by some clients.
        for img in images:
            if isinstance(img, dict) and img.get('url'):
                ProductImage.objects.create(
                    product=product, 
                    url=img['url'], 
                    is_primary=img.get('isPrimary', False)
                )
            else:
                # assume it's already a file-like object acceptable to ImageField
                ProductImage.objects.create(product=product, image=img)

        return product


class ProductUpdateSerializer(serializers.ModelSerializer):
    location = serializers.DictField(write_only=True, required=False)
    buyerCategoryVisibility = serializers.ListField(child=serializers.CharField(), required=False)
    images = serializers.ListField(child=ImageOrUrlField(), write_only=True, required=False)
    # CamelCase aliases accepted from some clients (write-only aliases mapped in update())
    availableQuantity = serializers.DecimalField(write_only=True, max_digits=12, decimal_places=3, required=False)
    quantityUnit = serializers.CharField(write_only=True, required=False)
    pricePerUnit = serializers.DecimalField(write_only=True, max_digits=12, decimal_places=2, required=False)
    priceCurrency = serializers.CharField(write_only=True, required=False)
    priceType = serializers.CharField(write_only=True, required=False)
    marketPriceSource = serializers.CharField(write_only=True, required=False, allow_null=True, allow_blank=True)
    # Make title read-only here so frontend edit modal changing category does not accidentally
    # modify title — we want category to be editable via PUT/PATCH instead of title.
    title = serializers.CharField(read_only=True)
    category = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = Product
        fields = [
            'title', 'description', 'category', 'crop', 'variety', 'grade',
            'available_quantity', 'availableQuantity', 'quantity_unit', 'quantityUnit',
            'price_per_unit', 'pricePerUnit', 'price_currency', 'priceCurrency',
            'price_type', 'priceType', 'market_price_source', 'marketPriceSource',
            'location', 'buyerCategoryVisibility', 'images', 'metadata', 'status'
        ]

    def validate(self, data):
        # If price_type becomes market_linked ensure market_price_source present
        price_type = data.get('price_type') or data.get('priceType')
        market_source = data.get('market_price_source') or data.get('marketPriceSource')
        if price_type == 'market_linked' and not market_source:
            raise serializers.ValidationError({'marketPriceSource': 'required when priceType is market_linked'})
        return data

    def update(self, instance, validated_data):
        images = validated_data.pop('images', None)
        location = validated_data.pop('location', None)
        buyer_visibility = validated_data.pop('buyerCategoryVisibility', None)

        # map camelCase aliases
        if 'availableQuantity' in validated_data:
            validated_data['quantity_available'] = validated_data.pop('availableQuantity')
        if 'quantityUnit' in validated_data:
            validated_data['unit'] = _normalize_unit(validated_data.pop('quantityUnit'))
        if 'pricePerUnit' in validated_data:
            validated_data['price_per_unit'] = validated_data.pop('pricePerUnit')
        if 'priceCurrency' in validated_data:
            validated_data['price_currency'] = validated_data.pop('priceCurrency')
        if 'priceType' in validated_data:
            validated_data['price_type'] = validated_data.pop('priceType')
        if 'marketPriceSource' in validated_data:
            validated_data['market_price_source'] = validated_data.pop('marketPriceSource')

        # If the incoming data used quintals as unit, normalize and convert quantities/prices to KG
        unit_val = validated_data.get('unit')
        if unit_val is not None:
            unit_val = _normalize_unit(unit_val)
            validated_data['unit'] = unit_val

        if unit_val and unit_val == 'QUINTAL':
            # convert available_quantity if present
            aq = validated_data.get('quantity_available')
            if aq is not None:
                try:
                    validated_data['quantity_available'] = Decimal(str(aq)) * Decimal('100')
                except Exception:
                    pass

            # convert price_per_unit if present (per quintal -> per kg)
            pp = validated_data.get('price_per_unit')
            if pp is not None:
                try:
                    validated_data['price_per_unit'] = (Decimal(str(pp)) / Decimal('100')).quantize(Decimal('0.01'))
                except Exception:
                    pass

            # convert min_order_quantity if present
            moq = validated_data.get('min_order_quantity')
            if moq is not None:
                try:
                    validated_data['min_order_quantity'] = Decimal(str(moq)) * Decimal('100')
                except Exception:
                    pass

            validated_data['unit'] = 'KG'

        for attr, val in validated_data.items():
            setattr(instance, attr, val)

        if location:
            instance.latitude = location.get('latitude', instance.latitude)
            instance.longitude = location.get('longitude', instance.longitude)
            instance.city = location.get('city', instance.city)
            instance.pincode = location.get('pincode', instance.pincode)

        if buyer_visibility is not None:
            instance.buyer_category_visibility = buyer_visibility

        instance.save()

        if images is not None and images:
            instance.images.all().delete()
            for img in images:
                if isinstance(img, dict) and img.get('url'):
                    ProductImage.objects.create(
                        product=instance, 
                        url=img['url'], 
                        is_primary=img.get('isPrimary', False)
                    )
                else:
                    ProductImage.objects.create(product=instance, image=img)

        return instance
