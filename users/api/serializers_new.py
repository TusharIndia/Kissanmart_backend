from rest_framework import serializers
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError as DjangoValidationError
from ..models import CustomUser, OTP, ContactQuery
import re


class PhoneRegistrationSerializer(serializers.Serializer):
    """Step 1: Phone number registration and verification - now supports multi-role"""
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
        
        # No longer check for existing users since we support multi-role
        # The role availability check will be done separately
        
        return cleaned_number


class ProfileCompletionSerializer(serializers.ModelSerializer):
    """Step 2: Complete user profile after phone verification - now supports multi-role validation"""
    mobile_number = serializers.CharField(max_length=15, write_only=True)
    
    class Meta:
        model = CustomUser
        fields = [
            'mobile_number', 'full_name', 'user_type', 'buyer_category', 'email',
            'address', 'city', 'state', 'pincode', 'latitude', 'longitude',
        ]
        extra_kwargs = {
            'mobile_number': {'write_only': True, 'required': True},
            'email': {'required': False},
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
        mobile_number = attrs.get('mobile_number')
        
        # Validate required fields that have defaults in the model
        required_fields = ['full_name', 'user_type', 'address', 'city', 'state', 'pincode']
        for field in required_fields:
            value = attrs.get(field)
            if not value or (isinstance(value, str) and not value.strip()):
                raise serializers.ValidationError({
                    field: f'{field.replace("_", " ").title()} is required'
                })
        
        # Require latitude/longitude for all users
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
        
        # Multi-role validation: Check if this specific role combination already exists
        if mobile_number and user_type:
            existing_query = CustomUser.objects.filter(
                mobile_number=mobile_number,
                user_type=user_type
            )
            
            if user_type == 'smart_buyer' and buyer_category:
                existing_query = existing_query.filter(buyer_category=buyer_category)
                
            if existing_query.exists():
                if user_type == 'smart_seller':
                    raise serializers.ValidationError({
                        'user_type': 'A Seller account with this mobile number already exists'
                    })
                else:
                    category_display = dict(CustomUser.BUYER_CATEGORY_CHOICES).get(buyer_category, buyer_category)
                    raise serializers.ValidationError({
                        'buyer_category': f'A Buyer ({category_display}) account with this mobile number already exists'
                    })
        
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
    """Serializer for phone/OTP based login - now supports multi-role selection"""
    mobile_number = serializers.CharField(max_length=15)
    otp_code = serializers.CharField(max_length=6)
    user_type = serializers.CharField(max_length=20, required=False)
    buyer_category = serializers.CharField(max_length=20, required=False)
    
    def validate(self, attrs):
        mobile_number = attrs.get('mobile_number')
        otp_code = attrs.get('otp_code')
        user_type = attrs.get('user_type')
        buyer_category = attrs.get('buyer_category')
        
        cleaned_number = re.sub(r'[^\d+]', '', mobile_number)
        if cleaned_number.startswith('+91'):
            cleaned_number = cleaned_number[3:]
        elif cleaned_number.startswith('91'):
            cleaned_number = cleaned_number[2:]
        
        attrs['mobile_number'] = cleaned_number
        
        # Get all users with this mobile number
        users = CustomUser.objects.filter(mobile_number=cleaned_number)
        
        if not users.exists():
            raise serializers.ValidationError({
                'mobile_number': 'No account found with this mobile number'
            })
        
        # If user_type and buyer_category are provided, find specific user
        target_user = None
        if user_type:
            if user_type == 'smart_seller':
                target_user = users.filter(user_type='smart_seller').first()
            elif user_type == 'smart_buyer' and buyer_category:
                target_user = users.filter(
                    user_type='smart_buyer', 
                    buyer_category=buyer_category
                ).first()
            
            if not target_user:
                if user_type == 'smart_seller':
                    raise serializers.ValidationError({
                        'user_type': 'No Seller account found with this mobile number'
                    })
                else:
                    category_display = dict(CustomUser.BUYER_CATEGORY_CHOICES).get(buyer_category, buyer_category)
                    raise serializers.ValidationError({
                        'buyer_category': f'No Buyer ({category_display}) account found with this mobile number'
                    })
        else:
            # If no specific role provided, check if there's only one account
            if users.count() == 1:
                target_user = users.first()
            else:
                # Multiple accounts exist, user must specify which role to login as
                available_roles = []
                for user in users:
                    if user.user_type == 'smart_seller':
                        available_roles.append({'type': 'smart_seller', 'category': None, 'display': 'Seller'})
                    elif user.user_type == 'smart_buyer':
                        category_display = dict(CustomUser.BUYER_CATEGORY_CHOICES).get(user.buyer_category, user.buyer_category)
                        available_roles.append({
                            'type': 'smart_buyer',
                            'category': user.buyer_category,
                            'display': f'Buyer ({category_display})'
                        })
                
                raise serializers.ValidationError({
                    'user_selection_required': 'Multiple accounts found. Please select which account to login to.',
                    'available_accounts': available_roles
                })
        
        if not target_user.is_profile_complete:
            raise serializers.ValidationError({
                'profile': 'Please complete your profile first'
            })
        
        # Prevent login for suspended / deactivated users
        if not target_user.is_active:
            raise serializers.ValidationError({
                'account': 'This account has been suspended'
            })
        
        attrs['user'] = target_user
        
        # Verify OTP
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


class ContactQuerySerializer(serializers.ModelSerializer):
    """Serializer for contact queries from visitors"""
    
    class Meta:
        model = ContactQuery
        fields = ['name', 'email', 'message']
    
    def validate_name(self, value):
        """Validate name field"""
        if len(value.strip()) < 2:
            raise serializers.ValidationError("Name must be at least 2 characters long")
        if len(value.strip()) > 255:
            raise serializers.ValidationError("Name must be less than 255 characters")
        return value.strip()
    
    def validate_email(self, value):
        """Validate email field"""
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, value):
            raise serializers.ValidationError("Please enter a valid email address")
        return value.lower()
    
    def validate_message(self, value):
        """Validate message field"""
        if len(value.strip()) < 10:
            raise serializers.ValidationError("Message must be at least 10 characters long")
        if len(value.strip()) > 2000:
            raise serializers.ValidationError("Message must be less than 2000 characters")
        return value.strip()


class ContactQueryListSerializer(serializers.ModelSerializer):
    """Serializer for listing contact queries (admin view)"""
    
    class Meta:
        model = ContactQuery
        fields = ['id', 'name', 'email', 'message', 'created_at', 'ip_address']
        read_only_fields = ['id', 'created_at', 'ip_address']


class RoleAvailabilitySerializer(serializers.Serializer):
    """Serializer for checking available roles for a mobile number"""
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