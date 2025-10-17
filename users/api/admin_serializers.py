from rest_framework import serializers
from ..models import CustomUser
from ..models import AdminActionLog


class AdminUserListSerializer(serializers.ModelSerializer):
    """Serializer for admin user listing - limited visible fields"""
    class Meta:
        model = CustomUser
        # Provide a comprehensive list view for admins (excluding password)
        fields = [
            'id', 'mobile_number', 'full_name', 'email', 'user_type', 'buyer_category',
            'registration_method', 'is_mobile_verified', 'is_profile_complete', 'is_active',
            'profile_picture', 'address', 'city', 'state', 'pincode', 'latitude', 'longitude',
            'created_at', 'updated_at', 'last_login', 'google_id', 'facebook_id'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'last_login']


class AdminUserDetailSerializer(serializers.ModelSerializer):
    """Serializer for admin user detail - limited visible fields"""
    class Meta:
        model = CustomUser
        # Provide full detail view for admins (excluding password)
        fields = [
            'id', 'mobile_number', 'full_name', 'email', 'user_type', 'buyer_category',
            'registration_method', 'is_mobile_verified', 'is_profile_complete', 'is_active',
            'profile_picture', 'address', 'city', 'state', 'pincode', 'latitude', 'longitude',
            'created_at', 'updated_at', 'last_login', 'google_id', 'facebook_id'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'last_login']


class AdminActionLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdminActionLog
        fields = ['id', 'admin_username', 'action', 'details', 'created_at']


class AdminUserUpdateSerializer(serializers.ModelSerializer):
    """Serializer used by admin to update allowed fields only"""
    class Meta:
        model = CustomUser
        fields = ['full_name', 'email', 'address', 'city', 'state']

    def validate_email(self, value):
        if value:
            qs = CustomUser.objects.filter(email=value)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError('User with this email already exists')
        return value
