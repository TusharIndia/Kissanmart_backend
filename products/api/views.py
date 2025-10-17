from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.core.cache import cache
import math
import logging
from ..models import Product, Category, ProductImage
from .serializers import (
    ProductListSerializer, ProductCreateSerializer, ProductUpdateSerializer
)
import json
from django.db import connection
from django.db.utils import DatabaseError
import os
import requests
from django.conf import settings
from drf_spectacular.utils import extend_schema
from ..services import pexels_service

logger = logging.getLogger(__name__)

# Allowed buyer categories (must match serializer allowed set and users.BUYER_CATEGORY_CHOICES)
# Note: values come from users.models.CustomUser.BUYER_CATEGORY_CHOICES: 'mandi_owner','shopkeeper','community'
ALLOWED_BUYER_CATEGORIES = {'mandi_owner', 'shopkeeper', 'community'}


def haversine_distance(lat1, lon1, lat2, lon2):
    # Returns distance in meters
    # Convert all inputs to float to handle DecimalField values
    lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
    R = 6371000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return int(R * c)


@extend_schema(operation_id='seller-products-list', responses={200: ProductListSerializer(many=True)})
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_seller_products(request):
    """Get all products for the authenticated seller"""
    # Only smart_seller users (or staff) may access seller product listing
    if not getattr(request.user, 'is_authenticated', False):
        return Response({'error': {'code': 'AUTH_REQUIRED', 'message': 'Authentication required'}}, status=status.HTTP_401_UNAUTHORIZED, headers={'Content-Type': 'application/json'})
    if request.user.user_type != 'smart_seller' and not getattr(request.user, 'is_staff', False):
        return Response({'error': {'code': 'FORBIDDEN', 'message': 'Only smart_seller accounts may access seller products'}}, status=status.HTTP_403_FORBIDDEN)

    products = Product.objects.filter(seller=request.user).prefetch_related('images')
    serializer = ProductListSerializer(products, many=True)
    return Response({'items': serializer.data, 'totalCount': products.count()})


@extend_schema(request=ProductCreateSerializer, responses={201: ProductListSerializer})
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_product(request):
    """Farmer creates product. Seller is taken from token."""
    # Only smart_seller users (and staff ops) may create products
    if not getattr(request.user, 'is_authenticated', False):
        return Response({'error': {'code': 'AUTH_REQUIRED', 'message': 'Authentication required'}}, status=status.HTTP_401_UNAUTHORIZED)
    if request.user.user_type != 'smart_seller' and not getattr(request.user, 'is_staff', False):
        return Response({'error': {'code': 'FORBIDDEN', 'message': 'Only smart_seller accounts may create products'}}, status=status.HTTP_403_FORBIDDEN)

    # Prepare data for serializer - combine JSON image objects with uploaded files
    data = request.data.copy()
    # request.FILES may contain multiple files under the 'images' key (multipart/form-data)
    files = request.FILES.getlist('images') if hasattr(request, 'FILES') else []
    # Ensure images key is a list; if provided in JSON, extend it with file objects
    images_json = []
    try:
        raw_images = data.get('images') or []
        # request.data may return a single string, a list of strings, or already parsed dicts
        if isinstance(raw_images, (list, tuple)):
            images_json = list(raw_images)
        else:
            images_json = [raw_images]
    except Exception:
        images_json = []
    # Try to parse any JSON-encoded strings into dicts (common when sending JSON in multipart)
    parsed_images = []
    for it in images_json:
        if isinstance(it, str):
            try:
                cand = json.loads(it)
                parsed_images.append(cand)
            except Exception:
                # skip non-json strings
                continue
        elif isinstance(it, dict):
            parsed_images.append(it)
        else:
            # ignore other types here (files are handled separately)
            continue
    images_json = parsed_images
    # Append uploaded files to the images list so serializer.create handles them
    images_combined = images_json + files
    data.setlist('images', images_combined) if hasattr(data, 'setlist') else data.__setitem__('images', images_combined)

    serializer = ProductCreateSerializer(data=data)
    if serializer.is_valid():
        product = serializer.save(seller=request.user)
        
        # Only fetch Pexels image if user didn't provide their own image URL
        user_provided_image = 'pexelsImageUrl' in data and data.get('pexelsImageUrl')
        if not user_provided_image and pexels_service.is_configured() and not product.pexels_image_url:
            try:
                pexels_service.get_or_fetch_product_image(product)
            except Exception as e:
                # Log error but don't fail the product creation
                logger.error(f"Error fetching Pexels image for product {product.title}: {e}")
        
        return Response(ProductListSerializer(product).data, status=status.HTTP_201_CREATED)

    return Response({'error': {'code': 'VALIDATION_ERROR', 'message': 'Validation failed', 'details': serializer.errors}}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(request=ProductUpdateSerializer, responses={200: ProductListSerializer})
@api_view(['PATCH', 'PUT'])
@permission_classes([IsAuthenticated])
def update_product(request, uuid):
    """Farmer updates their product. Only owner or admin allowed."""
    product = get_object_or_404(Product, uuid=uuid)
    # Only the owning smart_seller or staff may update
    if not getattr(request.user, 'is_authenticated', False):
        return Response({'error': {'code': 'AUTH_REQUIRED', 'message': 'Authentication required'}}, status=status.HTTP_401_UNAUTHORIZED)
    if product.seller != request.user and not getattr(request.user, 'is_staff', False):
        return Response({'error': {'code': 'FORBIDDEN', 'message': 'Not allowed to update this product'}}, status=status.HTTP_403_FORBIDDEN)
    if request.user.user_type != 'smart_seller' and not getattr(request.user, 'is_staff', False):
        return Response({'error': {'code': 'FORBIDDEN', 'message': 'Only smart_seller accounts may update products'}}, status=status.HTTP_403_FORBIDDEN)

    # Combine uploaded files with any JSON images provided in the payload
    data = request.data.copy()
    files = request.FILES.getlist('images') if hasattr(request, 'FILES') else []
    images_json = []
    try:
        raw_images = data.get('images') or []
        if isinstance(raw_images, (list, tuple)):
            images_json = list(raw_images)
        else:
            images_json = [raw_images]
    except Exception:
        images_json = []
    parsed_images = []
    for it in images_json:
        if isinstance(it, str):
            try:
                cand = json.loads(it)
                parsed_images.append(cand)
            except Exception:
                continue
        elif isinstance(it, dict):
            parsed_images.append(it)
        else:
            continue
    images_json = parsed_images
    images_combined = images_json + files
    data.setlist('images', images_combined) if hasattr(data, 'setlist') else data.__setitem__('images', images_combined)

    serializer = ProductUpdateSerializer(product, data=data, partial=True)
    if serializer.is_valid():
        # Check if user provided an image URL
        user_provided_image = 'pexelsImageUrl' in data
        
        # Check if title or category was updated - if so, might need new image
        title_changed = 'title' in data and data.get('title') != product.title
        
        # Check if category changed by comparing category names
        category_changed = False
        if 'category' in data:
            old_category_name = product.category.name if product.category else None
            # Get the new category name from the validated data in the serializer
            new_category = serializer.validated_data.get('category')
            new_category_name = new_category.name if new_category else None
            category_changed = old_category_name != new_category_name
        
        # Save the product first
        product = serializer.save()
        
        # Only fetch new image from Pexels if:
        # 1. User did not provide their own image URL, AND
        # 2. Either title/category changed OR no image exists
        if not user_provided_image and pexels_service.is_configured():
            if (title_changed or category_changed) and not product.pexels_image_url:
                try:
                    pexels_service.get_or_fetch_product_image(product)
                except Exception as e:
                    # Log error but don't fail the product update
                    logger.error(f"Error fetching Pexels image for product {product.title}: {e}")
            elif not product.pexels_image_url:
                # If no image exists, try to fetch one regardless of changes
                try:
                    pexels_service.get_or_fetch_product_image(product)
                except Exception as e:
                    # Log error but don't fail the product update
                    logger.error(f"Error fetching Pexels image for product {product.title}: {e}")
        
        return Response(ProductListSerializer(product).data)

    return Response({'error': {'code': 'VALIDATION_ERROR', 'message': 'Validation failed', 'details': serializer.errors}}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(responses={200: dict})
@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_product(request, uuid):
    """Soft-delete a product (farmer or admin)"""
    product = get_object_or_404(Product, uuid=uuid)
    # Only owning smart_seller or staff may delete
    if not getattr(request.user, 'is_authenticated', False):
        return Response({'error': {'code': 'AUTH_REQUIRED', 'message': 'Authentication required'}}, status=status.HTTP_401_UNAUTHORIZED)
    if product.seller != request.user and not getattr(request.user, 'is_staff', False):
        return Response({'error': {'code': 'FORBIDDEN', 'message': 'Not allowed to delete this product'}}, status=status.HTTP_403_FORBIDDEN)
    if request.user.user_type != 'smart_seller' and not getattr(request.user, 'is_staff', False):
        return Response({'error': {'code': 'FORBIDDEN', 'message': 'Only smart_seller accounts may delete products'}}, status=status.HTTP_403_FORBIDDEN)

    # perform delete
    product.delete()
    return Response({'message': 'Product deleted successfully'}, status=status.HTTP_200_OK)


@extend_schema(responses={200: ProductListSerializer(many=True)})
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_products_by_buyer_type(request):
    """Return seller's products grouped by buyer category visibility"""
    # Only smart_seller users (or staff) may query their products by buyer-type
    if not getattr(request.user, 'is_authenticated', False):
        return Response({'error': {'code': 'AUTH_REQUIRED', 'message': 'Authentication required'}}, status=status.HTTP_401_UNAUTHORIZED)
    if request.user.user_type != 'smart_seller' and not getattr(request.user, 'is_staff', False):
        return Response({'error': {'code': 'FORBIDDEN', 'message': 'Only smart_seller accounts may access this resource'}}, status=status.HTTP_403_FORBIDDEN)

    products = Product.objects.filter(seller=request.user, is_published=True).prefetch_related('images')

    # Serialize all seller products once, then group them in-memory so that a product
    # that lists multiple buyer categories appears in every corresponding bucket.
    serialized = ProductListSerializer(products, many=True).data

    # all_buyers: those with any buyer_category_visibility set (non-empty)
    all_buyers = [p for p in serialized if p.get('buyerCategoryVisibility')]

    # Initialize buckets
    by_type = {cat: [] for cat in ALLOWED_BUYER_CATEGORIES}

    # Fill buckets: each product may belong to multiple categories
    for p in serialized:
        vis = p.get('buyerCategoryVisibility') or []
        # ensure we iterate a list-like structure
        try:
            iter(vis)
        except TypeError:
            continue
        for cat in vis:
            if cat in by_type:
                by_type[cat].append(p)

    return Response({
        'all_buyers': all_buyers,
        'by_type': by_type,
    })


@extend_schema(operation_id='product-detail', responses={200: ProductListSerializer})
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_product_detail(request, uuid):
    """Product detail for smart_buyers. Enforce buyer visibility if necessary."""
    # Only smart_buyer users (or staff) may access product details
    if not getattr(request.user, 'is_authenticated', False):
        return Response({'error': {'code': 'AUTH_REQUIRED', 'message': 'Authentication required'}}, status=status.HTTP_401_UNAUTHORIZED)
    if request.user.user_type != 'smart_buyer' and not getattr(request.user, 'is_staff', False):
        return Response({'error': {'code': 'FORBIDDEN', 'message': 'Only smart_buyer accounts may access product details'}}, status=status.HTTP_403_FORBIDDEN)
    """Public product detail. Enforce buyer visibility if necessary."""
    product = get_object_or_404(Product.objects.prefetch_related('images'), uuid=uuid, is_published=True)

    # buyerCategory can be provided by authenticated token or query param
    buyer_category = None
    if request.user.is_authenticated:
        buyer_category = getattr(request.user, 'buyer_category', None)
    if not buyer_category:
        buyer_category = request.GET.get('buyerCategory')

    if product.buyer_category_visibility:
        vis = product.buyer_category_visibility
        # Validate provided buyer_category value if present
        if buyer_category and buyer_category not in ALLOWED_BUYER_CATEGORIES:
            return Response({'error': {'code': 'VALIDATION_ERROR', 'message': f'invalid buyerCategory {buyer_category}'}}, status=status.HTTP_400_BAD_REQUEST)

        if buyer_category and buyer_category not in vis and not getattr(request.user, 'is_staff', False):
            return Response({'error': {'code': 'FORBIDDEN', 'message': 'Not visible to your buyer category'}}, status=status.HTTP_403_FORBIDDEN)
        if not buyer_category and vis:
            # if visibility restricted and no buyer category provided, deny
            return Response({'error': {'code': 'FORBIDDEN', 'message': 'Product visibility restricted'}}, status=status.HTTP_403_FORBIDDEN)

    # If requester is authenticated smart_buyer, try to get lat/lon for distance calculation (optional)
    lat = request.GET.get('latitude')
    lon = request.GET.get('longitude')
    # Fallback to authenticated smart_buyer stored coordinates if available
    if (not lat or not lon) and request.user.is_authenticated and getattr(request.user, 'user_type', None) == 'smart_buyer':
        user_lat = getattr(request.user, 'latitude', None)
        user_lon = getattr(request.user, 'longitude', None)
        if user_lat is not None and user_lon is not None:
            lat = str(user_lat)
            lon = str(user_lon)

    serializer = ProductListSerializer(product)
    data = serializer.data
    # attach distanceMeters if coords provided
    if lat and lon:
        try:
            latf = float(lat); lonf = float(lon)
            if product.latitude is not None and product.longitude is not None:
                data['distanceMeters'] = haversine_distance(latf, lonf, product.latitude, product.longitude)
        except Exception:
            # ignore invalid coords and return without distance
            pass

    return Response(data)


@extend_schema(operation_id='public-products-list', responses={200: ProductListSerializer(many=True)})
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_products(request):
    """Public listing with filters, search, pagination, distance calculation"""
    # Only smart_buyer users (or staff) may access product listings
    if not getattr(request.user, 'is_authenticated', False):
        return Response({'error': {'code': 'AUTH_REQUIRED', 'message': 'Authentication required'}}, status=status.HTTP_401_UNAUTHORIZED)
    if request.user.user_type != 'smart_buyer' and not getattr(request.user, 'is_staff', False):
        return Response({'error': {'code': 'FORBIDDEN', 'message': 'Only smart_buyer accounts may access product listings'}}, status=status.HTTP_403_FORBIDDEN)
    qs = Product.objects.filter(is_published=True)

    q = request.GET.get('q')
    crop = request.GET.get('crop')
    category = request.GET.get('category')
    minPrice = request.GET.get('minPrice')
    maxPrice = request.GET.get('maxPrice')
    priceType = request.GET.get('priceType')
    minQuantity = request.GET.get('minQuantity')
    # Prefer buyer category from authenticated smart_buyer token over query param
    buyerCategory = None
    if request.user.is_authenticated and getattr(request.user, 'user_type', None) == 'smart_buyer':
        buyerCategory = getattr(request.user, 'buyer_category', None)
    if not buyerCategory:
        buyerCategory = request.GET.get('buyerCategory')
    lat = request.GET.get('latitude')
    lon = request.GET.get('longitude')
    maxDistance = request.GET.get('maxDistanceMeters')
    sortBy = request.GET.get('sortBy')
    page = int(request.GET.get('page', 1))
    limit = int(request.GET.get('limit', 20))

    # Fallback to authenticated smart_buyer stored coordinates if available
    if (not lat or not lon) and request.user.is_authenticated and getattr(request.user, 'user_type', None) == 'smart_buyer':
        user_lat = getattr(request.user, 'latitude', None)
        user_lon = getattr(request.user, 'longitude', None)
        if user_lat is not None and user_lon is not None:
            lat = str(user_lat)
            lon = str(user_lon)

    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q) | Q(crop__icontains=q) | Q(variety__icontains=q))
    if crop:
        qs = qs.filter(crop__iexact=crop)
    if category:
        qs = qs.filter(category__iexact=category)
    if priceType:
        qs = qs.filter(price_type__iexact=priceType)
    if minPrice:
        try:
            qs = qs.filter(price_per_unit__gte=float(minPrice))
        except Exception:
            pass
    if maxPrice:
        try:
            qs = qs.filter(price_per_unit__lte=float(maxPrice))
        except Exception:
            pass
    if minQuantity:
        try:
            qs = qs.filter(quantity_available__gte=float(minQuantity))
        except Exception:
            pass

    # Visibility filtering
    if buyerCategory:
        # ensure buyerCategory value matches expected set
        if buyerCategory not in ALLOWED_BUYER_CATEGORIES:
            return Response({'error': {'code': 'VALIDATION_ERROR', 'message': f'invalid buyerCategory {buyerCategory}'}}, status=status.HTTP_400_BAD_REQUEST)
        try:
            if connection.vendor == 'postgresql':
                qs = qs.filter(buyer_category_visibility__contains=[buyerCategory])
            else:
                qs = qs.filter(buyer_category_visibility__icontains=f'"{buyerCategory}"')
        except DatabaseError:
            qs = qs.filter(buyer_category_visibility__icontains=f'"{buyerCategory}"')

    # Precompute distances if lat/lon provided
    items = list(qs.prefetch_related('images'))

    if lat and lon:
        try:
            latf = float(lat); lonf = float(lon)
            new_items = []
            for it in items:
                if it.latitude is None or it.longitude is None:
                    continue
                d = haversine_distance(latf, lonf, it.latitude, it.longitude)
                if maxDistance and d > int(maxDistance):
                    continue
                it._distance = d
                new_items.append(it)
            items = new_items
            if sortBy == 'distance':
                items.sort(key=lambda x: getattr(x, '_distance', 0))
        except Exception:
            pass

    # other sorts
    if sortBy == 'price':
        items.sort(key=lambda x: x.price_per_unit)
    elif sortBy == 'createdAt':
        items.sort(key=lambda x: x.created_at, reverse=True)

    total = len(items)
    start = (page-1)*limit
    end = start+limit
    paged = items[start:end]

    # serialize and attach distanceMeters
    serialized = ProductListSerializer(paged, many=True).data
    if lat and lon:
        for idx, obj in enumerate(paged):
            d = getattr(obj, '_distance', None)
            if d is not None:
                serialized[idx]['distanceMeters'] = d

    return Response({'items': serialized, 'totalCount': total, 'page': page, 'limit': limit})


@extend_schema(responses={200: dict})
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_mandi_prices(request):
    """Return latest mandi prices for a commodity and city via query parameters"""
    # Only smart_seller users (or staff) may fetch live mandi prices
    if not getattr(request.user, 'is_authenticated', False):
        return Response({'error': {'code': 'AUTH_REQUIRED', 'message': 'Authentication required'}}, status=status.HTTP_401_UNAUTHORIZED)
    if request.user.user_type != 'smart_seller' and not getattr(request.user, 'is_staff', False):
        return Response({'error': {'code': 'FORBIDDEN', 'message': 'Only smart_seller accounts may fetch live mandi prices'}}, status=status.HTTP_403_FORBIDDEN, headers={'Content-Type': 'application/json'})

    commodity = request.GET.get('commodity')
    city = request.GET.get('city')

    if not commodity:
        return Response({'error': {'code': 'VALIDATION_ERROR', 'message': 'commodity parameter is required'}}, status=status.HTTP_400_BAD_REQUEST, headers={'Content-Type': 'application/json'})

    if not city:
        return Response({'error': {'code': 'VALIDATION_ERROR', 'message': 'city parameter is required'}}, status=status.HTTP_400_BAD_REQUEST, headers={'Content-Type': 'application/json'})

    # Use provided commodity and city
    commodity = commodity.strip()
    city = city.strip()
    
    # Check cache first to improve response time (cache for 10 minutes)
    state_param = request.GET.get('state')
    cache_key = f"mandi_price_{commodity.lower()}_{city.lower()}_{state_param.lower() if state_param else 'none'}"
    cached_result = cache.get(cache_key)
    if cached_result:
        return Response(cached_result, headers={'Content-Type': 'application/json'})

    # Attempt to fetch live mandi prices from data.gov.in resource
    # Resource: Current Daily Price of Various Commodities from Various Markets (Mandi)
    resource_id = '9ef84268-d588-465a-a308-a864a43d0070'

    # Allow callers to override api key for debugging via query param 'api_key' or 'apikey'.
    api_key = (request.GET.get('api_key') or request.GET.get('apikey') or
               os.environ.get('MANDI_API_KEY') or getattr(settings, 'MANDI_API_KEY', None))

    params = {
        'format': 'json',
        'limit': 100,  # fetch a reasonable number of recent records
    }
    if api_key:
        params['api-key'] = api_key
    # add commodity filter
    params['filters[commodity]'] = commodity
    # Use city for both district and state filters
    # Prefer filtering by district (city). Do not set state to the same value
    # because that often results in no matches (state != district). If callers
    # want to filter by state, they can pass a separate 'state' query param.
    params['filters[district]'] = city
    state_param = request.GET.get('state')
    if state_param:
        params['filters[state]'] = state_param.strip()

    try:
        url = f'https://api.data.gov.in/resource/{resource_id}'
        # Reduce timeout to 5 seconds for faster response
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code != 200:
            # include downstream body message when possible
            reason = None
            try:
                reason = resp.json()
            except Exception:
                reason = resp.text
            raise RuntimeError(f'data.gov.in returned status {resp.status_code}: {reason}')
        j = resp.json()
        records = j.get('records') or []
    except Exception as e:
        return Response({'error': {'code': 'NOT_AVAILABLE', 'message': 'No mandi price available or upstream fetch failed', 'reason': str(e)}}, status=status.HTTP_502_BAD_GATEWAY, headers={'Content-Type': 'application/json'})

    if not records:
        return Response({'error': {'code': 'NOT_AVAILABLE', 'message': 'No mandi price records found for commodity and city'}}, status=status.HTTP_404_NOT_FOUND, headers={'Content-Type': 'application/json'})

    # Convert returned prices (per quintal) to a simplified per-kg market list
    def per_kg(x):
        try:
            if x is None:
                return None
            return round(float(x) / 100.0, 2)
        except Exception:
            return None

    simple_markets = []
    for r in records:
        modal = r.get('modal_price') or r.get('modalPrice')
        min_p = r.get('min_price') or r.get('minPrice')
        max_p = r.get('max_price') or r.get('maxPrice')

        # prefer modal, else use avg(min,max), else None
        price_per_q = None
        try:
            if modal:
                price_per_q = float(modal)
            elif min_p and max_p:
                price_per_q = (float(min_p) + float(max_p)) / 2.0
        except Exception:
            price_per_q = None

        price_per_kg = per_kg(price_per_q)

        simple_markets.append({
            'market': r.get('market'),
            'state': r.get('state'),
            'district': r.get('district'),
            'pricePerKg': price_per_kg,
        })

    # final response
    resp = {
        'commodity': commodity,
        'city': city,
        'markets': simple_markets,
        'count': len(simple_markets),
    }

    # Cache the result for 10 minutes (600 seconds) to improve performance
    cache.set(cache_key, resp, 600)

    return Response(resp, headers={'Content-Type': 'application/json'})


@extend_schema(responses={200: dict})
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_product_distance(request, uuid):
    """Return distance in meters from the requesting smart_buyer to the product's location.

    The requesting user must be an authenticated smart_buyer (or staff). Latitude/longitude
    must be supplied either in query params (latitude, longitude) or (for future) could be
    taken from the user's profile (not implemented here). The function returns 400 when
    lat/lon missing or product has no coordinates.
    """
    # Only smart_buyer users (or staff) may use this endpoint
    if not getattr(request.user, 'is_authenticated', False):
        return Response({'error': {'code': 'AUTH_REQUIRED', 'message': 'Authentication required'}}, status=status.HTTP_401_UNAUTHORIZED)
    if request.user.user_type != 'smart_buyer' and not getattr(request.user, 'is_staff', False):
        return Response({'error': {'code': 'FORBIDDEN', 'message': 'Only smart_buyer accounts may fetch product distance'}}, status=status.HTTP_403_FORBIDDEN)

    lat = request.GET.get('latitude')
    lon = request.GET.get('longitude')
    # Fallback to authenticated smart_buyer stored coordinates if available
    if (not lat or not lon) and request.user.is_authenticated and getattr(request.user, 'user_type', None) == 'smart_buyer':
        user_lat = getattr(request.user, 'latitude', None)
        user_lon = getattr(request.user, 'longitude', None)
        if user_lat is not None and user_lon is not None:
            lat = str(user_lat)
            lon = str(user_lon)

    if not lat or not lon:
        return Response({'error': {'code': 'VALIDATION_ERROR', 'message': 'latitude and longitude are required for smart_buyer to calculate distance'}}, status=status.HTTP_400_BAD_REQUEST)

    try:
        latf = float(lat); lonf = float(lon)
    except Exception:
        return Response({'error': {'code': 'VALIDATION_ERROR', 'message': 'invalid latitude/longitude'}}, status=status.HTTP_400_BAD_REQUEST)

    product = get_object_or_404(Product, uuid=uuid)
    if product.latitude is None or product.longitude is None:
        return Response({'error': {'code': 'NOT_AVAILABLE', 'message': 'Product has no location coordinates'}}, status=status.HTTP_404_NOT_FOUND)

    d = haversine_distance(latf, lonf, product.latitude, product.longitude)
    return Response({'productId': str(product.uuid), 'distanceMeters': d})


# Category Management Views

from users.api.admin_views import AdminPermissionMixin
from .serializers import CategoryCreateSerializer, CategoryListSerializer
import base64


@extend_schema(responses={200: dict})
@api_view(['GET'])
@permission_classes([AllowAny])
def list_categories(request):
    """List all active categories (public endpoint)"""
    categories = Category.objects.filter(is_active=True).order_by('name')
    serializer = CategoryListSerializer(categories, many=True)
    return Response({
        'success': True,
        'categories': serializer.data
    })


class CategoryAdminPermissionMixin:
    """Mixin to check X-Admin-Token header for category admin operations"""

    def check_admin(self, request):
        header_token = request.headers.get('X-Admin-Token') or request.META.get('HTTP_X_ADMIN_TOKEN')
        if not header_token:
            # also support Authorization: Basic <base64>
            auth = request.headers.get('Authorization') or request.META.get('HTTP_AUTHORIZATION', '')
            if auth.startswith('Basic '):
                header_token = auth.split(' ', 1)[1].strip()

        if not header_token:
            return False

        expected_user = getattr(settings, 'ADMIN_USERNAME', None)
        expected_pass = getattr(settings, 'ADMIN_PASSWORD', None)
        if not expected_user or not expected_pass:
            return False
        
        expected = base64.b64encode(f"{expected_user}:{expected_pass}".encode('utf-8')).decode('utf-8')
        return header_token == expected


@extend_schema(responses={201: dict})
@api_view(['POST'])
@permission_classes([AllowAny])
def add_category(request):
    """Add a new category (admin only)"""
    # Check admin authentication
    mixin = CategoryAdminPermissionMixin()
    if not mixin.check_admin(request):
        return Response({
            'success': False,
            'message': 'Admin authentication required'
        }, status=status.HTTP_401_UNAUTHORIZED)

    serializer = CategoryCreateSerializer(data=request.data)
    if serializer.is_valid():
        category = serializer.save()
        return Response({
            'success': True,
            'message': 'Category created successfully',
            'category': {
                'id': category.id,
                'name': category.name,
                'description': category.description,
                'is_active': category.is_active,
                'created_at': category.created_at
            }
        }, status=status.HTTP_201_CREATED)
    else:
        return Response({
            'success': False,
            'message': 'Validation error',
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(responses={200: dict})
@api_view(['DELETE'])
@permission_classes([AllowAny])
def delete_category(request, category_id):
    """Delete a category (admin only)"""
    # Check admin authentication
    mixin = CategoryAdminPermissionMixin()
    if not mixin.check_admin(request):
        return Response({
            'success': False,
            'message': 'Admin authentication required'
        }, status=status.HTTP_401_UNAUTHORIZED)

    try:
        category = Category.objects.get(id=category_id)
    except Category.DoesNotExist:
        return Response({
            'success': False,
            'message': 'Category not found'
        }, status=status.HTTP_404_NOT_FOUND)

    # Check if any products are using this category
    products_count = category.products.count()
    if products_count > 0:
        return Response({
            'success': False,
            'message': f'Cannot delete category. {products_count} products are still using this category.'
        }, status=status.HTTP_400_BAD_REQUEST)

    category_name = category.name
    category.delete()
    
    return Response({
        'success': True,
        'message': f'Category "{category_name}" deleted successfully'
    })
