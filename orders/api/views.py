from rest_framework import status, generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import Q, Sum, Count, Avg
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
import uuid
import logging

logger = logging.getLogger(__name__)

from ..models import (
    Order, OrderItem, DeliveryAddress, OrderTracking, 
    OrderStatusHistory, OrderRefund, OrderAnalytics
)
from .serializers import (
    OrderCreateSerializer, OrderListSerializer, OrderDetailSerializer,
    OrderUpdateSerializer, OrderCancelSerializer, OrderReorderSerializer,
    OrderStatisticsSerializer, PaymentSerializer, LiveTrackingSerializer
)
from products.models import Product
from cart.models import Cart


class OrderPagination(PageNumberPagination):
    """Custom pagination for orders"""
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 50


class CreateOrderView(APIView):
    """Create a new order"""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        """Create order from request data"""
        serializer = OrderCreateSerializer(data=request.data, context={'request': request})
        
        if serializer.is_valid():
            try:
                with transaction.atomic():
                    order = serializer.save()
                    
                    # Prepare response data
                    response_data = {
                        'success': True,
                        'message': 'Order created successfully',
                        'order': {
                            'id': order.id,
                            'uuid': str(order.uuid),
                            'status': order.status,
                            'payment_method': order.payment_method,
                            'payment_status': order.payment_status,
                            'total_amount': float(order.total_amount),
                            'estimated_delivery': order.estimated_delivery.isoformat() if order.estimated_delivery else None
                        }
                    }
                    
                    # Handle different payment methods
                    if order.payment_method == 'cod':
                        # For COD, order is confirmed immediately
                        response_data['message'] += ' (Cash on Delivery)'
                        response_data['order']['payment_required'] = False
                    else:
                        # For non-COD orders, payment is required
                        response_data['message'] += ' - Payment required to confirm order'
                        response_data['order']['payment_required'] = True
                        response_data['order']['razorpay_required'] = True
                        response_data['next_step'] = {
                            'action': 'create_razorpay_order',
                            'endpoint': f'/api/orders/{order.uuid}/razorpay/create/',
                            'method': 'POST'
                        }
                    
                    return Response(response_data, status=status.HTTP_201_CREATED)
                    
            except Exception as e:
                return Response({
                    'success': False,
                    'message': str(e)
                }, status=status.HTTP_400_BAD_REQUEST)
        
        return Response({
            'success': False,
            'message': 'Invalid order data',
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class UserOrdersView(generics.ListAPIView):
    """Get user's orders with pagination and filtering"""
    
    serializer_class = OrderListSerializer
    pagination_class = OrderPagination
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Filter orders for current user"""
        queryset = Order.objects.filter(user=self.request.user)
        
        # Apply filters
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
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
        
        return queryset.order_by('-created_at')
    
    def list(self, request, *args, **kwargs):
        """Custom list response format"""
        response = super().list(request, *args, **kwargs)
        
        return Response({
            'success': True,
            'data': response.data
        })


class OrderDetailView(APIView):
    """Get detailed information about a specific order"""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, order_uuid):
        """Get order details by UUID"""
        try:
            order = Order.objects.select_related(
                'delivery_address', 'tracking'
            ).prefetch_related(
                'items', 'status_history'
            ).get(uuid=order_uuid, user=request.user)
            
            serializer = OrderDetailSerializer(order)
            
            return Response({
                'success': True,
                'order': serializer.data
            })
            
        except Order.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Order not found'
            }, status=status.HTTP_404_NOT_FOUND)


class UpdateOrderStatusView(APIView):
    """Update order status (for sellers/admin)"""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def patch(self, request, order_uuid):
        """Update order status"""
        try:
            # Get order and check permissions
            order = Order.objects.get(uuid=order_uuid)
            
            # Check if user is admin or seller of items in the order
            is_admin = getattr(request.user, 'is_staff', False)
            is_seller = order.items.filter(seller=request.user).exists()
            
            if not (is_admin or is_seller):
                return Response({
                    'success': False,
                    'message': 'Permission denied'
                }, status=status.HTTP_403_FORBIDDEN)
            
            serializer = OrderUpdateSerializer(
                order, 
                data=request.data, 
                partial=True,
                context={'is_admin': is_admin}
            )
            
            if serializer.is_valid():
                updated_order = serializer.save()
                
                return Response({
                    'success': True,
                    'message': 'Order status updated successfully',
                    'order': {
                        'id': updated_order.id,
                        'status': updated_order.status,
                        'updated_at': updated_order.updated_at.isoformat()
                    }
                })
            
            return Response({
                'success': False,
                'message': 'Invalid data',
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
            
        except Order.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Order not found'
            }, status=status.HTTP_404_NOT_FOUND)


class CancelOrderView(APIView):
    """Cancel an order with integrated Shiprocket cancellation"""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, order_uuid):
        """Cancel order with Shiprocket integration and process refund if needed"""
        try:
            # Ensure user can only cancel their own orders
            order = Order.objects.get(uuid=order_uuid, user=request.user)
            
            # Check if order can be cancelled
            if not order.can_be_cancelled:
                return Response({
                    'success': False,
                    'message': f'Order in {order.status} status cannot be cancelled'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            serializer = OrderCancelSerializer(
                data=request.data,
                context={'order': order}
            )
            
            if serializer.is_valid():
                with transaction.atomic():
                    reason = serializer.validated_data['reason']
                    shiprocket_cancelled = False
                    shiprocket_message = None
                    
                    # Cancel in Shiprocket if order exists there
                    if order.shiprocket_order_id:
                        try:
                            from services.shiprocket import get_shiprocket_service
                            cancel_response = get_shiprocket_service().cancel_order([int(order.shiprocket_order_id)])
                            
                            if cancel_response['success']:
                                shiprocket_cancelled = True
                                shiprocket_message = cancel_response['message']
                                logger.info(f"Shiprocket order {order.shiprocket_order_id} cancelled successfully")
                            else:
                                logger.warning(f"Failed to cancel Shiprocket order {order.shiprocket_order_id}: {cancel_response}")
                                shiprocket_message = "Failed to cancel in shipping system, but order will be cancelled locally"
                        except Exception as e:
                            logger.error(f"Error cancelling Shiprocket order {order.shiprocket_order_id}: {str(e)}")
                            shiprocket_message = "Shipping system unavailable, but order will be cancelled locally"
                    
                    # Update local order status
                    order.status = 'cancelled'
                    order.save()
                    
                    # Restore product quantities
                    for item in order.items.all():
                        item.product.quantity_available += item.quantity
                        item.product.save()
                    
                    # Create comprehensive status history
                    status_message = f"Order cancelled by customer. Reason: {reason}"
                    if shiprocket_cancelled:
                        status_message += f" | Shiprocket: {shiprocket_message}"
                    elif order.shiprocket_order_id:
                        status_message += f" | Shiprocket cancellation failed but order cancelled locally"
                    
                    OrderStatusHistory.objects.create(
                        order=order,
                        status='cancelled',
                        title='Order Cancelled',
                        message=status_message,
                        location='Customer Request',
                        changed_by=request.user,
                        change_source='customer'
                    )
                    
                    # Create refund if required and payment was made
                    refund_info = None
                    if (serializer.validated_data.get('refund_required', True) and 
                        order.payment_status == 'completed'):
                        
                        refund = OrderRefund.objects.create(
                            order=order,
                            refund_amount=order.total_amount,
                            reason=reason,
                            initiated_by=request.user
                        )
                        
                        refund_info = {
                            'refund_amount': float(refund.refund_amount),
                            'refund_status': refund.refund_status,
                            'estimated_refund_days': refund.estimated_refund_days
                        }
                    
                    # Prepare response
                    response_data = {
                        'success': True,
                        'message': 'Order cancelled successfully',
                        'order': {
                            'id': order.id,
                            'status': order.status,
                            'updated_at': order.updated_at.isoformat()
                        }
                    }
                    
                    # Add Shiprocket status
                    response_data['shiprocket'] = {
                        'cancelled': shiprocket_cancelled,
                        'message': shiprocket_message or 'No shipping order found'
                    }
                    
                    # Add refund info if applicable
                    if refund_info:
                        response_data['refund_info'] = refund_info
                    
                    return Response(response_data)
            
            return Response({
                'success': False,
                'message': 'Invalid cancellation request',
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
            
        except Order.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Order not found'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Unexpected error in order cancellation: {str(e)}")
            return Response({
                'success': False,
                'message': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ReorderView(APIView):
    """Create a new order from existing order items"""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, order_uuid):
        """Create reorder from existing order"""
        try:
            original_order = Order.objects.get(uuid=order_uuid, user=request.user)
            
            if not original_order.can_be_reordered:
                return Response({
                    'success': False,
                    'message': f'Order in {original_order.status} status cannot be reordered'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            serializer = OrderReorderSerializer(
                data=request.data,
                context={'order': original_order}
            )
            
            if serializer.is_valid():
                with transaction.atomic():
                    # Get items to reorder
                    exclude_items = set(serializer.validated_data.get('exclude_items', []))
                    items_to_reorder = original_order.items.exclude(id__in=exclude_items)
                    
                    # Check availability and prepare order data
                    order_items_data = []
                    unavailable_items = []
                    
                    for item in items_to_reorder:
                        if (item.product.is_published and 
                            item.product.quantity_available >= item.quantity):
                            order_items_data.append({
                                'product_id': item.product.uuid,
                                'quantity': item.quantity,
                                'unit_price': item.product.price_per_unit  # Use current price
                            })
                        else:
                            unavailable_items.append({
                                'product_name': item.product_name,
                                'reason': 'Out of stock' if item.product.quantity_available < item.quantity else 'Product unavailable'
                            })
                    
                    if not order_items_data:
                        return Response({
                            'success': False,
                            'message': 'No items available for reorder',
                            'unavailable_items': unavailable_items
                        }, status=status.HTTP_400_BAD_REQUEST)
                    
                    # Prepare order creation data
                    delivery_address_data = serializer.validated_data.get(
                        'delivery_address', 
                        {
                            'name': original_order.delivery_address.name,
                            'phone': original_order.delivery_address.phone,
                            'email': original_order.delivery_address.email,
                            'address_line_1': original_order.delivery_address.address_line_1,
                            'address_line_2': original_order.delivery_address.address_line_2,
                            'city': original_order.delivery_address.city,
                            'state': original_order.delivery_address.state,
                            'pincode': original_order.delivery_address.pincode,
                            'landmark': original_order.delivery_address.landmark,
                            'delivery_instructions': original_order.delivery_address.delivery_instructions,
                        }
                    )
                    
                    reorder_data = {
                        'items': order_items_data,
                        'delivery_address': delivery_address_data,
                        'payment_method': serializer.validated_data.get(
                            'payment_method', 
                            original_order.payment_method
                        ),
                        'clear_cart': False  # Don't clear cart for reorders
                    }
                    
                    # Create new order
                    order_serializer = OrderCreateSerializer(
                        data=reorder_data,
                        context={'request': request}
                    )
                    
                    if order_serializer.is_valid():
                        new_order = order_serializer.save()
                        
                        response_data = {
                            'success': True,
                            'message': 'Reorder created successfully',
                            'new_order': {
                                'id': new_order.id,
                                'uuid': str(new_order.uuid),
                                'total_amount': float(new_order.total_amount)
                            }
                        }
                        
                        if unavailable_items:
                            response_data['unavailable_items'] = unavailable_items
                        
                        return Response(response_data, status=status.HTTP_201_CREATED)
                    
                    return Response({
                        'success': False,
                        'message': 'Failed to create reorder',
                        'errors': order_serializer.errors
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            return Response({
                'success': False,
                'message': 'Invalid reorder data',
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
            
        except Order.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Original order not found'
            }, status=status.HTTP_404_NOT_FOUND)


class OrderTrackingView(APIView):
    """Get order tracking information"""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, order_uuid):
        """Get tracking info for order"""
        try:
            order = Order.objects.select_related('tracking').prefetch_related(
                'status_history'
            ).get(uuid=order_uuid, user=request.user)
            
            # Prepare tracking response
            tracking_data = {
                'order_id': order.id,
                'current_status': order.status,
                'estimated_delivery': order.estimated_delivery.isoformat() if order.estimated_delivery else None
            }
            
            # Add tracking details if available
            if hasattr(order, 'tracking'):
                tracking = order.tracking
                tracking_data.update({
                    'tracking_number': tracking.tracking_number,
                    'delivery_partner': tracking.delivery_partner,
                    'delivery_person': {
                        'name': tracking.delivery_person_name,
                        'phone': tracking.delivery_person_phone,
                        'vehicle_number': tracking.delivery_vehicle_number
                    } if tracking.delivery_person_name else None
                })
                
                if tracking.current_location:
                    tracking_data['delivery_person']['location'] = tracking.current_location
            
            # Add status timeline
            status_timeline = []
            for history in order.status_history.all():
                status_timeline.append({
                    'status': history.status,
                    'timestamp': history.timestamp.isoformat(),
                    'title': history.title,
                    'message': history.message,
                    'location': history.location
                })
            
            tracking_data['status_timeline'] = status_timeline
            
            return Response({
                'success': True,
                'tracking': tracking_data
            })
            
        except Order.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Order not found'
            }, status=status.HTTP_404_NOT_FOUND)


class LiveTrackingView(APIView):
    """Get live tracking for orders in transit"""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, order_uuid):
        """Get live location updates"""
        try:
            order = Order.objects.select_related('tracking').get(
                uuid=order_uuid, 
                user=request.user,
                status='in_transit'
            )
            
            if not hasattr(order, 'tracking'):
                return Response({
                    'success': False,
                    'message': 'Tracking information not available'
                }, status=status.HTTP_404_NOT_FOUND)
            
            tracking = order.tracking
            
            live_tracking_data = {
                'order_id': order.id,
                'status': order.status,
                'delivery_person': {
                    'name': tracking.delivery_person_name or 'Driver',
                    'phone': tracking.delivery_person_phone,
                    'vehicle_number': tracking.delivery_vehicle_number
                },
                'current_location': tracking.current_location,
                'last_updated': tracking.last_location_update.isoformat() if tracking.last_location_update else None
            }
            
            return Response({
                'success': True,
                'live_tracking': live_tracking_data
            })
            
        except Order.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Order not found or not in transit'
            }, status=status.HTTP_404_NOT_FOUND)


class ProcessPaymentView(APIView):
    """Process payment for an order (Legacy - Use Razorpay APIs for new payments)"""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, order_uuid):
        """Process payment for order"""
        try:
            order = Order.objects.get(uuid=order_uuid, user=request.user)
            
            if order.payment_status == 'completed':
                return Response({
                    'success': False,
                    'message': 'Payment already completed for this order'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if this is a non-COD order and redirect to Razorpay
            if order.payment_method in ['upi', 'netbanking', 'card', 'wallet']:
                return Response({
                    'success': False,
                    'message': 'Please use Razorpay payment flow for this payment method',
                    'redirect_to': {
                        'endpoint': f'/api/orders/{order.uuid}/razorpay/create/',
                        'method': 'POST'
                    }
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Handle COD orders
            if order.payment_method == 'cod':
                # For COD, mark as confirmed immediately
                with transaction.atomic():
                    order.status = 'confirmed'
                    order.payment_status = 'pending'  # COD payment is pending until delivery
                    order.save()
                    
                    # Create status history
                    OrderStatusHistory.objects.create(
                        order=order,
                        status='confirmed',
                        title='COD Order Confirmed',
                        message='Cash on Delivery order confirmed',
                        location='System',
                        change_source='cod'
                    )
                
                return Response({
                    'success': True,
                    'message': 'COD order confirmed successfully',
                    'order': {
                        'id': order.id,
                        'status': order.status,
                        'payment_status': order.payment_status,
                        'payment_method': order.payment_method
                    }
                })
            
            return Response({
                'success': False,
                'message': 'Invalid payment method'
            }, status=status.HTTP_400_BAD_REQUEST)
            
        except Order.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Order not found'
            }, status=status.HTTP_404_NOT_FOUND)


class PaymentStatusView(APIView):
    """Get payment status for an order"""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, order_uuid):
        """Get payment status"""
        try:
            order = Order.objects.get(uuid=order_uuid, user=request.user)
            
            payment_data = {
                'order_id': order.id,
                'status': order.payment_status,
                'transaction_id': order.payment_transaction_id,
                'amount': float(order.total_amount),
                'payment_method': order.payment_method,
                'payment_date': order.created_at.isoformat() if order.payment_status == 'completed' else None,
                'refund_eligible': order.can_be_cancelled and order.payment_status == 'completed',
                'refund_amount': float(order.total_amount) if order.can_be_cancelled else 0
            }
            
            return Response({
                'success': True,
                'payment': payment_data
            })
            
        except Order.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Order not found'
            }, status=status.HTTP_404_NOT_FOUND)


class OrderStatisticsView(APIView):
    """Get order statistics for dashboard"""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """Get user's order statistics"""
        user = request.user
        now = timezone.now()
        today = now.date()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        
        # Base queryset for user's orders
        orders = Order.objects.filter(user=user)
        
        # Calculate statistics
        total_orders = orders.count()
        orders_today = orders.filter(order_date__date=today).count()
        orders_this_week = orders.filter(order_date__date__gte=week_start).count()
        orders_this_month = orders.filter(order_date__date__gte=month_start).count()
        
        # Revenue calculations (only for completed payments)
        completed_orders = orders.filter(payment_status='completed')
        
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
            status_breakdown[status_key] = orders.filter(status=status_key).count()
        
        # Top products (from user's orders)
        top_products = []
        product_stats = OrderItem.objects.filter(
            order__user=user,
            order__payment_status='completed'
        ).values(
            'product_name'
        ).annotate(
            orders_count=Count('order', distinct=True),
            revenue=Sum('total_price')
        ).order_by('-orders_count')[:5]
        
        for product in product_stats:
            top_products.append({
                'product_name': product['product_name'],
                'orders_count': product['orders_count'],
                'revenue': float(product['revenue'] or 0)
            })
        
        statistics = {
            'total_orders': total_orders,
            'orders_today': orders_today,
            'orders_this_week': orders_this_week,
            'orders_this_month': orders_this_month,
            'revenue_today': float(revenue_today),
            'revenue_this_week': float(revenue_this_week),
            'revenue_this_month': float(revenue_this_month),
            'average_order_value': float(avg_order_value),
            'status_breakdown': status_breakdown,
            'top_products': top_products
        }
        
        serializer = OrderStatisticsSerializer(statistics)
        
        return Response({
            'success': True,
            'statistics': serializer.data
        })