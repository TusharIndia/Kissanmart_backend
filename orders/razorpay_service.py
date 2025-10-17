"""
Razorpay payment service for handling payment gateway operations
"""

import razorpay
import hmac
import hashlib
from django.conf import settings
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class RazorpayService:
    """Service class for Razorpay payment gateway operations"""
    
    def __init__(self):
        """Initialize Razorpay client with API credentials"""
        self.client = razorpay.Client(
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        )
    
    def create_order(self, amount, currency='INR', receipt=None, notes=None):
        """
        Create a Razorpay order
        
        Args:
            amount (Decimal): Order amount in the smallest currency unit (paise for INR)
            currency (str): Currency code (default: INR)
            receipt (str): Receipt ID for tracking
            notes (dict): Additional notes/metadata
            
        Returns:
            dict: Razorpay order response
        """
        try:
            # Convert amount to paise (smallest unit for INR)
            amount_in_paise = int(amount * 100)
            
            order_data = {
                'amount': amount_in_paise,
                'currency': currency,
                'payment_capture': 1  # Auto capture payment
            }
            
            if receipt:
                order_data['receipt'] = receipt
            
            if notes:
                order_data['notes'] = notes
            
            logger.info(f"Creating Razorpay order with data: {order_data}")
            
            order = self.client.order.create(data=order_data)
            
            logger.info(f"Razorpay order created successfully: {order['id']}")
            
            return {
                'success': True,
                'order': order
            }
            
        except Exception as e:
            logger.error(f"Error creating Razorpay order: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def verify_payment_signature(self, razorpay_order_id, razorpay_payment_id, razorpay_signature):
        """
        Verify Razorpay payment signature
        
        Args:
            razorpay_order_id (str): Razorpay order ID
            razorpay_payment_id (str): Razorpay payment ID
            razorpay_signature (str): Payment signature to verify
            
        Returns:
            bool: True if signature is valid, False otherwise
        """
        try:
            # Generate expected signature
            body = razorpay_order_id + "|" + razorpay_payment_id
            expected_signature = hmac.new(
                key=settings.RAZORPAY_KEY_SECRET.encode('utf-8'),
                msg=body.encode('utf-8'),
                digestmod=hashlib.sha256
            ).hexdigest()
            
            # Compare signatures
            is_valid = hmac.compare_digest(expected_signature, razorpay_signature)
            
            if is_valid:
                logger.info(f"Payment signature verified successfully for order: {razorpay_order_id}")
            else:
                logger.warning(f"Payment signature verification failed for order: {razorpay_order_id}")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"Error verifying payment signature: {str(e)}")
            return False
    
    def fetch_payment(self, payment_id):
        """
        Fetch payment details from Razorpay
        
        Args:
            payment_id (str): Razorpay payment ID
            
        Returns:
            dict: Payment details or error
        """
        try:
            payment = self.client.payment.fetch(payment_id)
            
            logger.info(f"Payment details fetched successfully: {payment_id}")
            logger.debug(f"Raw payment response: {payment}")
            
            # Ensure the payment object is JSON serializable
            if hasattr(payment, 'json'):
                payment_data = payment.json()
            elif isinstance(payment, dict):
                payment_data = payment
            else:
                # Convert to dict if it's a different type
                payment_data = dict(payment) if hasattr(payment, '__iter__') else {'raw_response': str(payment)}
            
            return {
                'success': True,
                'payment': payment_data
            }
            
        except Exception as e:
            logger.error(f"Error fetching payment details: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def refund_payment(self, payment_id, amount=None, notes=None):
        """
        Create a refund for a payment
        
        Args:
            payment_id (str): Razorpay payment ID
            amount (int): Refund amount in paise (if None, full refund)
            notes (dict): Additional notes for the refund
            
        Returns:
            dict: Refund response or error
        """
        try:
            refund_data = {}
            
            if amount:
                refund_data['amount'] = amount
            
            if notes:
                refund_data['notes'] = notes
            
            refund = self.client.payment.refund(payment_id, refund_data)
            
            logger.info(f"Refund created successfully: {refund['id']}")
            
            return {
                'success': True,
                'refund': refund
            }
            
        except Exception as e:
            logger.error(f"Error creating refund: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def capture_payment(self, payment_id, amount):
        """
        Capture a payment (for manual capture mode)
        
        Args:
            payment_id (str): Razorpay payment ID
            amount (int): Amount to capture in paise
            
        Returns:
            dict: Capture response or error
        """
        try:
            capture_data = {
                'amount': amount,
                'currency': 'INR'
            }
            
            payment = self.client.payment.capture(payment_id, capture_data)
            
            logger.info(f"Payment captured successfully: {payment_id}")
            
            return {
                'success': True,
                'payment': payment
            }
            
        except Exception as e:
            logger.error(f"Error capturing payment: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }