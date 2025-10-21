"""
Razorpay payment API views
"""

from rest_framework import status, parsers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import permissions
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.utils import timezone
from decimal import Decimal
import logging

from ..models import Order, OrderStatusHistory
from ..razorpay_service import RazorpayService
from .serializers import RazorpayOrderCreateSerializer, RazorpayPaymentVerificationSerializer

logger = logging.getLogger(__name__)


class CreateRazorpayOrderView(APIView):
    """Create Razorpay order for non-COD payments"""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, order_uuid):
        """Create Razorpay order for existing order"""
        try:
            order = Order.objects.get(uuid=order_uuid, user=request.user)
            
            # Check if order is eligible for Razorpay payment
            if order.payment_method == 'cod':
                return Response({
                    'success': False,
                    'message': 'COD orders do not require Razorpay payment'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if order.payment_status == 'completed':
                return Response({
                    'success': False,
                    'message': 'Payment already completed for this order'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if order.razorpay_order_id:
                return Response({
                    'success': False,
                    'message': 'Razorpay order already created for this order'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Update shipping charges if provided in request
            shipping_charges = request.data.get('shipping_charges')
            courier_name = request.data.get('courier_name', '')
            
            if shipping_charges is not None:
                try:
                    shipping_charges = Decimal(str(shipping_charges))
                    if shipping_charges >= 0:
                        # Update order with selected shipping charges
                        with transaction.atomic():
                            order.shipping_charges = shipping_charges
                            # Recalculate platform_fee and payment_mode_charge using the updated shipping so the
                            # Razorpay amount reflects portal charges applied to the final payable base.
                            # Recompute platform fee using admin-configured PaymentModeCharge percentage
                            from ..models import PaymentModeCharge
                            try:
                                pct = PaymentModeCharge.get_percentage_for_mode(order.payment_method)
                                platform_base = order.subtotal + order.shipping_charges
                                order.platform_fee = (platform_base * (Decimal(str(pct)) / Decimal('100.0'))).quantize(Decimal('0.01'))
                            except Exception:
                                order.platform_fee = Decimal('0.00')

                            # No portal/payment-mode charge is used separately; razorpay fee bookkeeping remains zero
                            order.payment_mode_charge = Decimal('0.00')
                            order.razorpay_fee = Decimal('0.00')

                            # Recalculate final total_amount to be sent to Razorpay
                            order.total_amount = (
                                order.subtotal
                                + order.shipping_charges
                                + order.tax_amount
                                + order.platform_fee
                                - order.discount_amount
                            )
                            order.shiprocket_courier_name = courier_name
                            order.save()
                            
                            # Create status history for shipping update
                            OrderStatusHistory.objects.create(
                                order=order,
                                status=order.status,
                                title='Shipping Option Selected',
                                message=f'Shipping charges updated to ₹{shipping_charges}' + (f' for {courier_name}' if courier_name else ''),
                                location='Payment Gateway',
                                change_source='customer'
                            )
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid shipping_charges value: {shipping_charges}, error: {e}")
                    # Continue with existing charges if invalid
            
            # Initialize Razorpay service
            razorpay_service = RazorpayService()
            
            # Create Razorpay order
            razorpay_response = razorpay_service.create_order(
                amount=order.total_amount,
                receipt=order.id,
                notes={
                    'order_id': order.id,
                    'customer_name': order.customer_name,
                    'customer_email': order.customer_email,
                    'customer_phone': order.customer_phone
                }
            )
            
            if not razorpay_response['success']:
                return Response({
                    'success': False,
                    'message': 'Failed to create Razorpay order',
                    'error': razorpay_response['error']
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Update order with Razorpay order ID
            with transaction.atomic():
                order.razorpay_order_id = razorpay_response['order']['id']
                order.save()
                
                # Create status history
                OrderStatusHistory.objects.create(
                    order=order,
                    status=order.status,
                    title='Payment Gateway Order Created',
                    message=f"Razorpay order created: {razorpay_response['order']['id']}",
                    location='Payment Gateway',
                    change_source='razorpay'
                )
            
            # Prepare response data
            response_data = {
                'success': True,
                'message': 'Razorpay order created successfully',
                'razorpay_order': {
                    'id': razorpay_response['order']['id'],
                    'amount': razorpay_response['order']['amount'],
                    'currency': razorpay_response['order']['currency'],
                    'status': razorpay_response['order']['status']
                },
                'payment_data': {
                    'key': razorpay_service.client.auth[0],  # Razorpay Key ID
                    'amount': razorpay_response['order']['amount'],
                    'currency': razorpay_response['order']['currency'],
                    'order_id': razorpay_response['order']['id'],
                    'name': 'KissanMart',
                    'description': f'Payment for Order #{order.id}',
                    'prefill': {
                        'name': order.customer_name,
                        'email': order.customer_email,
                        'contact': order.customer_phone
                    },
                    'theme': {
                        'color': '#4CAF50'  # Green theme for agricultural platform
                    }
                }
            }
            
            return Response(response_data, status=status.HTTP_201_CREATED)
            
        except Order.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Order not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        except Exception as e:
            logger.error(f"Error creating Razorpay order: {str(e)}")
            return Response({
                'success': False,
                'message': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class VerifyRazorpayPaymentView(APIView):
    """Verify Razorpay payment and update order status"""
    
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [parsers.JSONParser, parsers.FormParser, parsers.MultiPartParser]
    
    def post(self, request, order_uuid):
        """Verify payment signature and update order"""
        try:
            # Log the incoming request data for debugging
            logger.info(f"Razorpay verification request data: {request.data}")
            logger.info(f"Request content type: {request.content_type}")
            
            order = Order.objects.get(uuid=order_uuid, user=request.user)
            
            if order.payment_status == 'completed':
                return Response({
                    'success': False,
                    'message': 'Payment already completed for this order'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if request.data is accessible
            try:
                request_data = request.data
                logger.info(f"Successfully accessed request.data: {request_data}")
            except Exception as data_error:
                logger.error(f"Error accessing request.data: {data_error}")
                return Response({
                    'success': False,
                    'message': 'Invalid request data format',
                    'error': 'Could not parse request data'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            serializer = RazorpayPaymentVerificationSerializer(data=request_data)
            
            if not serializer.is_valid():
                logger.error(f"Serializer validation failed: {serializer.errors}")
                return Response({
                    'success': False,
                    'message': 'Invalid payment verification data',
                    'errors': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Extract payment data
            razorpay_order_id = serializer.validated_data['razorpay_order_id']
            razorpay_payment_id = serializer.validated_data['razorpay_payment_id']
            razorpay_signature = serializer.validated_data['razorpay_signature']
            
            # Verify order ID matches
            if order.razorpay_order_id != razorpay_order_id:
                return Response({
                    'success': False,
                    'message': 'Order ID mismatch'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Initialize Razorpay service and verify signature
            razorpay_service = RazorpayService()
            
            is_signature_valid = razorpay_service.verify_payment_signature(
                razorpay_order_id=razorpay_order_id,
                razorpay_payment_id=razorpay_payment_id,
                razorpay_signature=razorpay_signature
            )
            
            if not is_signature_valid:
                return Response({
                    'success': False,
                    'message': 'Invalid payment signature'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Fetch payment details for additional verification
            payment_response = razorpay_service.fetch_payment(razorpay_payment_id)
            
            if not payment_response['success']:
                return Response({
                    'success': False,
                    'message': 'Failed to fetch payment details',
                    'error': payment_response['error']
                }, status=status.HTTP_400_BAD_REQUEST)
            
            payment_details = payment_response['payment']
            
            # Verify payment amount matches order amount
            expected_amount = int(order.total_amount * 100)  # Convert to paise
            if payment_details['amount'] != expected_amount:
                return Response({
                    'success': False,
                    'message': 'Payment amount mismatch'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Verify payment status
            if payment_details['status'] != 'captured':
                return Response({
                    'success': False,
                    'message': f'Payment not captured. Status: {payment_details["status"]}'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Update order with successful payment
            with transaction.atomic():
                order.payment_status = 'completed'
                order.payment_transaction_id = razorpay_payment_id
                order.razorpay_payment_id = razorpay_payment_id
                order.razorpay_signature = razorpay_signature
                # Ensure payment_details is serializable
                try:
                    order.payment_gateway_response = payment_details
                except Exception as json_error:
                    logger.warning(f"Could not save payment_details as JSON: {json_error}")
                    order.payment_gateway_response = {
                        'payment_id': razorpay_payment_id,
                        'status': 'captured',
                        'amount': payment_details.get('amount', 0),
                        'currency': payment_details.get('currency', 'INR'),
                        'method': payment_details.get('method', 'unknown')
                    }
                
                # Update order status to confirmed if it was pending
                if order.status == 'pending':
                    order.status = 'confirmed'
                
                order.save()
                
                # Create status history
                OrderStatusHistory.objects.create(
                    order=order,
                    status='confirmed',
                    title='Payment Successful',
                    message=f'Payment completed successfully. Transaction ID: {razorpay_payment_id}',
                    location='Payment Gateway',
                    change_source='razorpay'
                )
            
            # Prepare response
            response_data = {
                'success': True,
                'message': 'Payment verified and order confirmed successfully',
                'order': {
                    'id': order.id,
                    'status': order.status,
                    'payment_status': order.payment_status,
                    'payment_transaction_id': order.payment_transaction_id,
                    'total_amount': float(order.total_amount)
                },
                'payment_details': {
                    'razorpay_payment_id': razorpay_payment_id,
                    'amount': payment_details['amount'] / 100,  # Convert back to rupees
                    'currency': payment_details['currency'],
                    'method': payment_details['method'],
                    'status': payment_details['status'],
                    'created_at': payment_details['created_at']
                }
            }
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except Order.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Order not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        except Exception as e:
            import traceback
            logger.error(f"Error verifying Razorpay payment: {str(e)}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            logger.error(f"Request data was: {request.data}")
            return Response({
                'success': False,
                'message': 'Internal server error',
                'error': str(e) if request.user.is_staff else 'Payment verification failed'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RazorpayPaymentStatusView(APIView):
    """Get Razorpay payment status for an order"""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, order_uuid):
        """Get payment status from Razorpay"""
        try:
            order = Order.objects.get(uuid=order_uuid, user=request.user)
            
            if not order.razorpay_payment_id:
                return Response({
                    'success': False,
                    'message': 'No Razorpay payment found for this order'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Initialize Razorpay service and fetch payment
            razorpay_service = RazorpayService()
            payment_response = razorpay_service.fetch_payment(order.razorpay_payment_id)
            
            if not payment_response['success']:
                return Response({
                    'success': False,
                    'message': 'Failed to fetch payment status',
                    'error': payment_response['error']
                }, status=status.HTTP_400_BAD_REQUEST)
            
            payment_details = payment_response['payment']
            
            # Prepare response
            response_data = {
                'success': True,
                'payment_status': {
                    'order_id': order.id,
                    'razorpay_order_id': order.razorpay_order_id,
                    'razorpay_payment_id': order.razorpay_payment_id,
                    'status': payment_details['status'],
                    'amount': payment_details['amount'] / 100,  # Convert to rupees
                    'currency': payment_details['currency'],
                    'method': payment_details['method'],
                    'created_at': payment_details['created_at'],
                    'captured': payment_details.get('captured', False),
                    'refund_status': payment_details.get('refund_status'),
                    'amount_refunded': payment_details.get('amount_refunded', 0) / 100 if payment_details.get('amount_refunded') else 0
                }
            }
            
            return Response(response_data, status=status.HTTP_200_OK)
            
        except Order.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Order not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        except Exception as e:
            logger.error(f"Error fetching payment status: {str(e)}")
            return Response({
                'success': False,
                'message': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def debug_razorpay_request(request):
    """Debug endpoint to check request format"""
    import json
    
    logger.info("=== DEBUG RAZORPAY REQUEST ===")
    logger.info(f"Request method: {request.method}")
    logger.info(f"Content type: {request.content_type}")
    logger.info(f"Request META: {dict(request.META)}")
    
    try:
        logger.info(f"Request body (raw): {request.body}")
        logger.info(f"Request data: {request.data}")
        logger.info(f"Request POST: {request.POST}")
        
        # Try to parse as JSON manually
        if request.body:
            try:
                parsed_json = json.loads(request.body.decode('utf-8'))
                logger.info(f"Manually parsed JSON: {parsed_json}")
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                logger.error(f"Raw body that failed: {request.body}")
        
        return Response({
            'success': True,
            'debug_info': {
                'content_type': request.content_type,
                'data': request.data,
                'body_length': len(request.body) if request.body else 0,
                'has_data': bool(request.data)
            }
        })
        
    except Exception as e:
        logger.error(f"Debug endpoint error: {e}")
        return Response({
            'success': False,
            'error': str(e)
        })


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def handle_razorpay_webhook(request):
    """Handle Razorpay webhook notifications"""
    try:
        # Get webhook signature
        webhook_signature = request.META.get('HTTP_X_RAZORPAY_SIGNATURE')
        
        if not webhook_signature:
            return Response({
                'success': False,
                'message': 'Missing webhook signature'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # TODO: Implement webhook signature verification
        # This would require storing webhook secret in settings
        
        webhook_body = request.data
        event_type = webhook_body.get('event')
        
        if event_type == 'payment.captured':
            # Handle payment capture event
            payment_entity = webhook_body.get('payload', {}).get('payment', {}).get('entity', {})
            
            if payment_entity:
                razorpay_payment_id = payment_entity.get('id')
                
                # Find order by payment ID
                try:
                    order = Order.objects.get(razorpay_payment_id=razorpay_payment_id)
                    
                    # Update order status if not already updated
                    if order.payment_status != 'completed':
                        with transaction.atomic():
                            order.payment_status = 'completed'
                            if order.status == 'pending':
                                order.status = 'confirmed'
                            order.save()
                            
                            OrderStatusHistory.objects.create(
                                order=order,
                                status='confirmed',
                                title='Payment Captured (Webhook)',
                                message=f'Payment captured via webhook. Payment ID: {razorpay_payment_id}',
                                location='Webhook',
                                change_source='webhook'
                            )
                    
                except Order.DoesNotExist:
                    logger.warning(f"Order not found for payment ID: {razorpay_payment_id}")
        
        elif event_type == 'payment.failed':
            # Handle payment failure
            payment_entity = webhook_body.get('payload', {}).get('payment', {}).get('entity', {})
            
            if payment_entity:
                razorpay_order_id = payment_entity.get('order_id')
                
                try:
                    order = Order.objects.get(razorpay_order_id=razorpay_order_id)
                    
                    with transaction.atomic():
                        order.payment_status = 'failed'
                        order.save()
                        
                        OrderStatusHistory.objects.create(
                            order=order,
                            status=order.status,
                            title='Payment Failed (Webhook)',
                            message='Payment failed via webhook notification',
                            location='Webhook',
                            change_source='webhook'
                        )
                
                except Order.DoesNotExist:
                    logger.warning(f"Order not found for order ID: {razorpay_order_id}")
        
        return Response({
            'success': True,
            'message': 'Webhook processed successfully'
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return Response({
            'success': False,
            'message': 'Internal server error'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class UpdateOrderShippingView(APIView):
    """Update order shipping charges before payment"""
    
    permission_classes = [permissions.IsAuthenticated]
    
    def patch(self, request, order_uuid):
        """Update shipping charges for an order"""
        try:
            order = Order.objects.get(uuid=order_uuid, user=request.user)
            
            # Check if order can be updated
            if order.payment_status == 'completed':
                return Response({
                    'success': False,
                    'message': 'Cannot update shipping for completed payment order'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get shipping data from request
            shipping_charges = request.data.get('shipping_charges')
            courier_name = request.data.get('courier_name', '')
            courier_id = request.data.get('courier_id', '')
            
            if shipping_charges is None:
                return Response({
                    'success': False,
                    'message': 'shipping_charges is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            try:
                shipping_charges = Decimal(str(shipping_charges))
                if shipping_charges < 0:
                    return Response({
                        'success': False,
                        'message': 'Shipping charges cannot be negative'
                    }, status=status.HTTP_400_BAD_REQUEST)
            except (ValueError, TypeError):
                return Response({
                    'success': False,
                    'message': 'Invalid shipping charges format'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Update order with new shipping charges
            with transaction.atomic():
                old_total = order.total_amount
                order.shipping_charges = shipping_charges
                order.total_amount = order.subtotal + order.shipping_charges + order.tax_amount - order.discount_amount
                
                # Store courier selection details
                if courier_name:
                    order.shiprocket_courier_name = courier_name
                if courier_id:
                    order.shiprocket_courier_id = courier_id
                    
                order.save()
                
                # Create status history
                OrderStatusHistory.objects.create(
                    order=order,
                    status=order.status,
                    title='Shipping Updated',
                    message=f'Shipping charges updated from ₹{old_total - order.subtotal - order.tax_amount + order.discount_amount:.2f} to ₹{shipping_charges:.2f}' + (f' for {courier_name}' if courier_name else ''),
                    location='Customer Selection',
                    change_source='customer'
                )
            
            return Response({
                'success': True,
                'message': 'Shipping charges updated successfully',
                'order': {
                    'id': order.id,
                    'uuid': str(order.uuid),
                    'subtotal': float(order.subtotal),
                    'shipping_charges': float(order.shipping_charges),
                    'tax_amount': float(order.tax_amount),
                    'discount_amount': float(order.discount_amount),
                    'total_amount': float(order.total_amount),
                    'courier_name': order.shiprocket_courier_name,
                    'courier_id': order.shiprocket_courier_id
                }
            })
            
        except Order.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Order not found'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error updating shipping charges: {str(e)}")
            return Response({
                'success': False,
                'message': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)