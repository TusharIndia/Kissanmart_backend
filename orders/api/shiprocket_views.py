from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.utils import timezone
from decimal import Decimal
import logging

from ..models import Order, OrderStatusHistory
from services.shiprocket import get_shiprocket_service, ShiprocketAPIError

logger = logging.getLogger(__name__)


class CourierServiceabilityView(APIView):
    """
    Check courier serviceability and get available courier options
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        """
        Check serviceability for given pickup and delivery locations
        
        Expected payload:
        {
            "pickup_postcode": "110032",
            "delivery_postcode": "110002", 
            "weight": 1.5,
            "cod": false,
            "courier_type": 1
        }
        """
        try:
            # Validate required fields
            required_fields = ['pickup_postcode', 'delivery_postcode', 'weight']
            for field in required_fields:
                if field not in request.data:
                    return Response({
                        'success': False,
                        'message': f'Missing required field: {field}'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            pickup_postcode = request.data['pickup_postcode']
            delivery_postcode = request.data['delivery_postcode']
            weight = float(request.data['weight'])
            cod = request.data.get('cod', False)
            courier_type = request.data.get('courier_type', 1)
            
            # Check serviceability
            serviceability = get_shiprocket_service().check_serviceability(
                pickup_postcode=pickup_postcode,
                delivery_postcode=delivery_postcode,
                weight=weight,
                cod=cod,
                courier_type=courier_type
            )
            
            if not serviceability['serviceable']:
                return Response({
                    'success': False,
                    'message': 'Service not available for this location',
                    'pickup_postcode': pickup_postcode,
                    'delivery_postcode': delivery_postcode
                }, status=status.HTTP_200_OK)
            
            # Format response for frontend
            courier_options = []
            for courier in serviceability['couriers']:
                courier_options.append({
                    'id': courier['courier_company_id'],
                    'name': courier['courier_name'],
                    'charges': {
                        'freight': courier['freight_charge'],
                        'cod': courier['cod_charge'],
                        'other': courier['other_charges'],
                        'total': courier['total_charge']
                    },
                    'delivery': {
                        'estimated_days': courier['estimated_delivery_days'],
                        'cutoff_time': courier['cutoff_time']
                    },
                    'performance': {
                        'pickup': courier['pickup_performance'],
                        'delivery': courier['delivery_performance'],
                        'tracking': courier['tracking_performance']
                    },
                    'service_type': {
                        'is_surface': courier['is_surface'],
                        'is_express': courier['is_express'],
                        'cod_available': courier['cod_available']
                    }
                })
            
            # Find recommended option (cheapest among reliable ones)
            recommended_courier = None
            if courier_options:
                # Filter couriers with good performance (>80% for delivery)
                reliable_couriers = [c for c in courier_options if c['performance']['delivery'] >= 80]
                if reliable_couriers:
                    recommended_courier = min(reliable_couriers, key=lambda x: x['charges']['total'])
                else:
                    recommended_courier = min(courier_options, key=lambda x: x['charges']['total'])
            
            return Response({
                'success': True,
                'serviceable': True,
                'location': {
                    'pickup_postcode': pickup_postcode,
                    'delivery_postcode': delivery_postcode,
                    'weight': weight,
                    'cod': cod
                },
                'courier_options': courier_options,
                'recommended_courier': recommended_courier,
                'total_options': len(courier_options)
            })
            
        except ShiprocketAPIError as e:
            logger.error(f"Shiprocket serviceability check failed: {str(e)}")
            return Response({
                'success': False,
                'message': f'Serviceability check failed: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Unexpected error in serviceability check: {str(e)}")
            return Response({
                'success': False,
                'message': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CreateShiprocketOrderView(APIView):
    """
    Create order in Shiprocket after successful payment
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, order_uuid):
        """
        Create Shiprocket order for existing order
        
        Expected payload:
        {
            "courier_company_id": 123,
            "pickup_location": "Primary"
        }
        """
        try:
            # Get the order
            order = get_object_or_404(Order, uuid=order_uuid, user=request.user)
            
            # Validate order state
            if order.payment_status != 'completed':
                return Response({
                    'success': False,
                    'message': 'Order payment not completed. Cannot create shipping order.'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if order.shiprocket_order_id:
                return Response({
                    'success': False,
                    'message': 'Shiprocket order already created for this order',
                    'shiprocket_order_id': order.shiprocket_order_id
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get courier selection
            courier_company_id = request.data.get('courier_company_id')
            if not courier_company_id:
                return Response({
                    'success': False,
                    'message': 'courier_company_id is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Prepare order data for Shiprocket
            delivery_address = order.delivery_address
            
            # Format order items for Shiprocket
            shiprocket_items = []
            total_weight = Decimal('0')
            
            for item in order.items.all():
                shiprocket_items.append({
                    'name': item.product_name,
                    'sku': f"{item.product.uuid}" if hasattr(item.product, 'uuid') else f"PROD_{item.id}",
                    'units': int(item.quantity),
                    'selling_price': float(item.unit_price)
                })
                # Estimate weight (you might want to add weight field to Product model)
                total_weight += item.quantity * Decimal('0.5')  # 0.5kg per unit as default
            
            # Determine payment method for Shiprocket
            shiprocket_payment_method = "Prepaid"
            if order.payment_method == 'cod':
                shiprocket_payment_method = "COD"
            
            shiprocket_order_data = {
                'order_id': order.id,
                'order_date': order.order_date.strftime('%Y-%m-%d %H:%M'),
                'pickup_location': request.data.get('pickup_location', 'Primary'),
                'billing_customer_name': delivery_address.name.split()[0] if ' ' in delivery_address.name else delivery_address.name,
                'billing_last_name': ' '.join(delivery_address.name.split()[1:]) if ' ' in delivery_address.name else '',
                'billing_address': delivery_address.address_line_1,
                'billing_address_2': delivery_address.address_line_2 or '',
                'billing_city': delivery_address.city,
                'billing_pincode': delivery_address.pincode,
                'billing_state': delivery_address.state,
                'billing_country': 'India',
                'billing_phone': delivery_address.phone,
                'billing_email': delivery_address.email or order.customer_email,
                'shipping_is_billing': True,
                'order_items': shiprocket_items,
                'payment_method': shiprocket_payment_method,
                'sub_total': float(order.subtotal),
                'length': 15,  # Default dimensions - you might want to calculate based on products
                'breadth': 10,
                'height': 8,
                'weight': float(total_weight)
            }
            
            with transaction.atomic():
                # Create order in Shiprocket
                shiprocket_response = get_shiprocket_service().create_order(shiprocket_order_data)
                
                if not shiprocket_response['success']:
                    return Response({
                        'success': False,
                        'message': 'Failed to create Shiprocket order',
                        'error': shiprocket_response
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                # Update order with Shiprocket details
                order.shiprocket_order_id = shiprocket_response['shiprocket_order_id']
                order.shiprocket_shipment_id = shiprocket_response['shipment_id']
                order.shiprocket_status = shiprocket_response['status']
                order.shiprocket_response = shiprocket_response['raw_response']
                order.save()
                
                # Now assign courier
                if shiprocket_response['shipment_id']:
                    try:
                        courier_response = get_shiprocket_service().assign_courier(
                            shipment_id=int(shiprocket_response['shipment_id']),
                            courier_company_id=int(courier_company_id)
                        )
                        
                        if courier_response['success']:
                            order.shiprocket_awb_code = courier_response['awb_code']
                            order.shiprocket_courier_name = courier_response['courier_name']
                            order.shiprocket_courier_id = str(courier_company_id)
                            order.status = 'processing'  # Update order status
                            order.save()
                            
                            # Create status history
                            OrderStatusHistory.objects.create(
                                order=order,
                                status='processing',
                                title='Shipping Arranged',
                                message=f'Order assigned to {courier_response["courier_name"]} with AWB: {courier_response["awb_code"]}',
                                location='Shiprocket',
                                change_source='shiprocket'
                            )
                            
                    except Exception as courier_error:
                        logger.error(f"Courier assignment failed: {courier_error}")
                        # Order is created but courier assignment failed
                        pass
                
                return Response({
                    'success': True,
                    'message': 'Shiprocket order created successfully',
                    'order': {
                        'id': order.id,
                        'shiprocket_order_id': order.shiprocket_order_id,
                        'shipment_id': order.shiprocket_shipment_id,
                        'awb_code': order.shiprocket_awb_code,
                        'courier_name': order.shiprocket_courier_name,
                        'status': order.status
                    }
                })
                
        except ShiprocketAPIError as e:
            logger.error(f"Shiprocket order creation failed: {str(e)}")
            return Response({
                'success': False,
                'message': f'Shiprocket order creation failed: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Unexpected error in Shiprocket order creation: {str(e)}")
            return Response({
                'success': False,
                'message': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TrackShiprocketOrderView(APIView):
    """
    Track order using Shiprocket AWB code
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, order_uuid):
        """
        Get tracking information for order
        """
        try:
            order = get_object_or_404(Order, uuid=order_uuid, user=request.user)
            
            if not order.shiprocket_awb_code:
                return Response({
                    'success': False,
                    'message': 'No tracking information available. Order not yet shipped.'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Get tracking information from Shiprocket
            tracking_info = get_shiprocket_service().track_order(awb_code=order.shiprocket_awb_code)
            
            if not tracking_info['success']:
                return Response({
                    'success': False,
                    'message': 'Failed to get tracking information'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            return Response({
                'success': True,
                'order': {
                    'id': order.id,
                    'status': order.status,
                    'awb_code': order.shiprocket_awb_code,
                    'courier_name': order.shiprocket_courier_name
                },
                'tracking': {
                    'current_status': tracking_info['current_status'],
                    'delivered_date': tracking_info['delivered_date'],
                    'origin': tracking_info['origin'],
                    'destination': tracking_info['destination'],
                    'tracking_history': tracking_info['tracking_history']
                }
            })
            
        except ShiprocketAPIError as e:
            logger.error(f"Shiprocket tracking failed: {str(e)}")
            return Response({
                'success': False,
                'message': f'Tracking failed: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Unexpected error in tracking: {str(e)}")
            return Response({
                'success': False,
                'message': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CancelShiprocketOrderView(APIView):
    """
    Cancel order in Shiprocket
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, order_uuid):
        """
        Cancel Shiprocket order
        
        Expected payload:
        {
            "reason": "Customer requested cancellation"
        }
        """
        try:
            order = get_object_or_404(Order, uuid=order_uuid, user=request.user)
            
            if not order.shiprocket_order_id:
                return Response({
                    'success': False,
                    'message': 'No Shiprocket order found to cancel'
                }, status=status.HTTP_404_NOT_FOUND)
            
            if order.status in ['delivered', 'cancelled']:
                return Response({
                    'success': False,
                    'message': f'Order in {order.status} status cannot be cancelled'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            reason = request.data.get('reason', 'Customer requested cancellation')
            
            with transaction.atomic():
                # Cancel in Shiprocket
                cancel_response = get_shiprocket_service().cancel_order([int(order.shiprocket_order_id)])
                
                if cancel_response['success']:
                    # Update local order status
                    order.status = 'cancelled'
                    order.save()
                    
                    # Create status history
                    OrderStatusHistory.objects.create(
                        order=order,
                        status='cancelled',
                        title='Order Cancelled',
                        message=f'Order cancelled in Shiprocket. Reason: {reason}',
                        location='Shiprocket',
                        changed_by=request.user,
                        change_source='customer'
                    )
                    
                    # Restore product quantities
                    for item in order.items.all():
                        item.product.quantity_available += item.quantity
                        item.product.save()
                    
                    return Response({
                        'success': True,
                        'message': 'Order cancelled successfully',
                        'order': {
                            'id': order.id,
                            'status': order.status,
                            'shiprocket_message': cancel_response['message']
                        }
                    })
                else:
                    return Response({
                        'success': False,
                        'message': 'Failed to cancel order in Shiprocket',
                        'error': cancel_response
                    }, status=status.HTTP_400_BAD_REQUEST)
                
        except ShiprocketAPIError as e:
            logger.error(f"Shiprocket cancellation failed: {str(e)}")
            return Response({
                'success': False,
                'message': f'Cancellation failed: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Unexpected error in cancellation: {str(e)}")
            return Response({
                'success': False,
                'message': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ShippingCalculatorView(APIView):
    """
    Calculate shipping charges for given locations
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        """
        Calculate shipping charges
        
        Expected payload:
        {
            "pickup_postcode": "110032",
            "delivery_postcode": "110002",
            "weight": 1.5,
            "cod": false
        }
        """
        try:
            required_fields = ['pickup_postcode', 'delivery_postcode', 'weight']
            for field in required_fields:
                if field not in request.data:
                    return Response({
                        'success': False,
                        'message': f'Missing required field: {field}'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            pickup_postcode = request.data['pickup_postcode']
            delivery_postcode = request.data['delivery_postcode']
            weight = float(request.data['weight'])
            cod = request.data.get('cod', False)
            
            shipping_info = get_shiprocket_service().calculate_shipping_charges(
                pickup_postcode=pickup_postcode,
                delivery_postcode=delivery_postcode,
                weight=weight,
                cod=cod
            )
            
            if not shipping_info['serviceable']:
                return Response({
                    'success': False,
                    'message': 'Shipping not available for this location',
                    'serviceable': False
                })
            
            return Response({
                'success': True,
                'serviceable': True,
                'shipping': {
                    'cheapest': {
                        'courier_name': shipping_info['cheapest_option']['courier_name'],
                        'charges': shipping_info['cheapest_option']['total_charge'],
                        'delivery_days': shipping_info['cheapest_option']['estimated_delivery_days']
                    },
                    'fastest': {
                        'courier_name': shipping_info['fastest_option']['courier_name'],
                        'charges': shipping_info['fastest_option']['total_charge'],
                        'delivery_days': shipping_info['fastest_option']['estimated_delivery_days']
                    },
                    'recommended': {
                        'courier_name': shipping_info['recommended']['courier_name'],
                        'charges': shipping_info['recommended']['total_charge'],
                        'delivery_days': shipping_info['recommended']['estimated_delivery_days']
                    }
                }
            })
            
        except ShiprocketAPIError as e:
            logger.error(f"Shipping calculation failed: {str(e)}")
            return Response({
                'success': False,
                'message': f'Shipping calculation failed: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Unexpected error in shipping calculation: {str(e)}")
            return Response({
                'success': False,
                'message': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class OrderShippingCalculatorView(APIView):
    """
    Calculate shipping charges for a specific order
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, order_uuid):
        """
        Calculate shipping charges for an existing order
        
        Expected payload:
        {
            "delivery_postcode": "110002",
            "pickup_postcode": "110032" (optional, will use default if not provided)
        }
        """
        try:
            order = get_object_or_404(Order, uuid=order_uuid, user=request.user)
            
            # Get delivery postcode from request or order
            delivery_postcode = request.data.get('delivery_postcode')
            if not delivery_postcode:
                if order.delivery_address and order.delivery_address.pincode:
                    delivery_postcode = order.delivery_address.pincode
                else:
                    return Response({
                        'success': False,
                        'message': 'delivery_postcode is required'
                    }, status=status.HTTP_400_BAD_REQUEST)
            
            # Use pickup postcode from request or default
            pickup_postcode = request.data.get('pickup_postcode', '110032')  # Default pickup location
            
            # Calculate estimated weight from order items
            total_weight = Decimal('0')
            for item in order.items.all():
                # Estimate weight (0.5kg per unit as default)
                total_weight += item.quantity * Decimal('0.5')
            
            # Minimum weight of 0.5kg
            if total_weight < Decimal('0.5'):
                total_weight = Decimal('0.5')
            
            # Determine if COD
            is_cod = order.payment_method == 'cod'
            
            # Get shipping options
            shipping_info = get_shiprocket_service().calculate_shipping_charges(
                pickup_postcode=pickup_postcode,
                delivery_postcode=delivery_postcode,
                weight=float(total_weight),
                cod=is_cod
            )
            
            if not shipping_info['serviceable']:
                return Response({
                    'success': False,
                    'message': 'Shipping not available for this location',
                    'serviceable': False,
                    'order': {
                        'id': order.id,
                        'subtotal': float(order.subtotal),
                        'current_shipping': float(order.shipping_charges),
                        'current_total': float(order.total_amount)
                    }
                })
            
            # Format response with updated totals
            def calculate_total(shipping_charge):
                return float(order.subtotal + Decimal(str(shipping_charge)) + order.tax_amount - order.discount_amount)
            
            return Response({
                'success': True,
                'serviceable': True,
                'order': {
                    'id': order.id,
                    'uuid': str(order.uuid),
                    'subtotal': float(order.subtotal),
                    'tax_amount': float(order.tax_amount),
                    'discount_amount': float(order.discount_amount),
                    'current_shipping': float(order.shipping_charges),
                    'current_total': float(order.total_amount),
                    'weight': float(total_weight)
                },
                'shipping_options': {
                    'cheapest': {
                        'courier_name': shipping_info['cheapest_option']['courier_name'],
                        'courier_id': shipping_info['cheapest_option'].get('courier_company_id'),
                        'shipping_charges': shipping_info['cheapest_option']['total_charge'],
                        'new_total': calculate_total(shipping_info['cheapest_option']['total_charge']),
                        'delivery_days': shipping_info['cheapest_option']['estimated_delivery_days']
                    },
                    'fastest': {
                        'courier_name': shipping_info['fastest_option']['courier_name'],
                        'courier_id': shipping_info['fastest_option'].get('courier_company_id'),
                        'shipping_charges': shipping_info['fastest_option']['total_charge'],
                        'new_total': calculate_total(shipping_info['fastest_option']['total_charge']),
                        'delivery_days': shipping_info['fastest_option']['estimated_delivery_days']
                    },
                    'recommended': {
                        'courier_name': shipping_info['recommended']['courier_name'],
                        'courier_id': shipping_info['recommended'].get('courier_company_id'),
                        'shipping_charges': shipping_info['recommended']['total_charge'],
                        'new_total': calculate_total(shipping_info['recommended']['total_charge']),
                        'delivery_days': shipping_info['recommended']['estimated_delivery_days']
                    }
                }
            })
            
        except ShiprocketAPIError as e:
            logger.error(f"Order shipping calculation failed: {str(e)}")
            return Response({
                'success': False,
                'message': f'Shipping calculation failed: {str(e)}'
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Unexpected error in order shipping calculation: {str(e)}")
            return Response({
                'success': False,
                'message': 'Internal server error'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def pickup_locations(request):
    """
    Get available pickup locations
    """
    try:
        locations = get_shiprocket_service().get_pickup_locations()
        
        return Response({
            'success': True,
            'pickup_locations': locations
        })
        
    except ShiprocketAPIError as e:
        logger.error(f"Failed to get pickup locations: {str(e)}")
        return Response({
            'success': False,
            'message': f'Failed to get pickup locations: {str(e)}'
        }, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Unexpected error getting pickup locations: {str(e)}")
        return Response({
            'success': False,
            'message': 'Internal server error'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)