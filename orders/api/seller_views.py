"""
Seller-specific views for managing their orders and products
"""

from rest_framework import status, generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import Q, Sum, Count, Avg, F
from django.utils import timezone
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from ..models import (
    Order, OrderItem, OrderStatusHistory
)
from .seller_serializers import (
    SellerOrderListSerializer, SellerOrderDetailSerializer,
    SellerOrderItemSerializer, SellerOrderUpdateSerializer,
    SellerOrderStatisticsSerializer
)
from products.models import Product


class SellerOrdersPagination(PageNumberPagination):
    """Custom pagination for seller orders"""
    page_size = 15
    page_size_query_param = 'page_size'
    max_page_size = 100


class SellerOrdersView(generics.ListAPIView):
    """Get orders for products sold by the current seller"""
    
    serializer_class = SellerOrderListSerializer
    pagination_class = SellerOrdersPagination
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Filter orders containing seller's products"""
        user = self.request.user
        
        # Check if user is a seller
        if user.user_type != 'smart_seller':
            return Order.objects.none()
        
        # Get orders that contain items sold by this seller
        queryset = Order.objects.filter(
            items__seller=user
        ).distinct().select_related(
            'user', 'delivery_address'
        ).prefetch_related(
            'items__product', 'status_history'
        )
        
        # Apply filters
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Filter by item status (for seller's items only)
        item_status_filter = self.request.query_params.get('item_status')
        if item_status_filter:
            queryset = queryset.filter(items__seller=user, items__item_status=item_status_filter)
        
        # Date filters
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
        
        # Product filter (seller's products only)
        product_id = self.request.query_params.get('product')
        if product_id:
            try:
                product = Product.objects.get(uuid=product_id, seller=user)
                queryset = queryset.filter(items__product=product)
            except Product.DoesNotExist:
                pass
        
        return queryset.order_by('-created_at')
    
    def list(self, request, *args, **kwargs):
        """Custom list response format with seller-specific data"""
        if request.user.user_type != 'smart_seller':
            return Response({
                'success': False,
                'message': 'Only sellers can access this endpoint'
            }, status=status.HTTP_403_FORBIDDEN)
        
        response = super().list(request, *args, **kwargs)
        
        # Add summary statistics
        total_orders = self.get_queryset().count()
        pending_orders = self.get_queryset().filter(status='pending').count()
        processing_orders = self.get_queryset().filter(status__in=['confirmed', 'processing', 'packed']).count()
        
        return Response({
            'success': True,
            'summary': {
                'total_orders': total_orders,
                'pending_orders': pending_orders,
                'processing_orders': processing_orders
            },
            'data': response.data
        })


class SellerOrderDetailView(APIView):
    """Get detailed information about a specific order for seller"""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, order_uuid):
        """Get order details with seller's items only"""
        if request.user.user_type != 'smart_seller':
            return Response({
                'success': False,
                'message': 'Only sellers can access this endpoint'
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Get order and ensure the seller has items in it. Use filter().first()
        orders_qs = Order.objects.select_related(
            'user', 'delivery_address', 'tracking'
        ).prefetch_related(
            'items__product', 'status_history'
        ).filter(
            uuid=order_uuid,
            items__seller=request.user
        )

        order = orders_qs.first()

        # If no order found, return 404
        if not order:
            return Response({
                'success': False,
                'message': 'Order not found or you do not have items in this order'
            }, status=status.HTTP_404_NOT_FOUND)

        # If there are multiple matching orders (data inconsistency), log a warning
        if orders_qs.count() > 1:
            logger = logging.getLogger(__name__)
            logger.warning(
                "Multiple orders found with uuid=%s for seller id=%s. Returning the first match.",
                order_uuid, request.user.id
            )

        serializer = SellerOrderDetailSerializer(order, context={'seller': request.user})

        return Response({
            'success': True,
            'order': serializer.data
        })


class SellerOrderItemUpdateView(APIView):
    """Update individual order items for seller"""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def patch(self, request, order_uuid, item_id):
        """Update order item status and details"""
        if request.user.user_type != 'smart_seller':
            return Response({
                'success': False,
                'message': 'Only sellers can access this endpoint'
            }, status=status.HTTP_403_FORBIDDEN)
        
        try:
            # Get the specific order item for this seller
            order_item = OrderItem.objects.select_related('order', 'product').get(
                id=item_id,
                order__uuid=order_uuid,
                seller=request.user
            )
            
            serializer = SellerOrderItemSerializer(
                order_item,
                data=request.data,
                partial=True,
                context={'seller': request.user}
            )
            
            if serializer.is_valid():
                with transaction.atomic():
                    updated_item = serializer.save()
                    
                    # Update overall order status if needed
                    order = updated_item.order
                    self._update_order_status_if_needed(order)
                    
                    # Create status history for the order
                    if 'item_status' in request.data:
                        OrderStatusHistory.objects.create(
                            order=order,
                            status=updated_item.item_status,
                            title=f'Item Status Updated',
                            message=f'Item "{updated_item.product_name}" status updated to {updated_item.get_item_status_display()} by seller',
                            location=f'Seller: {request.user.full_name}',
                            changed_by=request.user,
                            change_source='seller'
                        )
                    
                    return Response({
                        'success': True,
                        'message': 'Order item updated successfully',
                        'item': SellerOrderItemSerializer(updated_item).data
                    })
            
            return Response({
                'success': False,
                'message': 'Invalid data',
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
            
        except OrderItem.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Order item not found or you are not the seller'
            }, status=status.HTTP_404_NOT_FOUND)
    
    def _update_order_status_if_needed(self, order):
        """Update overall order status based on item statuses"""
        seller_items = order.items.filter(seller=self.request.user)
        
        # If all seller's items are packed, we could update the order
        # This is a simplified logic - you might want more complex rules
        if seller_items.filter(item_status='packed').count() == seller_items.count():
            # Check if all items from all sellers are packed
            all_items = order.items.all()
            if all_items.filter(item_status='packed').count() == all_items.count():
                if order.status in ['confirmed', 'processing']:
                    order.status = 'packed'
                    order.save()


class SellerBulkOrderUpdateView(APIView):
    """Bulk update multiple order items for seller"""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def patch(self, request):
        """Bulk update order items"""
        if request.user.user_type != 'smart_seller':
            return Response({
                'success': False,
                'message': 'Only sellers can access this endpoint'
            }, status=status.HTTP_403_FORBIDDEN)
        
        item_ids = request.data.get('item_ids', [])
        update_data = request.data.get('update_data', {})
        
        if not item_ids or not update_data:
            return Response({
                'success': False,
                'message': 'item_ids and update_data are required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            with transaction.atomic():
                # Get items that belong to this seller
                items = OrderItem.objects.filter(
                    id__in=item_ids,
                    seller=request.user
                ).select_related('order')
                
                if not items.exists():
                    return Response({
                        'success': False,
                        'message': 'No valid items found for update'
                    }, status=status.HTTP_404_NOT_FOUND)
                
                updated_items = []
                orders_to_check = set()
                
                for item in items:
                    # Update allowed fields
                    if 'item_status' in update_data:
                        item.item_status = update_data['item_status']
                    if 'notes' in update_data:
                        item.notes = update_data['notes']
                    
                    item.save()
                    updated_items.append(item)
                    orders_to_check.add(item.order)
                
                # Update order statuses if needed
                for order in orders_to_check:
                    self._update_order_status_if_needed(order)
                
                # Create status history entries
                if 'item_status' in update_data:
                    for order in orders_to_check:
                        OrderStatusHistory.objects.create(
                            order=order,
                            status=update_data['item_status'],
                            title='Bulk Item Status Update',
                            message=f'Multiple items updated to {update_data["item_status"]} by seller',
                            location=f'Seller: {request.user.full_name}',
                            changed_by=request.user,
                            change_source='seller_bulk'
                        )
                
                return Response({
                    'success': True,
                    'message': f'Successfully updated {len(updated_items)} items',
                    'updated_count': len(updated_items)
                })
                
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Error updating items: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _update_order_status_if_needed(self, order):
        """Same logic as single item update"""
        seller_items = order.items.filter(seller=self.request.user)
        
        if seller_items.filter(item_status='packed').count() == seller_items.count():
            all_items = order.items.all()
            if all_items.filter(item_status='packed').count() == all_items.count():
                if order.status in ['confirmed', 'processing']:
                    order.status = 'packed'
                    order.save()


class SellerOrderStatisticsView(APIView):
    """Get order statistics for seller dashboard"""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """Get seller's order and sales statistics"""
        if request.user.user_type != 'smart_seller':
            return Response({
                'success': False,
                'message': 'Only sellers can access this endpoint'
            }, status=status.HTTP_403_FORBIDDEN)
        
        user = request.user
        now = timezone.now()
        today = now.date()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        
        # Base queryset for seller's items
        seller_items = OrderItem.objects.filter(seller=user)
        
        # Order statistics (unique orders containing seller's items)
        orders_with_seller_items = Order.objects.filter(items__seller=user).distinct()
        
        total_orders = orders_with_seller_items.count()
        orders_today = orders_with_seller_items.filter(order_date__date=today).count()
        orders_this_week = orders_with_seller_items.filter(order_date__date__gte=week_start).count()
        orders_this_month = orders_with_seller_items.filter(order_date__date__gte=month_start).count()
        
        # Revenue calculations (from seller's items only)
        revenue_today = seller_items.filter(
            order__order_date__date=today,
            order__payment_status='completed'
        ).aggregate(total=Sum('total_price'))['total'] or Decimal('0')
        
        revenue_this_week = seller_items.filter(
            order__order_date__date__gte=week_start,
            order__payment_status='completed'
        ).aggregate(total=Sum('total_price'))['total'] or Decimal('0')
        
        revenue_this_month = seller_items.filter(
            order__order_date__date__gte=month_start,
            order__payment_status='completed'
        ).aggregate(total=Sum('total_price'))['total'] or Decimal('0')
        
        total_revenue = seller_items.filter(
            order__payment_status='completed'
        ).aggregate(total=Sum('total_price'))['total'] or Decimal('0')
        
        # Average order value (for seller's items)
        avg_item_value = seller_items.filter(
            order__payment_status='completed'
        ).aggregate(avg=Avg('total_price'))['avg'] or Decimal('0')
        
        # Product performance
        product_performance = seller_items.filter(
            order__payment_status='completed'
        ).values(
            'product__title'
        ).annotate(
            quantity_sold=Sum('quantity'),
            revenue=Sum('total_price'),
            orders_count=Count('order', distinct=True)
        ).order_by('-revenue')[:10]
        
        # Item status breakdown (for seller's items)
        item_status_breakdown = {}
        for choice in OrderItem._meta.get_field('item_status').choices:
            status_key = choice[0]
            item_status_breakdown[status_key] = seller_items.filter(item_status=status_key).count()
        
        # Recent activity (last 10 orders with seller's items)
        recent_orders = orders_with_seller_items.order_by('-created_at')[:10]
        recent_activity = []
        for order in recent_orders:
            seller_items_in_order = order.items.filter(seller=user)
            recent_activity.append({
                'order_id': order.id,
                'order_date': order.order_date.isoformat(),
                'customer_name': order.customer_name,
                'status': order.status,
                'items_count': seller_items_in_order.count(),
                'total_value': float(seller_items_in_order.aggregate(total=Sum('total_price'))['total'] or 0)
            })
        
        # Monthly revenue trend (last 6 months)
        monthly_revenue = []
        for i in range(6):
            month_date = (today.replace(day=1) - timedelta(days=i*30)).replace(day=1)
            month_revenue = seller_items.filter(
                order__order_date__date__gte=month_date,
                order__order_date__date__lt=month_date.replace(month=month_date.month+1) if month_date.month < 12 else month_date.replace(year=month_date.year+1, month=1),
                order__payment_status='completed'
            ).aggregate(total=Sum('total_price'))['total'] or Decimal('0')
            
            monthly_revenue.append({
                'month': month_date.strftime('%Y-%m'),
                'revenue': float(month_revenue)
            })
        
        statistics = {
            'total_orders': total_orders,
            'orders_today': orders_today,
            'orders_this_week': orders_this_week,
            'orders_this_month': orders_this_month,
            'total_revenue': float(total_revenue),
            'revenue_today': float(revenue_today),
            'revenue_this_week': float(revenue_this_week),
            'revenue_this_month': float(revenue_this_month),
            'average_item_value': float(avg_item_value),
            'item_status_breakdown': item_status_breakdown,
            'product_performance': list(product_performance),
            'recent_activity': recent_activity,
            'monthly_revenue_trend': list(reversed(monthly_revenue))
        }
        
        serializer = SellerOrderStatisticsSerializer(statistics)
        
        return Response({
            'success': True,
            'statistics': serializer.data
        })


class SellerProductInventoryView(APIView):
    """View and manage product inventory with order impact"""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """Get seller's products with inventory and order information"""
        if request.user.user_type != 'smart_seller':
            return Response({
                'success': False,
                'message': 'Only sellers can access this endpoint'
            }, status=status.HTTP_403_FORBIDDEN)
        
        products = Product.objects.filter(seller=request.user, is_published=True)
        
        inventory_data = []
        for product in products:
            # Get order statistics for this product
            ordered_items = OrderItem.objects.filter(
                product=product,
                order__payment_status__in=['completed', 'pending']
            )
            
            total_ordered = ordered_items.aggregate(
                total=Sum('quantity')
            )['total'] or Decimal('0')
            
            pending_orders = ordered_items.filter(
                item_status__in=['confirmed', 'processing', 'packed']
            ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')
            
            inventory_data.append({
                'product_id': str(product.uuid),
                'title': product.title,
                'category': product.category,
                'current_quantity': float(product.quantity_available),
                'unit': product.unit,
                'price_per_unit': float(product.price_per_unit),
                'total_ordered': float(total_ordered),
                'pending_orders': float(pending_orders),
                'available_for_sale': float(product.quantity_available),
                'low_stock_alert': product.quantity_available < 10,  # You can adjust this threshold
                'revenue_potential': float(product.quantity_available * product.price_per_unit),
                'last_updated': product.updated_at.isoformat()
            })
        
        return Response({
            'success': True,
            'inventory': inventory_data,
            'summary': {
                'total_products': len(inventory_data),
                'low_stock_products': len([p for p in inventory_data if p['low_stock_alert']]),
                'total_inventory_value': sum(p['revenue_potential'] for p in inventory_data)
            }
        })


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def seller_dashboard_summary(request):
    """Get a quick dashboard summary for seller"""
    if request.user.user_type != 'smart_seller':
        return Response({
            'success': False,
            'message': 'Only sellers can access this endpoint'
        }, status=status.HTTP_403_FORBIDDEN)
    
    user = request.user
    today = timezone.now().date()
    
    # Quick stats
    total_products = Product.objects.filter(seller=user, is_published=True).count()
    total_orders = Order.objects.filter(items__seller=user).distinct().count()
    today_orders = Order.objects.filter(items__seller=user, order_date__date=today).distinct().count()
    
    # Revenue today
    today_revenue = OrderItem.objects.filter(
        seller=user,
        order__order_date__date=today,
        order__payment_status='completed'
    ).aggregate(total=Sum('total_price'))['total'] or Decimal('0')
    
    # Pending items to process
    pending_items = OrderItem.objects.filter(
        seller=user,
        item_status__in=['confirmed', 'processing']
    ).count()
    
    # Low stock products
    low_stock_products = Product.objects.filter(
        seller=user,
        is_published=True,
        quantity_available__lt=10
    ).count()
    
    return Response({
        'success': True,
        'dashboard': {
            'total_products': total_products,
            'total_orders': total_orders,
            'today_orders': today_orders,
            'today_revenue': float(today_revenue),
            'pending_items': pending_items,
            'low_stock_products': low_stock_products,
            'alerts': {
                'low_stock': low_stock_products > 0,
                'pending_orders': pending_items > 0
            }
        }
    })