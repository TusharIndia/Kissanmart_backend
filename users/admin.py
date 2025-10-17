from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, OTP, UserSession

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ('mobile_number', 'full_name', 'user_type', 'buyer_category', 'is_mobile_verified', 'is_active', 'created_at')
    list_filter = ('user_type', 'buyer_category', 'is_mobile_verified', 'is_active', 'created_at')
    search_fields = ('mobile_number', 'full_name', 'email')
    ordering = ('-created_at',)
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('mobile_number', 'full_name', 'email', 'user_type', 'buyer_category')
        }),
        ('Verification Status', {
            'fields': ('is_mobile_verified', 'is_active', 'is_staff', 'is_superuser')
        }),
        ('Location Information', {
            'fields': ('address', 'city', 'state', 'pincode', 'latitude', 'longitude')
        }),
        ('Profile', {
            'fields': ('profile_picture',)
        }),
        ('Permissions', {
            'fields': ('groups', 'user_permissions'),
            'classes': ('collapse',)
        }),
        ('Important dates', {
            'fields': ('last_login', 'date_joined', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    add_fieldsets = (
        ('Basic Information', {
            'classes': ('wide',),
            'fields': ('mobile_number', 'full_name', 'user_type', 'buyer_category', 'password1', 'password2'),
        }),
    )
    
    readonly_fields = ('created_at', 'updated_at', 'date_joined', 'last_login')


@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    list_display = ('mobile_number', 'otp_code', 'is_verified', 'created_at', 'expires_at', 'is_expired_display')
    list_filter = ('is_verified', 'created_at')
    search_fields = ('mobile_number',)
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'is_expired_display')
    
    def is_expired_display(self, obj):
        return obj.is_expired()
    is_expired_display.short_description = 'Is Expired'
    is_expired_display.boolean = True


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'session_token_short', 'created_at', 'expires_at', 'is_active', 'is_expired_display')
    list_filter = ('is_active', 'created_at')
    search_fields = ('user__mobile_number', 'user__full_name')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'is_expired_display')
    
    def session_token_short(self, obj):
        return f"{obj.session_token[:10]}..."
    session_token_short.short_description = 'Session Token'
    
    def is_expired_display(self, obj):
        return obj.is_expired()
    is_expired_display.short_description = 'Is Expired'
    is_expired_display.boolean = True
