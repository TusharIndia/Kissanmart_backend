from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from .api.views import (
    # OTP and Phone Verification
    SendOTPView, VerifyPhoneRegistrationView,
    
    # Registration Flow
    CompleteProfileView, CompleteProfileWithSocialView, QuickRoleRegistrationView,
    
    # Login Options
    PhoneLoginView,
    
    # User Management
    UserLogoutView, UserProfileView, CurrentUserView, CheckUserExistsView, CheckRoleAvailabilityView,
    user_dashboard, user_statistics
    , OAuthCallbackView, OAuthTokenView
    , weather_view
    , LinkSocialView
    
    # Contact Query
    , ContactQueryCreateView, ContactQueryListView, ContactQueryDeleteView
    
    # Image Upload
    , UploadImageToDriveView
    
)

app_name = 'users'

urlpatterns = [
    # REGISTRATION FLOW (Step by step)
    # Step 1: Send OTP to phone number
    path('send-otp/', SendOTPView.as_view(), name='send_otp'),
    # Step 2: Verify OTP and create account
    path('verify-phone-registration/', VerifyPhoneRegistrationView.as_view(), name='verify_phone_registration'),
    # Step 3: Complete profile
    path('complete-profile/', CompleteProfileView.as_view(), name='complete_profile'),
    # Step 3b: Complete profile with social account linking
    path('complete-profile-with-social/', CompleteProfileWithSocialView.as_view(), name='complete_profile_with_social'),
    # Quick role registration using existing profile
    path('quick-role-registration/', QuickRoleRegistrationView.as_view(), name='quick_role_registration'),
    
    # LOGIN OPTIONS
    path('login/phone/', PhoneLoginView.as_view(), name='phone_login'),
    path('logout/', UserLogoutView.as_view(), name='logout'),
    
    # USER MANAGEMENT
    path('profile/', UserProfileView.as_view(), name='profile'),
    path('current-user/', CurrentUserView.as_view(), name='current_user'),
    path('dashboard/', user_dashboard, name='dashboard'),
    
    # UTILITY ENDPOINTS
    path('check-user/', CheckUserExistsView.as_view(), name='check_user'),
    path('check-roles/', CheckRoleAvailabilityView.as_view(), name='check_roles'),
    path('statistics/', user_statistics, name='statistics'),
    path('weather/', weather_view, name='weather'),
    
    # CONTACT QUERY ENDPOINTS
    path('contact/', ContactQueryCreateView.as_view(), name='contact_create'),
    path('contact/queries/', ContactQueryListView.as_view(), name='contact_list'),
    path('contact/queries/<int:query_id>/delete/', ContactQueryDeleteView.as_view(), name='contact_delete'),
    
    # IMAGE UPLOAD ENDPOINT
    path('upload-image/', UploadImageToDriveView.as_view(), name='upload_image'),
    
    # OAuth endpoints used by frontend
    path('auth/oauth/callback/', csrf_exempt(OAuthCallbackView.as_view()), name='oauth_callback'),
    path('auth/oauth/token/', csrf_exempt(OAuthTokenView.as_view()), name='oauth_token'),
    path('auth/oauth/link/', (LinkSocialView.as_view()), name='oauth_link'),
    # Admin APIs (simple env-based auth)
    # Imported below to avoid circular-import issues during app initialization
]

from .api import admin_views

urlpatterns += [
    path('admin/auth/', csrf_exempt(admin_views.AdminAuthView.as_view()), name='admin_auth'),
    path('admin/users/', admin_views.AdminUserListCreate.as_view(), name='admin_users_list_create'),
    path('admin/users/<int:id>/', admin_views.AdminUserRetrieveUpdateDelete.as_view(), name='admin_user_rud'),
    path('admin/users/<int:id>/suspend/', csrf_exempt(admin_views.AdminUserSuspendView.as_view()), name='admin_user_suspend'),
    path('admin/users/<int:id>/logs/', admin_views.AdminUserLogsView.as_view(), name='admin_user_logs'),
]

