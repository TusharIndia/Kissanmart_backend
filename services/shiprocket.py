import requests
import json
import logging
from datetime import datetime, timedelta
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class ShiprocketAPIError(Exception):
    """Custom exception for Shiprocket API errors"""
    pass


class ShiprocketService:
    """
    Shiprocket API integration service
    Handles authentication, order creation, tracking, and courier management
    """
    
    BASE_URL = "https://apiv2.shiprocket.in/v1/external"
    TOKEN_CACHE_KEY = "shiprocket_auth_token"
    TOKEN_CACHE_TIMEOUT = 86400  # 24 hours
    
    def __init__(self):
        self.email = getattr(settings, 'SHIPROCKET_API_EMAIL', None)
        self.password = getattr(settings, 'SHIPROCKET_API_PASSWORD', None)
        
        if not self.email or not self.password:
            missing = []
            if not self.email:
                missing.append('SHIPROCKET_API_EMAIL')
            if not self.password:
                missing.append('SHIPROCKET_API_PASSWORD')
            raise ShiprocketAPIError(f"Shiprocket credentials not configured in settings: {', '.join(missing)}")
        
        self._token = None
    
    def get_auth_token(self) -> str:
        """
        Get or refresh authentication token
        Token is cached for 24 hours to avoid frequent API calls
        """
        # Try to get token from cache first
        token = cache.get(self.TOKEN_CACHE_KEY)
        if token:
            self._token = token
            return token
        
        # Generate new token
        auth_url = f"{self.BASE_URL}/auth/login"
        payload = {
            "email": self.email,
            "password": self.password
        }
        
        try:
            response = requests.post(auth_url, json=payload, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            token = data.get('token')
            
            if not token:
                raise ShiprocketAPIError("No token received from Shiprocket API")
            
            # Cache the token
            cache.set(self.TOKEN_CACHE_KEY, token, self.TOKEN_CACHE_TIMEOUT)
            self._token = token
            
            logger.info("Shiprocket authentication successful")
            return token
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Shiprocket authentication failed: {str(e)}")
            raise ShiprocketAPIError(f"Authentication failed: {str(e)}")
        except KeyError as e:
            logger.error(f"Invalid response format from Shiprocket auth: {str(e)}")
            raise ShiprocketAPIError("Invalid authentication response")
    
    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None, 
                     params: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Make authenticated request to Shiprocket API
        """
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        headers = {
            'Authorization': f'Bearer {self.get_auth_token()}',
            'Content-Type': 'application/json'
        }
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=headers, params=params, timeout=30)
            elif method.upper() == 'POST':
                response = requests.post(url, headers=headers, json=data, timeout=30)
            elif method.upper() == 'PUT':
                response = requests.put(url, headers=headers, json=data, timeout=30)
            elif method.upper() == 'DELETE':
                response = requests.delete(url, headers=headers, timeout=30)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            # Handle token expiration
            if response.status_code == 401:
                # Clear cached token and retry once
                cache.delete(self.TOKEN_CACHE_KEY)
                self._token = None
                headers['Authorization'] = f'Bearer {self.get_auth_token()}'
                
                # Retry the request
                if method.upper() == 'GET':
                    response = requests.get(url, headers=headers, params=params, timeout=30)
                elif method.upper() == 'POST':
                    response = requests.post(url, headers=headers, json=data, timeout=30)
                elif method.upper() == 'PUT':
                    response = requests.put(url, headers=headers, json=data, timeout=30)
                elif method.upper() == 'DELETE':
                    response = requests.delete(url, headers=headers, timeout=30)
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Shiprocket API request failed: {method} {url} - {str(e)}")
            raise ShiprocketAPIError(f"API request failed: {str(e)}")
    
    def check_serviceability(self, pickup_postcode: str, delivery_postcode: str, 
                           weight: float, cod: bool = False, courier_type: int = 1) -> Dict[str, Any]:
        """
        Check courier serviceability and get available options
        
        Args:
            pickup_postcode: Pickup location pincode
            delivery_postcode: Delivery location pincode  
            weight: Package weight in kg
            cod: Cash on delivery (True/False)
            courier_type: 1 for Surface, 2 for Express
        """
        params = {
            'pickup_postcode': pickup_postcode,
            'delivery_postcode': delivery_postcode,
            'weight': weight,
            'cod': 1 if cod else 0,
            'courier_type': courier_type
        }
        
        try:
            response = self._make_request('GET', 'courier/serviceability/', params=params)
            
            # Process and format courier options
            couriers = response.get('data', {}).get('available_courier_companies', [])
            
            formatted_couriers = []
            for courier in couriers:
                formatted_couriers.append({
                    'courier_company_id': courier.get('courier_company_id'),
                    'courier_name': courier.get('courier_name'),
                    'freight_charge': float(courier.get('freight_charge', 0)),
                    'cod_charge': float(courier.get('cod_charges', 0)),
                    'other_charges': float(courier.get('other_charges', 0)),
                    'total_charge': float(courier.get('rate', 0)),
                    'estimated_delivery_days': courier.get('estimated_delivery_days'),
                    'cutoff_time': courier.get('cutoff_time'),
                    'pickup_performance': courier.get('pickup_performance'),
                    'delivery_performance': courier.get('delivery_performance'),
                    'tracking_performance': courier.get('tracking_performance'),
                    'is_surface': courier.get('is_surface', True),
                    'is_express': courier.get('express', False),
                    'cod_available': courier.get('cod', False)
                })
            
            return {
                'serviceable': len(formatted_couriers) > 0,
                'couriers': formatted_couriers,
                'pickup_postcode': pickup_postcode,
                'delivery_postcode': delivery_postcode,
                'weight': weight,
                'cod': cod
            }
            
        except Exception as e:
            logger.error(f"Serviceability check failed: {str(e)}")
            raise ShiprocketAPIError(f"Serviceability check failed: {str(e)}")
    
    def create_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create order in Shiprocket
        
        Args:
            order_data: Order information dictionary
        """
        try:
            # Validate required fields
            required_fields = [
                'order_id', 'order_date', 'billing_customer_name', 'billing_address',
                'billing_city', 'billing_pincode', 'billing_state', 'billing_country',
                'billing_phone', 'order_items', 'payment_method', 'sub_total'
            ]
            
            for field in required_fields:
                if field not in order_data:
                    raise ShiprocketAPIError(f"Missing required field: {field}")
            
            # Set default values
            shiprocket_order = {
                'order_id': order_data['order_id'],
                'order_date': order_data['order_date'],
                'pickup_location': order_data.get('pickup_location', 'Primary'),
                'billing_customer_name': order_data['billing_customer_name'],
                'billing_last_name': order_data.get('billing_last_name', ''),
                'billing_address': order_data['billing_address'],
                'billing_address_2': order_data.get('billing_address_2', ''),
                'billing_city': order_data['billing_city'],
                'billing_pincode': int(order_data['billing_pincode']),
                'billing_state': order_data['billing_state'],
                'billing_country': order_data['billing_country'],
                'billing_phone': int(order_data['billing_phone']),
                'billing_email': order_data.get('billing_email', ''),
                'shipping_is_billing': order_data.get('shipping_is_billing', True),
                'order_items': order_data['order_items'],
                'payment_method': order_data['payment_method'],
                'sub_total': float(order_data['sub_total']),
                'length': float(order_data.get('length', 10)),
                'breadth': float(order_data.get('breadth', 15)),
                'height': float(order_data.get('height', 20)),
                'weight': float(order_data.get('weight', 0.5))
            }
            
            # Add shipping address if different from billing
            if not shiprocket_order['shipping_is_billing']:
                shipping_fields = [
                    'shipping_customer_name', 'shipping_last_name', 'shipping_address',
                    'shipping_address_2', 'shipping_city', 'shipping_pincode',
                    'shipping_state', 'shipping_country', 'shipping_phone', 'shipping_email'
                ]
                for field in shipping_fields:
                    if field in order_data:
                        shiprocket_order[field] = order_data[field]
            
            response = self._make_request('POST', 'orders/create/adhoc', shiprocket_order)
            
            return {
                'success': True,
                'shiprocket_order_id': response.get('order_id'),
                'channel_order_id': response.get('channel_order_id'),
                'shipment_id': response.get('shipment_id'),
                'status': response.get('status'),
                'status_code': response.get('status_code'),
                'awb_code': response.get('awb_code'),
                'courier_company_id': response.get('courier_company_id'),
                'courier_name': response.get('courier_name'),
                'raw_response': response
            }
            
        except Exception as e:
            logger.error(f"Order creation failed: {str(e)}")
            raise ShiprocketAPIError(f"Order creation failed: {str(e)}")
    
    def assign_courier(self, shipment_id: int, courier_company_id: int) -> Dict[str, Any]:
        """
        Assign courier to shipment
        
        Args:
            shipment_id: Shiprocket shipment ID
            courier_company_id: Selected courier company ID
        """
        payload = {
            'shipment_id': shipment_id,
            'courier_id': courier_company_id
        }
        
        try:
            response = self._make_request('POST', 'courier/assign/awb', payload)
            
            return {
                'success': True,
                'awb_code': response.get('awb_code'),
                'courier_name': response.get('courier_name'),
                'response': response
            }
            
        except Exception as e:
            logger.error(f"Courier assignment failed: {str(e)}")
            raise ShiprocketAPIError(f"Courier assignment failed: {str(e)}")
    
    def track_order(self, awb_code: str = None, shipment_id: int = None) -> Dict[str, Any]:
        """
        Track order by AWB code or shipment ID
        
        Args:
            awb_code: AWB tracking code
            shipment_id: Shiprocket shipment ID
        """
        if not awb_code and not shipment_id:
            raise ShiprocketAPIError("Either AWB code or shipment ID is required for tracking")
        
        params = {}
        if awb_code:
            params['awb_code'] = awb_code
        if shipment_id:
            params['shipment_id'] = shipment_id
        
        try:
            response = self._make_request('GET', 'courier/track', params=params)
            
            tracking_data = response.get('tracking_data', {})
            shipment_track = tracking_data.get('shipment_track', [])
            
            # Format tracking information
            formatted_tracking = []
            for track in shipment_track:
                formatted_tracking.append({
                    'date': track.get('date'),
                    'status': track.get('status'),
                    'activity': track.get('activity'),
                    'location': track.get('location'),
                    'sr_status_label': track.get('sr_status_label')
                })
            
            return {
                'success': True,
                'awb_code': tracking_data.get('awb_code'),
                'courier_name': tracking_data.get('courier_name'),
                'current_status': tracking_data.get('current_status'),
                'delivered_date': tracking_data.get('delivered_date'),
                'destination': tracking_data.get('destination'),
                'origin': tracking_data.get('origin'),
                'tracking_history': formatted_tracking,
                'raw_response': response
            }
            
        except Exception as e:
            logger.error(f"Order tracking failed: {str(e)}")
            raise ShiprocketAPIError(f"Order tracking failed: {str(e)}")
    
    def cancel_order(self, order_ids: List[int]) -> Dict[str, Any]:
        """
        Cancel orders in Shiprocket
        
        Args:
            order_ids: List of Shiprocket order IDs to cancel
        """
        payload = {
            'ids': [str(order_id) for order_id in order_ids]
        }
        
        try:
            response = self._make_request('POST', 'orders/cancel', payload)
            
            return {
                'success': True,
                'message': response.get('message', 'Orders cancelled successfully'),
                'status_code': response.get('status_code'),
                'response': response
            }
            
        except Exception as e:
            logger.error(f"Order cancellation failed: {str(e)}")
            raise ShiprocketAPIError(f"Order cancellation failed: {str(e)}")
    
    def get_order_details(self, order_id: str) -> Dict[str, Any]:
        """
        Get order details from Shiprocket
        
        Args:
            order_id: Channel order ID (our order ID)
        """
        params = {
            'channel_order_id': order_id
        }
        
        try:
            response = self._make_request('GET', 'orders/show', params=params)
            
            return {
                'success': True,
                'order_data': response.get('data'),
                'response': response
            }
            
        except Exception as e:
            logger.error(f"Failed to get order details: {str(e)}")
            raise ShiprocketAPIError(f"Failed to get order details: {str(e)}")
    
    def get_pickup_locations(self) -> List[Dict[str, Any]]:
        """
        Get all pickup locations
        """
        try:
            response = self._make_request('GET', 'settings/company/pickup')
            
            # Debug the response
            logger.debug(f"Pickup locations response: {response}")
            
            pickup_locations = []
            data = response.get('data', [])
            
            # Handle case where data might be a string or different format
            if isinstance(data, str):
                logger.warning("Pickup locations data is a string, parsing as JSON")
                import json
                data = json.loads(data)
            
            # If response format is different, handle it
            if isinstance(data, dict):
                data = [data]  # Convert single location to list
            
            for location in data:
                if isinstance(location, dict):
                    pickup_locations.append({
                        'pickup_id': location.get('id'),
                        'pickup_location': location.get('pickup_location'),
                        'name': location.get('name'),
                        'email': location.get('email'),
                        'phone': location.get('phone'),
                        'address': location.get('address'),
                        'address_2': location.get('address_2'),
                        'city': location.get('city'),
                        'state': location.get('state'),
                        'country': location.get('country'),
                        'pin_code': location.get('pin_code'),
                        'is_primary': location.get('pickup_location') == 'Primary'
                    })
            
            return pickup_locations
            
        except Exception as e:
            logger.error(f"Failed to get pickup locations: {str(e)}")
            raise ShiprocketAPIError(f"Failed to get pickup locations: {str(e)}")
    
    def calculate_shipping_charges(self, pickup_postcode: str, delivery_postcode: str,
                                 weight: float, cod: bool = False) -> Dict[str, Any]:
        """
        Calculate shipping charges for different courier options
        """
        try:
            serviceability = self.check_serviceability(
                pickup_postcode=pickup_postcode,
                delivery_postcode=delivery_postcode,
                weight=weight,
                cod=cod
            )
            
            if not serviceability['serviceable']:
                return {
                    'serviceable': False,
                    'message': 'Service not available for this location'
                }
            
            # Get the cheapest option
            couriers = serviceability['couriers']
            cheapest = min(couriers, key=lambda x: x['total_charge'])
            fastest = min(couriers, key=lambda x: int(x['estimated_delivery_days'] or 999))
            
            return {
                'serviceable': True,
                'cheapest_option': cheapest,
                'fastest_option': fastest,
                'all_options': couriers,
                'recommended': cheapest if cheapest['total_charge'] <= fastest['total_charge'] * 1.2 else fastest
            }
            
        except Exception as e:
            logger.error(f"Failed to calculate shipping charges: {str(e)}")
            raise ShiprocketAPIError(f"Failed to calculate shipping charges: {str(e)}")


# Singleton instance with lazy initialization
_shiprocket_service_instance = None

def get_shiprocket_service():
    """
    Get the Shiprocket service instance with lazy initialization
    """
    global _shiprocket_service_instance
    if _shiprocket_service_instance is None:
        _shiprocket_service_instance = ShiprocketService()
    return _shiprocket_service_instance

# For backward compatibility
def get_shiprocket_service_instance():
    return get_shiprocket_service()

# Legacy attribute for backward compatibility
shiprocket_service = None