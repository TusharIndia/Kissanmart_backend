from rest_framework import status, generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.db.models import Q, Sum, Count, Avg
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal

from ..models import (
    Order, OrderItem, OrderAnalytics, OrderStatusHistory
)
from .serializers import (
    OrderListSerializer, OrderDetailSerializer, OrderUpdateSerializer,
    OrderAnalyticsSerializer, OrderStatisticsSerializer
)
from .views import OrderPagination


def check_admin_permission(request):
    """Check if user has admin permissions"""
    # Check if user is staff
    if hasattr(request.user, 'is_staff') and request.user.is_staff:
        return True
    
    # Check for admin token in headers (as per your existing admin system)
    admin_token = request.headers.get('X-Admin-Token')
    if admin_token:
        # You can implement your admin token validation logic here
        # For now, we'll accept any admin token
        return True
    
    return False


class AdminOrderListView(generics.ListAPIView):
    """Admin view to get all orders with filtering"""
    
    serializer_class = OrderListSerializer
    pagination_class = OrderPagination
    permission_classes = [permissions.AllowAny]
    
    def get_queryset(self):
        """Get all orders with admin filters"""
        queryset = Order.objects.all()
        
        # Apply filters
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        seller_id = self.request.query_params.get('seller_id')
        if seller_id:
            queryset = queryset.filter(items__seller_id=seller_id).distinct()
        
        customer_id = self.request.query_params.get('customer_id')
        if customer_id:
            queryset = queryset.filter(user_id=customer_id)
        
        from_date = self.request.query_params.get('from_date')
        if from_date:
            try:
                from_date = datetime.strptime(from_date, '%Y-%m-%d').date()
                queryset = queryset.filter(order_date__date__gte=from_date)
            except ValueError:
                pass
        
        to_date = self.request.query_params.get('to_date')
        if to_date:
            try:
                to_date = datetime.strptime(to_date, '%Y-%m-%d').date()
                queryset = queryset.filter(order_date__date__lte=to_date)
            except ValueError:
                pass
        
        # Search functionality
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(id__icontains=search) |
                Q(customer_name__icontains=search) |
                Q(customer_phone__icontains=search) |
                Q(customer_email__icontains=search)
            )
        
        return queryset.order_by('-created_at')
    
    def list(self, request, *args, **kwargs):
        """Custom list response with admin permission check"""
        if not check_admin_permission(request):
            return Response({
                'success': False,
                'message': 'Admin access required'
            }, status=status.HTTP_403_FORBIDDEN)
        
        response = super().list(request, *args, **kwargs)
        
        # Enhance response data with additional admin info
        for order_data in response.data['results']:
            try:
                order = Order.objects.get(id=order_data['id'])
                # Add seller information
                sellers = order.items.values_list('seller__full_name', flat=True).distinct()
                order_data['seller_names'] = list(sellers)
                order_data['customer_name'] = order.customer_name
                order_data['customer_phone'] = order.customer_phone
            except Order.DoesNotExist:
                pass
        
        return Response({
            'success': True,
            'data': response.data
        })


class AdminOrderDetailView(APIView):
    """Admin view to get detailed order information"""
    
    permission_classes = [permissions.AllowAny]
    
    def get(self, request, order_uuid):
        """Get order details with admin access"""
        if not check_admin_permission(request):
            return Response({
                'success': False,
                'message': 'Admin access required'
            }, status=status.HTTP_403_FORBIDDEN)
        
        try:
            order = Order.objects.select_related(
                'delivery_address', 'tracking', 'user'
            ).prefetch_related(
                'items__product', 'items__seller', 'status_history'
            ).get(uuid=order_uuid)
            
            serializer = OrderDetailSerializer(order)
            order_data = serializer.data
            
            # Add admin-specific information
            order_data['user_info'] = {
                'id': order.user.id,
                'full_name': order.user.full_name,
                'mobile_number': order.user.mobile_number,
                'email': order.user.email,
                'user_type': order.user.user_type
            }
            
            return Response({
                'success': True,
                'order': order_data
            })
            
        except Order.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Order not found'
            }, status=status.HTTP_404_NOT_FOUND)


class AdminOrderAnalyticsView(APIView):
    """Admin view for comprehensive order analytics"""
    
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        """Get comprehensive order analytics"""
        if not check_admin_permission(request):
            return Response({
                'success': False,
                'message': 'Admin access required'
            }, status=status.HTTP_403_FORBIDDEN)
        
        now = timezone.now()
        today = now.date()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        
        # Overall statistics
        all_orders = Order.objects.all()
        
        total_orders = all_orders.count()
        orders_today = all_orders.filter(order_date__date=today).count()
        orders_this_week = all_orders.filter(order_date__date__gte=week_start).count()
        orders_this_month = all_orders.filter(order_date__date__gte=month_start).count()
        
        # Revenue calculations
        completed_orders = all_orders.filter(payment_status='completed')
        
        revenue_today = completed_orders.filter(
            order_date__date=today
        ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
        
        revenue_this_week = completed_orders.filter(
            order_date__date__gte=week_start
        ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
        
        revenue_this_month = completed_orders.filter(
            order_date__date__gte=month_start
        ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
        
        # Average order value
        avg_order_value = completed_orders.aggregate(
            avg=Avg('total_amount')
        )['avg'] or Decimal('0')
        
        # Status breakdown
        status_breakdown = {}
        for choice in Order._meta.get_field('status').choices:
            status_key = choice[0]
            status_breakdown[status_key] = all_orders.filter(status=status_key).count()
        
        # Top products
        top_products = []
        product_stats = OrderItem.objects.filter(
            order__payment_status='completed'
        ).values(
            'product_name'
        ).annotate(
            orders_count=Count('order', distinct=True),
            revenue=Sum('total_price'),
            quantity_sold=Sum('quantity')
        ).order_by('-revenue')[:10]
        
        for product in product_stats:
            top_products.append({
                'product_name': product['product_name'],
                'orders_count': product['orders_count'],
                'revenue': float(product['revenue'] or 0),
                'quantity_sold': float(product['quantity_sold'] or 0)
            })
        
        # Top sellers
        top_sellers = []
        seller_stats = OrderItem.objects.filter(
            order__payment_status='completed'
        ).values(
            'seller__full_name', 'seller_id'
        ).annotate(
            orders_count=Count('order', distinct=True),
            revenue=Sum('total_price'),
            items_sold=Count('id')
        ).order_by('-revenue')[:10]
        
        for seller in seller_stats:
            top_sellers.append({
                'seller_id': seller['seller_id'],
                'seller_name': seller['seller__full_name'],
                'orders_count': seller['orders_count'],
                'revenue': float(seller['revenue'] or 0),
                'items_sold': seller['items_sold']
            })
        
        # Top cities
        top_cities = []
        city_stats = Order.objects.filter(
            payment_status='completed'
        ).values(
            'delivery_address__city'
        ).annotate(
            orders_count=Count('id'),
            revenue=Sum('total_amount')
        ).order_by('-orders_count')[:10]
        
        for city in city_stats:
            top_cities.append({
                'city': city['delivery_address__city'],
                'orders_count': city['orders_count'],
                'revenue': float(city['revenue'] or 0)
            })
        
        # Monthly trends (last 12 months)
        monthly_trends = []
        for i in range(12):
            month_start = (today.replace(day=1) - timedelta(days=i*30)).replace(day=1)
            month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            
            month_orders = all_orders.filter(
                order_date__date__gte=month_start,
                order_date__date__lte=month_end,
                payment_status='completed'
            )
            
            monthly_trends.insert(0, {
                'month': month_start.strftime('%Y-%m'),
                'orders_count': month_orders.count(),
                'revenue': float(month_orders.aggregate(total=Sum('total_amount'))['total'] or 0)
            })
        
        analytics_data = {
            'total_orders': total_orders,
            'orders_today': orders_today,
            'orders_this_week': orders_this_week,
            'orders_this_month': orders_this_month,
            'revenue_today': float(revenue_today),
            'revenue_this_week': float(revenue_this_week),
            'revenue_this_month': float(revenue_this_month),
            'average_order_value': float(avg_order_value),
            'status_breakdown': status_breakdown,
            'top_products': top_products,
            'top_sellers': top_sellers,
            'top_cities': top_cities,
            'monthly_trends': monthly_trends
        }
        
        return Response({
            'success': True,
            'analytics': analytics_data
        })


class AdminDashboardStatsView(APIView):
    """Quick dashboard stats for admin panel"""
    
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        """Get quick dashboard statistics"""
        if not check_admin_permission(request):
            return Response({
                'success': False,
                'message': 'Admin access required'
            }, status=status.HTTP_403_FORBIDDEN)
        
        today = timezone.now().date()
        
        # Quick stats
        total_orders = Order.objects.count()
        pending_orders = Order.objects.filter(status='pending').count()
        processing_orders = Order.objects.filter(status__in=['confirmed', 'processing', 'packed']).count()
        in_transit_orders = Order.objects.filter(status__in=['shipped', 'in_transit']).count()
        delivered_today = Order.objects.filter(status='delivered', actual_delivery__date=today).count()
        
        # Revenue stats
        today_revenue = Order.objects.filter(
            order_date__date=today,
            payment_status='completed'
        ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
        
        # New customers today
        from users.models import CustomUser
        new_customers_today = CustomUser.objects.filter(
            created_at__date=today
        ).count()
        
        # Orders requiring attention (pending > 1 hour)
        one_hour_ago = timezone.now() - timedelta(hours=1)
        orders_needing_attention = Order.objects.filter(
            status='pending',
            created_at__lt=one_hour_ago
        ).count()
        
        dashboard_stats = {
            'total_orders': total_orders,
            'pending_orders': pending_orders,
            'processing_orders': processing_orders,
            'in_transit_orders': in_transit_orders,
            'delivered_today': delivered_today,
            'today_revenue': float(today_revenue),
            'new_customers_today': new_customers_today,
            'orders_needing_attention': orders_needing_attention
        }
        
        return Response({
            'success': True,
            'dashboard_stats': dashboard_stats
        })
