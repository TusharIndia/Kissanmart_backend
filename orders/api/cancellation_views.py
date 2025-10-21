"""
Order cancellation and refund API views
"""

from rest_framework import status, generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)

from ..models import Order, OrderCancellationRequest, OrderStatusHistory
from .serializers import (
    OrderCancellationRequestSerializer, OrderCancellationRequestCreateSerializer,
    OrderCancellationStatusSerializer, AdminRefundProcessSerializer
)
from ..razorpay_service import RazorpayService
from services.shiprocket import get_shiprocket_service


class CheckOrderCancellationEligibilityView(APIView):
    """Check if an order can be cancelled based on Shiprocket pickup status"""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, order_uuid):
        """Check cancellation eligibility for an order"""
        try:
            order = Order.objects.get(uuid=order_uuid, user=request.user)
            # Do not allow cancellations for Cash on Delivery orders
            if getattr(order, 'payment_method', None) == 'cod':
                return Response({
                    'success': True,
                    'can_cancel': False,
                    'reason': 'Cash on Delivery orders cannot be cancelled',
                    'current_status': order.status,
                    'payment_method': order.payment_method
                })
            
            # Basic status check
            if order.status in ['cancelled', 'refunded', 'delivered']:
                return Response({
                    'success': True,
                    'can_cancel': False,
                    'reason': f'Order is already {order.status}',
                    'current_status': order.status
                })
            
            # Check if cancellation request already exists
            if hasattr(order, 'cancellation_request'):
                cancellation_request = order.cancellation_request
                return Response({
                    'success': True,
                    'can_cancel': False,
                    'reason': f'Cancellation request already exists with status: {cancellation_request.request_status}',
                    'current_status': order.status,
                    'cancellation_status': cancellation_request.request_status
                })
            
            # Check payment status
            if order.payment_status != 'completed':
                return Response({
                    'success': True,
                    'can_cancel': False,
                    'reason': 'Only paid orders can be cancelled for refund',
                    'current_status': order.status,
                    'payment_status': order.payment_status
                })
            
            # Check Shiprocket pickup status
            response_data = {
                'success': True,
                'can_cancel': True,
                'reason': 'Order can be cancelled',
                'current_status': order.status,
                'shiprocket_status': order.shiprocket_status
            }
            
            # If order has Shiprocket shipment, check pickup status
            if order.shiprocket_order_id:
                try:
                    shiprocket_service = get_shiprocket_service()
                    eligibility_check = shiprocket_service.check_cancellation_eligibility(
                        order_id=order.id
                    )
                    
                    if eligibility_check['success']:
                        response_data.update({
                            'can_cancel': eligibility_check['can_cancel'],
                            'reason': eligibility_check['message'],
                            'pickup_scheduled_date': eligibility_check.get('pickup_scheduled_date'),
                            'pickup_completed': eligibility_check.get('pickup_completed', False),
                            'shiprocket_status': eligibility_check.get('current_status', order.shiprocket_status)
                        })
                        
                        # Update order with latest Shiprocket status
                        if eligibility_check.get('current_status'):
                            order.shiprocket_status = eligibility_check['current_status']
                            
                        # Update cancellation deadline based on pickup schedule
                        if eligibility_check.get('pickup_datetime'):
                            order.can_cancel_till = eligibility_check['pickup_datetime']
                            
                        order.save()
                    else:
                        logger.warning(f"Shiprocket eligibility check failed for order {order.id}: {eligibility_check.get('error')}")
                        # Fall back to basic status check
                        response_data.update({
                            'can_cancel': order.can_be_cancelled,
                            'reason': 'Could not verify pickup status with Shiprocket, using basic status check'
                        })
                        
                except Exception as e:
                    logger.error(f"Error checking Shiprocket status for order {order.id}: {str(e)}")
                    # Fall back to basic status check
                    response_data.update({
                        'can_cancel': order.can_be_cancelled,
                        'reason': 'Could not verify pickup status, using basic status check'
                    })
            
            return Response(response_data)
            
        except Order.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Order not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        except Exception as e:
            logger.error(f"Error checking cancellation eligibility: {str(e)}")
            return Response({
                'success': False,
                'message': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CreateCancellationRequestView(APIView):
    """Create a cancellation request for an order"""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, order_uuid):
        """Create cancellation request"""
        try:
            order = Order.objects.get(uuid=order_uuid, user=request.user)
            
            # Log incoming request data for debugging
            logger.debug(f"CreateCancellationRequestView incoming data: {request.data}")

            # Do not allow cancellation requests for Cash on Delivery orders
            if getattr(order, 'payment_method', None) == 'cod':
                return Response({
                    'success': False,
                    'message': 'Cash on Delivery orders cannot request cancellation or refund'
                }, status=status.HTTP_400_BAD_REQUEST)

            serializer = OrderCancellationRequestCreateSerializer(
                data=request.data,
                context={'order': order}
            )
            
            if serializer.is_valid():
                cancellation_request = serializer.save()
                
                # Serialize the created request for response
                response_serializer = OrderCancellationRequestSerializer(cancellation_request)
                
                return Response({
                    'success': True,
                    'message': 'Cancellation request submitted successfully',
                    'cancellation_request': response_serializer.data
                }, status=status.HTTP_201_CREATED)
            
            logger.info(f"Cancellation request validation failed for order {order.id}: {serializer.errors}")
            return Response({
                'success': False,
                'message': 'Invalid cancellation request data',
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
            
        except Order.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Order not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        except Exception as e:
            # Log full exception with traceback to help debugging 500s
            logger.exception(f"Unhandled error creating cancellation request for order UUID {order_uuid}: {str(e)}")
            return Response({
                'success': False,
                'message': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CancellationRequestDetailView(APIView):
    """Get cancellation request details"""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, order_uuid):
        """Get cancellation request for an order"""
        try:
            order = Order.objects.get(uuid=order_uuid, user=request.user)
            
            if not hasattr(order, 'cancellation_request'):
                return Response({
                    'success': False,
                    'message': 'No cancellation request found for this order'
                }, status=status.HTTP_404_NOT_FOUND)
            
            serializer = OrderCancellationRequestSerializer(order.cancellation_request)
            
            return Response({
                'success': True,
                'cancellation_request': serializer.data
            })
            
        except Order.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Order not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        except Exception as e:
            logger.error(f"Error getting cancellation request: {str(e)}")
            return Response({
                'success': False,
                'message': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


from .admin_views import check_admin_permission
class AdminCancellationRequestListView(generics.ListAPIView):
    """Admin view to list all cancellation requests"""

    # We'll validate admin access inside the view to allow header-based admin tokens
    permission_classes = [permissions.AllowAny]
    serializer_class = OrderCancellationRequestSerializer
    pagination_class = PageNumberPagination

    def get_queryset(self):
        """Get all cancellation requests with filtering"""
        queryset = OrderCancellationRequest.objects.all().select_related(
            'order', 'reviewed_by'
        ).order_by('-requested_at')

        # Filter by status
        status_filter = self.request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(request_status=status_filter)

        # Filter by date range
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')

        if start_date:
            try:
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
                queryset = queryset.filter(requested_at__date__gte=start_date)
            except ValueError:
                pass

        if end_date:
            try:
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
                queryset = queryset.filter(requested_at__date__lte=end_date)
            except ValueError:
                pass

        return queryset

    def list(self, request, *args, **kwargs):
        # Check admin permission using shared helper (checks staff or X-Admin-Token header)
        if not check_admin_permission(request):
            return Response({'success': False, 'message': 'Admin access required'}, status=status.HTTP_403_FORBIDDEN)

        return super().list(request, *args, **kwargs)


class AdminProcessRefundView(APIView):
    """Admin view to process refund for cancellation request"""

    permission_classes = [permissions.AllowAny]

    def post(self, request, cancellation_request_id):
        """Process refund for a cancellation request"""
        # Require admin header or staff
        if not check_admin_permission(request):
            return Response({'success': False, 'message': 'Admin access required'}, status=status.HTTP_403_FORBIDDEN)

        try:
            cancellation_request = OrderCancellationRequest.objects.get(id=cancellation_request_id)

            # Some clients send text/plain or form-encoded bodies. Normalize into a dict.
            incoming_data = None
            content_type = request.content_type or ''
            if content_type.startswith('application/json'):
                incoming_data = request.data
            else:
                # Try to parse body as JSON if possible
                try:
                    import json
                    body_text = request.body.decode('utf-8') if request.body else ''
                    if body_text:
                        incoming_data = json.loads(body_text)
                    else:
                        # Fallback to POST params
                        incoming_data = request.POST.dict() if hasattr(request, 'POST') else {}
                except Exception:
                    # Fallback to POST params
                    incoming_data = request.POST.dict() if hasattr(request, 'POST') else {}

            serializer = AdminRefundProcessSerializer(
                data=incoming_data or {},
                context={'cancellation_request': cancellation_request}
            )

            if not serializer.is_valid():
                return Response({
                    'success': False,
                    'message': 'Invalid refund processing data',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)

            admin_notes = serializer.validated_data.get('admin_notes', '')
            # Resolve admin user if available; header-based admin auth may not set request.user
            admin_user = request.user if getattr(request.user, 'is_authenticated', False) else None
            processed_by_name = None
            try:
                if admin_user:
                    # prefer full name, fallback to username
                    processed_by_name = admin_user.get_full_name() or getattr(admin_user, 'username', None)
            except Exception:
                processed_by_name = None
            if not processed_by_name:
                # fallback to header token or generic label
                processed_by_name = request.headers.get('X-Admin-Token') or 'admin'
            process_refund = serializer.validated_data.get('process_refund', True)
            cancel_in_shiprocket = serializer.validated_data.get('cancel_in_shiprocket', True)

            order = cancellation_request.order

            with transaction.atomic():
                # Approve the cancellation request using resolved admin_user (may be None when header-based token used)
                cancellation_request.approve_cancellation(admin_user, admin_notes)

                # Apply admin overrides if provided
                rpd = serializer.validated_data.get('razorpay_fee_deduction')
                pfd = serializer.validated_data.get('platform_fee_deduction')
                final_override = serializer.validated_data.get('final_refund_amount')

                # Use Decimal for calculations
                try:
                    refund_total = Decimal(cancellation_request.refund_amount)
                except Exception:
                    refund_total = Decimal(order.total_amount or 0)

                # If admin provided deduction overrides, use them
                if rpd is not None or pfd is not None:
                    rpd_val = Decimal(rpd or Decimal('0.00'))
                    pfd_val = Decimal(pfd or Decimal('0.00'))
                    cancellation_request.razorpay_fee_deduction = rpd_val
                    cancellation_request.platform_fee_deduction = pfd_val
                    cancellation_request.final_refund_amount = max(refund_total - (rpd_val + pfd_val), Decimal('0.00'))

                # If admin provided final amount override, use it (and derive deductions if not provided)
                if final_override is not None:
                    final_val = Decimal(final_override)
                    cancellation_request.final_refund_amount = final_val
                    # If specific deductions were not provided, compute them proportionally from stored order fees
                    if rpd is None:
                        cancellation_request.razorpay_fee_deduction = cancellation_request.razorpay_fee_deduction or order.razorpay_fee
                    if pfd is None:
                        cancellation_request.platform_fee_deduction = cancellation_request.platform_fee_deduction or order.platform_fee

                # Ensure fields saved before processing
                cancellation_request.save()

                # Process refund if requested
                refund_success = False
                razorpay_refund_id = ''

                if process_refund and order.razorpay_payment_id:
                    try:
                        razorpay_service = RazorpayService()

                        # Determine final refund amount
                        final_amount = Decimal(cancellation_request.final_refund_amount)
                        refund_amount_paise = int((final_amount * 100).quantize(Decimal('1')))

                        logger.info(f"Processing Razorpay refund for order {order.id}: amount ₹{final_amount} (paise={refund_amount_paise})")

                        refund_response = razorpay_service.refund_payment(
                            payment_id=order.razorpay_payment_id,
                            amount=refund_amount_paise,
                            notes={
                                'order_id': order.id,
                                'cancellation_request_id': str(cancellation_request.id),
                                'reason': cancellation_request.get_reason_display(),
                                'processed_by': processed_by_name
                            }
                        )

                        if refund_response.get('success'):
                            refund_success = True
                            razorpay_refund_id = refund_response['refund']['id']

                            # Mark refund as processed
                            cancellation_request.razorpay_refund_id = razorpay_refund_id
                            cancellation_request.mark_refund_processed(razorpay_refund_id)

                            # Update order payment status
                            order.payment_status = 'refunded'
                            order.save()

                            # Create status history
                            OrderStatusHistory.objects.create(
                                order=order,
                                status=order.status,
                                title='Refund Processed',
                                message=f'Refund of ₹{cancellation_request.final_refund_amount} processed successfully. Refund ID: {razorpay_refund_id}',
                                location='Admin Panel',
                                change_source='admin'
                            )

                        else:
                            logger.error(f"Failed to process refund: {refund_response}")
                            return Response({
                                'success': False,
                                'message': 'Failed to process refund in Razorpay',
                                'error': refund_response.get('error')
                            }, status=status.HTTP_400_BAD_REQUEST)

                    except Exception as e:
                        logger.error(f"Error processing refund: {str(e)}")
                        return Response({
                            'success': False,
                            'message': 'Error processing refund',
                            'error': str(e)
                        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                # After refund is successful (or if refund not requested), cancel in Shiprocket if requested
                shiprocket_cancelled = False
                if cancel_in_shiprocket and order.shiprocket_order_id:
                    try:
                        # Only attempt cancellation if refund succeeded or refund not required
                        if (process_refund and refund_success) or (not process_refund):
                            shiprocket_service = get_shiprocket_service()
                            cancel_response = shiprocket_service.cancel_order([int(order.shiprocket_order_id)])

                            if cancel_response.get('success'):
                                shiprocket_cancelled = True
                                cancellation_request.shiprocket_cancelled = True
                                cancellation_request.shiprocket_cancellation_response = cancel_response.get('response')
                                cancellation_request.save()

                                # Update order status to cancelled
                                order.status = 'cancelled'
                                order.save()

                                # Create status history
                                OrderStatusHistory.objects.create(
                                    order=order,
                                    status='cancelled',
                                    title='Order Cancelled in Shiprocket',
                                    message='Order successfully cancelled in Shiprocket',
                                    location='Admin Panel',
                                    change_source='admin'
                                )
                            else:
                                logger.error(f"Failed to cancel order in Shiprocket: {cancel_response}")
                        else:
                            logger.warning(f"Skipping Shiprocket cancel for order {order.id} because refund did not succeed")

                    except Exception as e:
                        logger.error(f"Error cancelling order in Shiprocket: {str(e)}")

            # Prepare response
            response_data = {
                'success': True,
                'message': 'Cancellation request processed successfully',
                'shiprocket_cancelled': shiprocket_cancelled,
                'refund_processed': refund_success,
                'refund_amount': float(cancellation_request.final_refund_amount),
                'razorpay_refund_id': razorpay_refund_id
            }

            return Response(response_data)

        except OrderCancellationRequest.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Cancellation request not found'
            }, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            logger.error(f"Error processing refund: {str(e)}")
            return Response({
                'success': False,
                'message': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AdminRejectCancellationView(APIView):
    """Admin view to reject a cancellation request"""

    permission_classes = [permissions.AllowAny]

    def post(self, request, cancellation_request_id):
        """Reject a cancellation request"""
        # Require admin header or staff
        if not check_admin_permission(request):
            return Response({'success': False, 'message': 'Admin access required'}, status=status.HTTP_403_FORBIDDEN)

        try:
            cancellation_request = OrderCancellationRequest.objects.get(id=cancellation_request_id)

            # Some clients send text/plain or form-encoded bodies. Normalize into a dict.
            incoming_data = None
            content_type = request.content_type or ''
            if content_type.startswith('application/json'):
                incoming_data = request.data
            else:
                try:
                    import json
                    body_text = request.body.decode('utf-8') if request.body else ''
                    if body_text:
                        # Try parse JSON body if present
                        try:
                            incoming_data = json.loads(body_text)
                        except Exception:
                            # Fallback to POST params
                            incoming_data = request.POST.dict() if hasattr(request, 'POST') else {}
                    else:
                        incoming_data = request.POST.dict() if hasattr(request, 'POST') else {}
                except Exception:
                    incoming_data = request.POST.dict() if hasattr(request, 'POST') else {}

            admin_notes = ''
            try:
                if isinstance(incoming_data, dict):
                    admin_notes = incoming_data.get('admin_notes', '')
                else:
                    # final fallback: try request.data
                    admin_notes = request.data.get('admin_notes', '')
            except Exception:
                admin_notes = request.data.get('admin_notes', '')

            if cancellation_request.request_status != 'pending':
                return Response({
                    'success': False,
                    'message': f'Cannot reject request in {cancellation_request.request_status} status'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Resolve admin user (may use header token flow where request.user is anonymous)
            admin_user = request.user if getattr(request.user, 'is_authenticated', False) else None

            # Reject the cancellation request
            cancellation_request.reject_cancellation(admin_user, admin_notes)

            # Create status history
            OrderStatusHistory.objects.create(
                order=cancellation_request.order,
                status=cancellation_request.order.status,
                title='Cancellation Request Rejected',
                message=f'Cancellation request rejected by admin. Reason: {admin_notes}',
                location='Admin Panel',
                change_source='admin'
            )

            return Response({
                'success': True,
                'message': 'Cancellation request rejected successfully'
            })

        except OrderCancellationRequest.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Cancellation request not found'
            }, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            logger.error(f"Error rejecting cancellation request: {str(e)}")
            return Response({
                'success': False,
                'message': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def admin_cancellation_stats(request):
    """Get cancellation request statistics for admin dashboard"""
    # Require admin header or staff
    if not check_admin_permission(request):
        return Response({'success': False, 'message': 'Admin access required'}, status=status.HTTP_403_FORBIDDEN)

    try:
        # Get counts by status
        total_requests = OrderCancellationRequest.objects.count()
        pending_requests = OrderCancellationRequest.objects.filter(request_status='pending').count()
        approved_requests = OrderCancellationRequest.objects.filter(request_status='approved').count()
        processed_requests = OrderCancellationRequest.objects.filter(request_status='refund_processed').count()
        rejected_requests = OrderCancellationRequest.objects.filter(request_status='rejected').count()
        
        # Get total refund amounts
        from django.db.models import Sum
        total_refund_amount = OrderCancellationRequest.objects.filter(
            request_status='refund_processed'
        ).aggregate(Sum('final_refund_amount'))['final_refund_amount__sum'] or Decimal('0.00')
        
        # Get recent requests
        recent_requests = OrderCancellationRequest.objects.filter(
            requested_at__gte=timezone.now() - timedelta(days=7)
        ).count()
        
        return Response({
            'success': True,
            'stats': {
                'total_requests': total_requests,
                'pending_requests': pending_requests,
                'approved_requests': approved_requests,
                'processed_requests': processed_requests,
                'rejected_requests': rejected_requests,
                'total_refund_amount': float(total_refund_amount),
                'recent_requests': recent_requests
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting cancellation stats: {str(e)}")
        return Response({
            'success': False,
            'message': 'Internal server error'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)