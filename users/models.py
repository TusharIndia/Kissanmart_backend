from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from datetime import timedelta
import random
import string

class CustomUser(AbstractUser):
    USER_TYPE_CHOICES = [
        ('smart_seller', 'Smart Seller (Farmer)'),
        ('smart_buyer', 'Smart Buyer'),
    ]
    
    BUYER_CATEGORY_CHOICES = [
        ('mandi_owner', 'Mandi Owner'),
        ('shopkeeper', 'Shopkeeper'),
        ('community', 'Community'),
    ]
    
    REGISTRATION_METHOD_CHOICES = [
        ('phone', 'Phone Number'),
        ('google', 'Google Account'),
        ('facebook', 'Facebook Account'),
    ]
    
    username = None
    
    mobile_number = models.CharField(max_length=15, unique=True, null=True, blank=True)
    full_name = models.CharField(max_length=255, blank=True, default='')
    user_type = models.CharField(max_length=20, choices=USER_TYPE_CHOICES, blank=True, default='')
    
    buyer_category = models.CharField(
        max_length=20, 
        choices=BUYER_CATEGORY_CHOICES, 
        null=True, 
        blank=True
    )
    
    # Registration method tracking
    registration_method = models.CharField(
        max_length=20, 
        choices=REGISTRATION_METHOD_CHOICES, 
        default='phone'
    )
    
    # Social authentication fields
    google_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    facebook_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    
    # Verification fields
    is_mobile_verified = models.BooleanField(default=False)
    is_profile_complete = models.BooleanField(default=False)
    
    # Profile fields
    profile_picture = models.ImageField(upload_to='profile_pics/', null=True, blank=True)
    
    # Address fields - temporarily nullable for migration, will be required in serializers
    address = models.TextField(blank=True, default='')  
    city = models.CharField(max_length=100, default='')  
    state = models.CharField(max_length=100, blank=True, default='')  
    pincode = models.CharField(max_length=10, blank=True, default='')  
    
    # Location coordinates
    latitude = models.DecimalField(max_digits=9, decimal_places=6, default=0.0)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, default=0.0)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    USERNAME_FIELD = 'id'  # Changed temporarily for migration compatibility
    REQUIRED_FIELDS = []  # Temporarily empty for migration
    
    def __str__(self):
        return f"{self.full_name} ({self.get_identifier()})"
    
    def get_identifier(self):
        """Return the primary identifier for the user"""
        if self.mobile_number:
            return self.mobile_number
        return self.email
    
    def clean(self):
        from django.core.exceptions import ValidationError
        
        # Validate user type and buyer category combination
        if self.user_type == 'smart_buyer' and not self.buyer_category:
            raise ValidationError('Smart Buyers must have a buyer category')
        
        if self.user_type == 'smart_seller' and self.buyer_category:
            self.buyer_category = None
        
        # Validate registration method and required fields
        if self.registration_method == 'phone' and not self.mobile_number:
            raise ValidationError('Phone number is required for phone registration')
        
        if self.registration_method == 'google' and not self.google_id:
            raise ValidationError('Google ID is required for Google registration')
        
        if self.registration_method == 'facebook' and not self.facebook_id:
            raise ValidationError('Facebook ID is required for Facebook registration')
        
        # Ensure unique identifiers exist
        if not self.mobile_number and not self.email:
            raise ValidationError('Either mobile number or email is required')
    
    def save(self, *args, **kwargs):
        # Check if profile is complete
        self.is_profile_complete = all([
            self.full_name,
            self.user_type,
            self.address,
            self.city,
            self.state,
            self.pincode,
            self.latitude is not None,
            self.longitude is not None,
            # For smart buyers, buyer_category is also required
            not (self.user_type == 'smart_buyer' and not self.buyer_category)
        ])
        
        super().save(*args, **kwargs)


class OTP(models.Model):
    mobile_number = models.CharField(max_length=15)
    otp_code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    
    class Meta:
        ordering = ['-created_at']
    
    def save(self, *args, **kwargs):
        if not self.otp_code:
            self.otp_code = self.generate_otp()
        if not self.expires_at:
            from django.conf import settings
            expiry_minutes = getattr(settings, 'OTP_EXPIRY_MINUTES', 5)
            self.expires_at = timezone.now() + timedelta(minutes=expiry_minutes)
        super().save(*args, **kwargs)
    
    @staticmethod
    def generate_otp():
        return ''.join(random.choices(string.digits, k=6))
    
    def is_expired(self):
        return timezone.now() > self.expires_at
    
    def __str__(self):
        return f"OTP for {self.mobile_number} - {self.otp_code}"


class UserSession(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    session_token = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    
    def save(self, *args, **kwargs):
        if not self.session_token:
            self.session_token = self.generate_session_token()
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=30)
        super().save(*args, **kwargs)
    
    @staticmethod
    def generate_session_token():
        return ''.join(random.choices(string.ascii_letters + string.digits, k=64))
    
    def is_expired(self):
        return timezone.now() > self.expires_at
    
    def __str__(self):
        return f"Session for {self.user.mobile_number}"


class AdminActionLog(models.Model):
    """Record admin actions taken on user accounts for auditing."""
    ACTION_CHOICES = [
        ('view', 'View'),
        ('suspend', 'Suspend'),
        ('delete', 'Delete'),
        ('other', 'Other'),
    ]

    admin_username = models.CharField(max_length=150, null=True, blank=True)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='admin_logs')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    details = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.action} by {self.admin_username} on {self.user.get_identifier()} at {self.created_at}"
