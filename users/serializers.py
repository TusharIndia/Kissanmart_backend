from rest_framework import serializers
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import CustomUser, OTP
import re


class UserRegistrationSerializer(serializers.ModelSerializer):
    confirm_password = serializers.CharField(write_only=True, required=False)
    
    class Meta:
        model = CustomUser
        fields = [
            'mobile_number', 'full_name', 'user_type', 'buyer_category',
            'email', 'password', 'confirm_password', 'address', 'city', 
            'state', 'pincode', 'latitude', 'longitude'
        ]
        extra_kwargs = {
            'password': {'write_only': True, 'required': False},
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
        
        if CustomUser.objects.filter(mobile_number=cleaned_number).exists():
            raise serializers.ValidationError("User with this mobile number already exists")
        
        return cleaned_number
    
    def validate_full_name(self, value):
        if len(value.strip()) < 2:
            raise serializers.ValidationError("Full name must be at least 2 characters long")
        return value.strip()
    
    def validate(self, attrs):
        user_type = attrs.get('user_type')
        buyer_category = attrs.get('buyer_category')
        
        if user_type == 'smart_buyer' and not buyer_category:
            raise serializers.ValidationError({
                'buyer_category': 'Smart Buyers must select a buyer category'
            })
        
        if user_type == 'smart_seller' and buyer_category:
            attrs['buyer_category'] = None
        
        password = attrs.get('password')
        confirm_password = attrs.get('confirm_password')
        
        if password and confirm_password:
            if password != confirm_password:
                raise serializers.ValidationError({
                    'confirm_password': 'Passwords do not match'
                })
        
        return attrs
    
    def create(self, validated_data):
        validated_data.pop('confirm_password', None)
        password = validated_data.pop('password', None)
        
        user = CustomUser(**validated_data)
        
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        
        user.save()
        return user


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


class UserLoginSerializer(serializers.Serializer):
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
            'buyer_category', 'is_mobile_verified', 'profile_picture',
            'address', 'city', 'state', 'pincode', 'latitude', 'longitude',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'mobile_number', 'user_type', 'is_mobile_verified', 'created_at', 'updated_at']
    
    def validate_buyer_category(self, value):
        user = self.instance
        if user and user.user_type == 'smart_seller' and value:
            raise serializers.ValidationError("Smart Sellers cannot have a buyer category")
        return value


class UserListSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = [
            'id', 'mobile_number', 'full_name', 'user_type', 'buyer_category',
            'is_mobile_verified', 'is_active', 'city', 'state', 'created_at'
        ]
