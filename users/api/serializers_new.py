from rest_framework import serializers
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError as DjangoValidationError
from ..models import CustomUser, OTP
import re


class PhoneRegistrationSerializer(serializers.Serializer):
    """Step 1: Phone number registration and verification"""
    mobile_number = serializers.CharField(max_length=15)
    
    def validate_mobile_number(self, value):
        cleaned_number = re.sub(r'[^\d+]', '', value)
        
        if not re.match(r'^\+?91?[6-9]\d{9}$', cleaned_number):
            raise serializers.ValidationError(
                "Please enter a valid Indian mobile number (10 digits starting with 6-9)"
            )
        
        if cleaned_number.startswith('+91'):
            cleaned_number = cleaned_number[3:]
        elif cleaned_number.startswith('91'):
            cleaned_number = cleaned_number[2:]
        
        if CustomUser.objects.filter(mobile_number=cleaned_number).exists():
            raise serializers.ValidationError("User with this mobile number already exists")
        
        return cleaned_number


class ProfileCompletionSerializer(serializers.ModelSerializer):
    """Step 2: Complete user profile after phone verification with optional Google/Facebook linking"""
    mobile_number = serializers.CharField(max_length=15, write_only=True)
    # Removed social token fields: linking should happen after profile completion via a dedicated endpoint
    
    class Meta:
        model = CustomUser
        fields = [
            'mobile_number', 'full_name', 'user_type', 'buyer_category', 'email',
            'address', 'city', 'state', 'pincode', 'latitude', 'longitude',
            # social linking removed from profile completion
        ]
        extra_kwargs = {
            'mobile_number': {'write_only': True, 'required': True},
            'full_name': {'required': True},
            'user_type': {'required': True},
            'address': {'required': True},
            'city': {'required': True},
            'state': {'required': True},
            'pincode': {'required': True},
            'latitude': {'required': True},
            'longitude': {'required': True},
            'email': {'required': False},
            # social linking removed from profile completion
        }
    
    def validate_mobile_number(self, value):
        cleaned_number = re.sub(r'[^\d+]', '', value)
        
        if not re.match(r'^\+?91?[6-9]\d{9}$', cleaned_number):
            raise serializers.ValidationError(
                "Please enter a valid Indian mobile number (10 digits starting with 6-9)"
            )
        
        if cleaned_number.startswith('+91'):
            cleaned_number = cleaned_number[3:]
        elif cleaned_number.startswith('91'):
            cleaned_number = cleaned_number[2:]
        
        return cleaned_number
    
    def validate_full_name(self, value):
        if len(value.strip()) < 2:
            raise serializers.ValidationError("Full name must be at least 2 characters long")
        return value.strip()
    
    def validate_pincode(self, value):
        if not re.match(r'^\d{6}$', value):
            raise serializers.ValidationError("Pincode must be 6 digits")
        return value
    
    def validate_email(self, value):
        if value and CustomUser.objects.filter(email=value).exists():
            raise serializers.ValidationError("User with this email already exists")
        return value
    
    def validate(self, attrs):
        user_type = attrs.get('user_type')
        buyer_category = attrs.get('buyer_category')
    # social tokens are not part of the profile completion payload
        # require latitude/longitude for all users
        latitude = attrs.get('latitude')
        longitude = attrs.get('longitude')
        if latitude is None or longitude is None:
            raise serializers.ValidationError({'latitude,longitude': 'Latitude and longitude are required'})
        try:
            if not (-90 <= float(latitude) <= 90) or not (-180 <= float(longitude) <= 180):
                raise serializers.ValidationError({'latitude,longitude': 'latitude must be -90..90 and longitude -180..180'})
        except (TypeError, ValueError):
            raise serializers.ValidationError({'latitude,longitude': 'invalid latitude/longitude'})

        if user_type == 'smart_buyer' and not buyer_category:
            raise serializers.ValidationError({
                'buyer_category': 'Smart Buyers must select a buyer category'
            })
        
        if user_type == 'smart_seller' and buyer_category:
            attrs['buyer_category'] = None
        
        # No social token validation here
        attrs.pop('mobile_number', None)
        
        return attrs
    
    def verify_google_token(self, token):
        """Verify Google access token and return user data"""
        try:
            import requests as http_requests
            
            # Get user info from Google
            response = http_requests.get(
                f'https://www.googleapis.com/oauth2/v1/userinfo?access_token={token}'
            )
            
            if response.status_code == 200:
                user_data = response.json()
                return {
                    'id': user_data.get('id'),
                    'email': user_data.get('email'),
                    'first_name': user_data.get('given_name', ''),
                    'last_name': user_data.get('family_name', ''),
                    'name': user_data.get('name', ''),
                    'picture': user_data.get('picture', ''),
                }
            return None
        except Exception:
            return None
    
    def verify_facebook_token(self, token):
        """Verify Facebook access token and return user data"""
        try:
            import requests as http_requests
            
            # Verify token with Facebook
            response = http_requests.get(
                f'https://graph.facebook.com/me?access_token={token}&fields=id,name,email,first_name,last_name,picture'
            )
            
            if response.status_code == 200:
                user_data = response.json()
                return {
                    'id': user_data.get('id'),
                    'email': user_data.get('email'),
                    'first_name': user_data.get('first_name', ''),
                    'last_name': user_data.get('last_name', ''),
                    'name': user_data.get('name', ''),
                    'picture': user_data.get('picture', {}).get('data', {}).get('url', ''),
                }
            return None
        except Exception:
            return None


class OTPRequestSerializer(serializers.Serializer):
    mobile_number = serializers.CharField(max_length=15)
    
    def validate_mobile_number(self, value):
        cleaned_number = re.sub(r'[^\d+]', '', value)
        
        if not re.match(r'^\+?91?[6-9]\d{9}$', cleaned_number):
            raise serializers.ValidationError(
                "Please enter a valid Indian mobile number"
            )
        
        if cleaned_number.startswith('+91'):
            cleaned_number = cleaned_number[3:]
        elif cleaned_number.startswith('91'):
            cleaned_number = cleaned_number[2:]
        
        return cleaned_number


class OTPVerificationSerializer(serializers.Serializer):
    mobile_number = serializers.CharField(max_length=15)
    otp_code = serializers.CharField(max_length=6)
    
    def validate_otp_code(self, value):
        if not re.match(r'^\d{6}$', value):
            raise serializers.ValidationError("OTP must be 6 digits")
        return value
    
    def validate(self, attrs):
        mobile_number = attrs.get('mobile_number')
        otp_code = attrs.get('otp_code')
        
        cleaned_number = re.sub(r'[^\d+]', '', mobile_number)
        if cleaned_number.startswith('+91'):
            cleaned_number = cleaned_number[3:]
        elif cleaned_number.startswith('91'):
            cleaned_number = cleaned_number[2:]
        
        attrs['mobile_number'] = cleaned_number
        
        try:
            otp = OTP.objects.filter(
                mobile_number=cleaned_number,
                otp_code=otp_code,
                is_verified=False
            ).latest('created_at')
            
            if otp.is_expired():
                raise serializers.ValidationError({
                    'otp_code': 'OTP has expired. Please request a new one.'
                })
            
            attrs['otp_instance'] = otp
            
        except OTP.DoesNotExist:
            raise serializers.ValidationError({
                'otp_code': 'Invalid OTP code'
            })
        
        return attrs


class PhoneLoginSerializer(serializers.Serializer):
    """Serializer for phone/OTP based login"""
    mobile_number = serializers.CharField(max_length=15)
    otp_code = serializers.CharField(max_length=6)
    
    def validate(self, attrs):
        mobile_number = attrs.get('mobile_number')
        otp_code = attrs.get('otp_code')
        
        cleaned_number = re.sub(r'[^\d+]', '', mobile_number)
        if cleaned_number.startswith('+91'):
            cleaned_number = cleaned_number[3:]
        elif cleaned_number.startswith('91'):
            cleaned_number = cleaned_number[2:]
        
        attrs['mobile_number'] = cleaned_number
        
        try:
            user = CustomUser.objects.get(mobile_number=cleaned_number)
            if not user.is_profile_complete:
                raise serializers.ValidationError({
                    'profile': 'Please complete your profile first'
                })
            # Prevent login for suspended / deactivated users
            if not user.is_active:
                raise serializers.ValidationError({
                    'account': 'This account has been suspended'
                })
            attrs['user'] = user
        except CustomUser.DoesNotExist:
            raise serializers.ValidationError({
                'mobile_number': 'User with this mobile number does not exist'
            })
        
        try:
            otp = OTP.objects.filter(
                mobile_number=cleaned_number,
                otp_code=otp_code,
                is_verified=False
            ).latest('created_at')
            
            if otp.is_expired():
                raise serializers.ValidationError({
                    'otp_code': 'OTP has expired. Please request a new one.'
                })
            
            attrs['otp_instance'] = otp
            
        except OTP.DoesNotExist:
            raise serializers.ValidationError({
                'otp_code': 'Invalid OTP code'
            })
        
        return attrs


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = [
            'id', 'mobile_number', 'full_name', 'email', 'user_type', 
            'buyer_category', 'registration_method', 'is_mobile_verified', 
            'is_profile_complete', 'profile_picture',
            'address', 'city', 'state', 'pincode', 'latitude', 'longitude',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'mobile_number', 'user_type', 'registration_method', 
            'is_mobile_verified', 'is_profile_complete', 'created_at', 'updated_at'
        ]
    
    def validate_buyer_category(self, value):
        user = self.instance
        if user and user.user_type == 'smart_seller' and value:
            raise serializers.ValidationError("Smart Sellers cannot have a buyer category")
        return value


class UserListSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = [
            'id', 'mobile_number', 'full_name', 'email', 'user_type', 'buyer_category',
            'registration_method', 'is_mobile_verified', 'is_profile_complete', 
            'is_active', 'city', 'state', 'created_at'
        ]