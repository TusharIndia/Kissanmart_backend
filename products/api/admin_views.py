from rest_framework.views import APIView
from rest_framework import status, generics
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.db.models import Q, Sum, Avg, Count
from django.utils import timezone
from datetime import timedelta
import base64
try:
    from drf_spectacular.utils import extend_schema, OpenApiParameter
    from drf_spectacular.types import OpenApiTypes
    HAS_SPECTACULAR = True
except ImportError:
    # Fallback for when drf_spectacular is not available
    def extend_schema(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    
    class OpenApiParameter:
        def __init__(self, *args, **kwargs):
            pass
    
    class OpenApiTypes:
        STR = str
        INT = int
        NUMBER = float
        DATE = str
    
    HAS_SPECTACULAR = False

from ..models import Product, ProductImage
from users.models import CustomUser, AdminActionLog
from .admin_serializers import (
    AdminProductListSerializer, 
    AdminProductDetailSerializer, 
    AdminProductStatsSerializer,
    AdminProductUpdateSerializer
)


def make_admin_token(username: str, password: str) -> str:
    """Create a simple base64 token from username:password"""
    raw = f"{username}:{password}".encode('utf-8')
    return base64.b64encode(raw).decode('utf-8')


class AdminPermissionMixin:
    """Mixin to check X-Admin-Token header or basic auth style token"""

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
        
        expected = make_admin_token(expected_user, expected_pass)
        return header_token == expected

    def get_admin_username(self, request):
        """Extract admin username from auth header for logging purposes"""
        auth = request.headers.get('Authorization') or request.META.get('HTTP_AUTHORIZATION', '')
        if auth.startswith('Basic '):
            token = auth.split(' ', 1)[1]
            try:
                raw = base64.b64decode(token).decode('utf-8')
                return raw.split(':', 1)[0]
            except Exception:
                pass
        return None


@extend_schema(
    parameters=[
        OpenApiParameter(name='search', type=OpenApiTypes.STR, description='Search in title, category, crop, variety, seller name'),
        OpenApiParameter(name='status', type=OpenApiTypes.STR, description='Filter by status: active, inactive, sold_out'),
        OpenApiParameter(name='category', type=OpenApiTypes.STR, description='Filter by product category'),
        OpenApiParameter(name='city', type=OpenApiTypes.STR, description='Filter by city'),
        OpenApiParameter(name='seller_id', type=OpenApiTypes.INT, description='Filter by seller ID'),
        OpenApiParameter(name='min_price', type=OpenApiTypes.NUMBER, description='Minimum price filter'),
        OpenApiParameter(name='max_price', type=OpenApiTypes.NUMBER, description='Maximum price filter'),
        OpenApiParameter(name='date_from', type=OpenApiTypes.DATE, description='Filter products uploaded from this date (YYYY-MM-DD)'),
        OpenApiParameter(name='date_to', type=OpenApiTypes.DATE, description='Filter products uploaded to this date (YYYY-MM-DD)'),
        OpenApiParameter(name='ordering', type=OpenApiTypes.STR, description='Order by: created_at, -created_at, price_per_unit, -price_per_unit, quantity_available, -quantity_available'),
        OpenApiParameter(name='page', type=OpenApiTypes.INT, description='Page number'),
        OpenApiParameter(name='page_size', type=OpenApiTypes.INT, description='Number of items per page (max 100)')
    ],
    responses={200: dict}
)
class AdminProductListView(AdminPermissionMixin, APIView):
    """
    Admin endpoint to list all products with comprehensive filtering and search capabilities.
    
    Features:
    - Search across product title, category, crop, variety, and seller name
    - Filter by status, category, city, seller, price range, date range
    - Sorting by various fields
    - Pagination
    """
    permission_classes = [AllowAny]

    def dispatch(self, request, *args, **kwargs):
        if not self.check_admin(request):
            return Response(
                {'success': False, 'message': 'Admin authentication required'}, 
                status=status.HTTP_401_UNAUTHORIZED
            )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        queryset = Product.objects.select_related('seller').prefetch_related('images')
        
        # Search functionality
        search = request.query_params.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) |
                Q(category__icontains=search) |
                Q(crop__icontains=search) |
                Q(variety__icontains=search) |
                Q(seller__full_name__icontains=search) |
                Q(seller__mobile_number__icontains=search) |
                Q(description__icontains=search)
            )

        # Status filter
        status_filter = request.query_params.get('status', '').strip()
        if status_filter == 'active':
            queryset = queryset.filter(is_published=True, quantity_available__gt=0)
        elif status_filter == 'inactive':
            queryset = queryset.filter(is_published=False)
        elif status_filter == 'sold_out':
            queryset = queryset.filter(is_published=True, quantity_available=0)

        # Category filter
        category = request.query_params.get('category', '').strip()
        if category:
            queryset = queryset.filter(category__icontains=category)

        # City filter
        city = request.query_params.get('city', '').strip()
        if city:
            queryset = queryset.filter(city__icontains=city)

        # Seller filter
        seller_id = request.query_params.get('seller_id', '').strip()
        if seller_id:
            try:
                queryset = queryset.filter(seller_id=int(seller_id))
            except ValueError:
                pass

        # Price range filter
        min_price = request.query_params.get('min_price', '').strip()
        max_price = request.query_params.get('max_price', '').strip()
        if min_price:
            try:
                queryset = queryset.filter(price_per_unit__gte=float(min_price))
            except ValueError:
                pass
        if max_price:
            try:
                queryset = queryset.filter(price_per_unit__lte=float(max_price))
            except ValueError:
                pass

        # Date range filter
        date_from = request.query_params.get('date_from', '').strip()
        date_to = request.query_params.get('date_to', '').strip()
        if date_from:
            try:
                from datetime import datetime
                date_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
                queryset = queryset.filter(created_at__date__gte=date_obj)
            except ValueError:
                pass
        if date_to:
            try:
                from datetime import datetime
                date_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
                queryset = queryset.filter(created_at__date__lte=date_obj)
            except ValueError:
                pass

        # Ordering
        ordering = request.query_params.get('ordering', '-created_at')
        valid_orderings = [
            'created_at', '-created_at', 'updated_at', '-updated_at',
            'price_per_unit', '-price_per_unit', 'quantity_available', '-quantity_available',
            'title', '-title', 'category', '-category'
        ]
        if ordering in valid_orderings:
            queryset = queryset.order_by(ordering)
        else:
            queryset = queryset.order_by('-created_at')

        # Pagination
        page = int(request.query_params.get('page', 1))
        page_size = min(int(request.query_params.get('page_size', 20)), 100)  # Max 100 items per page
        
        total_count = queryset.count()
        start = (page - 1) * page_size
        end = start + page_size
        
        products = queryset[start:end]
        serializer = AdminProductListSerializer(products, many=True)
        
        return Response({
            'success': True,
            'data': {
                'products': serializer.data,
                'pagination': {
                    'currentPage': page,
                    'pageSize': page_size,
                    'totalCount': total_count,
                    'totalPages': (total_count + page_size - 1) // page_size,
                    'hasNext': end < total_count,
                    'hasPrev': page > 1
                },
                'filters': {
                    'search': search,
                    'status': status_filter,
                    'category': category,
                    'city': city,
                    'seller_id': seller_id,
                    'min_price': min_price,
                    'max_price': max_price,
                    'date_from': date_from,
                    'date_to': date_to,
                    'ordering': ordering
                }
            }
        })


@extend_schema(responses={200: dict})
class AdminProductDetailView(AdminPermissionMixin, APIView):
    """
    Admin endpoint to get detailed information about a specific product.
    Includes seller details, all images, pricing info, location, etc.
    """
    permission_classes = [AllowAny]

    def dispatch(self, request, *args, **kwargs):
        if not self.check_admin(request):
            return Response(
                {'success': False, 'message': 'Admin authentication required'}, 
                status=status.HTTP_401_UNAUTHORIZED
            )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, product_uuid):
        try:
            product = Product.objects.select_related('seller').prefetch_related('images').get(uuid=product_uuid)
            serializer = AdminProductDetailSerializer(product)
            
            # Log admin action
            admin_username = self.get_admin_username(request)
            AdminActionLog.objects.create(
                admin_username=admin_username,
                user=product.seller,
                action='view',
                details=f'Viewed product details: {product.title} (ID: {product.uuid})'
            )
            
            return Response({
                'success': True,
                'product': serializer.data
            })
        except Product.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Product not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )


@extend_schema(responses={200: dict})
class AdminProductStatsView(AdminPermissionMixin, APIView):
    """
    Admin endpoint to get comprehensive product statistics and analytics.
    """
    permission_classes = [AllowAny]

    def dispatch(self, request, *args, **kwargs):
        if not self.check_admin(request):
            return Response(
                {'success': False, 'message': 'Admin authentication required'}, 
                status=status.HTTP_401_UNAUTHORIZED
            )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        # Basic counts
        total_products = Product.objects.count()
        active_products = Product.objects.filter(is_published=True, quantity_available__gt=0).count()
        inactive_products = Product.objects.filter(is_published=False).count()
        sold_out_products = Product.objects.filter(is_published=True, quantity_available=0).count()
        
        # Value calculations
        total_value = Product.objects.filter(is_published=True).aggregate(
            total=Sum('price_per_unit')
        )['total'] or 0
        
        average_price = Product.objects.filter(is_published=True).aggregate(
            avg=Avg('price_per_unit')
        )['avg'] or 0
        
        # Top categories
        top_categories = list(Product.objects.values('category').annotate(
            count=Count('id')
        ).order_by('-count')[:10])
        
        # Top cities
        top_cities = list(Product.objects.exclude(city__isnull=True).exclude(city='').values('city').annotate(
            count=Count('id')
        ).order_by('-count')[:10])
        
        # Recent uploads (last 7 days)
        week_ago = timezone.now() - timedelta(days=7)
        recent_uploads = Product.objects.filter(created_at__gte=week_ago).count()
        
        stats_data = {
            'totalProducts': total_products,
            'activeProducts': active_products,
            'inactiveProducts': inactive_products,
            'soldOutProducts': sold_out_products,
            'totalValue': total_value,
            'averagePrice': average_price,
            'topCategories': top_categories,
            'topCities': top_cities,
            'recentUploads': recent_uploads
        }
        
        serializer = AdminProductStatsSerializer(stats_data)
        
        return Response({
            'success': True,
            'stats': serializer.data
        })


@extend_schema(responses={200: dict})
class AdminProductUpdateView(AdminPermissionMixin, APIView):
    """
    Admin endpoint to update product status (publish/unpublish).
    """
    permission_classes = [AllowAny]

    def dispatch(self, request, *args, **kwargs):
        if not self.check_admin(request):
            return Response(
                {'success': False, 'message': 'Admin authentication required'}, 
                status=status.HTTP_401_UNAUTHORIZED
            )
        return super().dispatch(request, *args, **kwargs)

    def patch(self, request, product_uuid):
        try:
            product = Product.objects.get(uuid=product_uuid)
            serializer = AdminProductUpdateSerializer(product, data=request.data, partial=True)
            
            if serializer.is_valid():
                old_status = product.is_published
                serializer.save()
                
                # Log admin action
                admin_username = self.get_admin_username(request)
                action_details = f'Updated product status from {"published" if old_status else "unpublished"} to {"published" if product.is_published else "unpublished"}'
                
                AdminActionLog.objects.create(
                    admin_username=admin_username,
                    user=product.seller,
                    action='other',
                    details=f'Product update: {product.title} - {action_details}'
                )
                
                return Response({
                    'success': True,
                    'message': 'Product updated successfully',
                    'product': AdminProductDetailSerializer(product).data
                })
            
            return Response({
                'success': False,
                'message': 'Invalid data',
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
            
        except Product.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Product not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )


@extend_schema(responses={200: dict})
class AdminProductDeleteView(AdminPermissionMixin, APIView):
    """
    Admin endpoint to delete a product (soft delete by unpublishing).
    """
    permission_classes = [AllowAny]

    def dispatch(self, request, *args, **kwargs):
        if not self.check_admin(request):
            return Response(
                {'success': False, 'message': 'Admin authentication required'}, 
                status=status.HTTP_401_UNAUTHORIZED
            )
        return super().dispatch(request, *args, **kwargs)

    def delete(self, request, product_uuid):
        try:
            product = Product.objects.get(uuid=product_uuid)
            product_title = product.title
            seller = product.seller

            # Default to permanent delete for admin API (hard delete).
            # For compatibility, allow forcing soft-delete with ?soft=true
            soft_param = request.query_params.get('soft')
            if soft_param is None:
                soft_param = request.data.get('soft') if isinstance(request.data, dict) else None

            soft_flag = str(soft_param).lower() in ('1', 'true', 'yes', 'on') if soft_param is not None else False

            if soft_flag:
                # Soft delete (unpublish)
                product.soft_delete()
                result_message = 'Product deleted successfully'  # preserve previous message
                details_msg = f'Soft deleted product: {product_title} (ID: {product_uuid})'
            else:
                # Permanent delete from DB (default behavior)
                product.delete()
                result_message = 'Product permanently deleted'
                details_msg = f'Hard deleted product: {product_title} (ID: {product_uuid})'

            # Log admin action
            admin_username = self.get_admin_username(request)
            AdminActionLog.objects.create(
                admin_username=admin_username,
                user=seller,
                action='delete',
                details=details_msg
            )

            return Response({
                'success': True,
                'message': result_message
            })
            
        except Product.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Product not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )


@extend_schema(
    parameters=[
        OpenApiParameter(name='seller_id', type=OpenApiTypes.INT, description='Seller ID to get products for'),
    ],
    responses={200: dict}
)
class AdminSellerProductsView(AdminPermissionMixin, APIView):
    """
    Admin endpoint to get all products from a specific seller.
    """
    permission_classes = [AllowAny]

    def dispatch(self, request, *args, **kwargs):
        if not self.check_admin(request):
            return Response(
                {'success': False, 'message': 'Admin authentication required'}, 
                status=status.HTTP_401_UNAUTHORIZED
            )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, seller_id):
        try:
            seller = CustomUser.objects.get(id=seller_id)
            products = Product.objects.filter(seller=seller).order_by('-created_at')
            
            # Apply basic filters if provided
            status_filter = request.query_params.get('status', '').strip()
            if status_filter == 'active':
                products = products.filter(is_published=True, quantity_available__gt=0)
            elif status_filter == 'inactive':
                products = products.filter(is_published=False)
            elif status_filter == 'sold_out':
                products = products.filter(is_published=True, quantity_available=0)
            
            serializer = AdminProductListSerializer(products, many=True)
            
            # Log admin action
            admin_username = self.get_admin_username(request)
            AdminActionLog.objects.create(
                admin_username=admin_username,
                user=seller,
                action='view',
                details=f'Viewed all products for seller: {seller.full_name} ({seller.get_identifier()})'
            )
            
            return Response({
                'success': True,
                'seller': {
                    'id': seller.id,
                    'fullName': seller.full_name,
                    'mobileNumber': seller.mobile_number,
                    'city': seller.city,
                    'totalProducts': products.count()
                },
                'products': serializer.data
            })
            
        except CustomUser.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Seller not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )


@extend_schema(
    parameters=[
        OpenApiParameter(name='category', type=OpenApiTypes.STR, description='Category name'),
    ],
    responses={200: dict}
)
class AdminCategoryProductsView(AdminPermissionMixin, APIView):
    """
    Admin endpoint to get all products in a specific category with analytics.
    """
    permission_classes = [AllowAny]

    def dispatch(self, request, *args, **kwargs):
        if not self.check_admin(request):
            return Response(
                {'success': False, 'message': 'Admin authentication required'}, 
                status=status.HTTP_401_UNAUTHORIZED
            )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, category):
        products = Product.objects.filter(category__iexact=category).select_related('seller').order_by('-created_at')
        
        if not products.exists():
            return Response(
                {'success': False, 'message': f'No products found in category: {category}'}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Category analytics
        total_products = products.count()
        active_products = products.filter(is_published=True, quantity_available__gt=0).count()
        total_sellers = products.values('seller').distinct().count()
        avg_price = products.aggregate(avg=Avg('price_per_unit'))['avg'] or 0
        
        serializer = AdminProductListSerializer(products, many=True)
        
        return Response({
            'success': True,
            'category': category,
            'analytics': {
                'totalProducts': total_products,
                'activeProducts': active_products,
                'totalSellers': total_sellers,
                'averagePrice': avg_price
            },
            'products': serializer.data
        })