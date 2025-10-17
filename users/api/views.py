from rest_framework import status, generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.authtoken.models import Token
from django.contrib.auth import login
from django.utils import timezone
from django.conf import settings
import logging
from rest_framework import status, generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.authtoken.models import Token
from django.contrib.auth import login
from django.utils import timezone
from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse
from django.http import JsonResponse
import logging
import requests
import json
import secrets
import base64
import hashlib
import urllib.parse

from django.views.decorators.csrf import csrf_exempt

from django.conf import settings

from ..models import CustomUser, OTP, UserSession, ContactQuery
from .serializers_new import (
    PhoneRegistrationSerializer,
    ProfileCompletionSerializer,
    OTPRequestSerializer,
    OTPVerificationSerializer,
    PhoneLoginSerializer,
    UserProfileSerializer,
    UserListSerializer,
    ContactQuerySerializer,
    ContactQueryListSerializer
)
from drf_spectacular.utils import extend_schema

logger = logging.getLogger(__name__)


# REGISTRATION FLOW
@extend_schema(request=OTPRequestSerializer, responses={200: dict})
class SendOTPView(APIView):
    """Step 1: Send OTP for phone registration or login"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = OTPRequestSerializer(data=request.data)
        
        if serializer.is_valid():
            mobile_number = serializer.validated_data['mobile_number']
            otp = OTP.objects.create(mobile_number=mobile_number)
            
            sms_sent = self.send_sms(mobile_number, otp.otp_code)
            
            if sms_sent:
                return Response({
                    'success': True,
                    'message': f'OTP sent successfully to {mobile_number}',
                    'expires_in_minutes': getattr(settings, 'OTP_EXPIRY_MINUTES', 10)
                }, status=status.HTTP_200_OK)
            else:
                return Response({
                    'success': False,
                    'message': 'Failed to send OTP. Please try again.'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)
    
    def send_sms(self, mobile_number, otp_code):
        try:
            # Use MSG91 flow API to send OTP. Settings pulled from Django settings.
            from django.conf import settings

            otp_url = getattr(settings, 'OTP_URL', 'https://control.msg91.com/api/v5/flow/')
            flow_id = getattr(settings, 'OTP_FLOW_ID', None)
            sender = getattr(settings, 'OTP_SENDER_ID', None)
            auth_key = getattr(settings, 'OTP_AUTH_KEY', None)

            # Ensure number is in expected format (without +), msg91 expects country code prefixed
            cleaned = mobile_number
            if cleaned.startswith('+'):
                cleaned = cleaned[1:]
            # If number is 10 digits, prefix with 91
            if len(cleaned) == 10:
                cleaned = '91' + cleaned

            headers = {
                'authkey': auth_key or '',
                'Content-Type': 'application/json'
            }

            payload = {
                'flow_id': flow_id,
                'sender': sender,
                'mobiles': cleaned,
                'var1': otp_code
            }

            # Log payload (avoid logging sensitive keys in production)
            logger.info(f"Sending OTP via MSG91 to {cleaned}")

            resp = requests.post(otp_url, headers=headers, json=payload, timeout=10)

            if resp.status_code in (200, 201):
                logger.info(f"MSG91 response: {resp.status_code} - {resp.text}")
                return True
            else:
                logger.error(f"MSG91 failed: {resp.status_code} - {resp.text}")
                return False
        except Exception as e:
            logger.error(f"SMS sending failed: {str(e)}")
            return False


@extend_schema(request=OTPVerificationSerializer, responses={200: dict})
class VerifyPhoneRegistrationView(APIView):
    """Step 2: Verify phone number and create basic user account"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = OTPVerificationSerializer(data=request.data)
        
        if serializer.is_valid():
            otp_instance = serializer.validated_data['otp_instance']
            mobile_number = serializer.validated_data['mobile_number']
            
            # Check if user already exists
            existing_user = CustomUser.objects.filter(mobile_number=mobile_number).first()
            if existing_user:
                if existing_user.is_profile_complete:
                    return Response({
                        'success': False,
                        'message': 'User with this mobile number already exists. Please login instead.'
                    }, status=status.HTTP_400_BAD_REQUEST)
                else:
                    # User exists but profile incomplete - just mark OTP as verified and return
                    otp_instance.is_verified = True
                    otp_instance.save()
                    try:
                        otp_instance.delete()
                    except Exception:
                        logger.exception('Failed to delete OTP instance after verification')
                    
                    return Response({
                        'success': True,
                        'message': 'Phone number verified successfully. Please complete your profile.',
                        'user_id': existing_user.id,
                        'mobile_number': mobile_number,
                        'next_step': 'complete_profile',
                        'profile_complete': False
                    }, status=status.HTTP_200_OK)
            
            # Mark OTP as verified
            otp_instance.is_verified = True
            otp_instance.save()
            # Remove the OTP record after successful verification to prevent reuse
            try:
                otp_instance.delete()
            except Exception:
                logger.exception('Failed to delete OTP instance after verification')
            
            # Create incomplete user account
            user = CustomUser.objects.create(
                mobile_number=mobile_number,
                registration_method='phone',
                is_mobile_verified=True,
                # These fields are empty and will be required in next step
                full_name='',
                user_type='',
                address='',
                city='',
                state='',
                pincode=''
            )
            user.set_unusable_password()
            user.save()
            
            return Response({
                'success': True,
                'message': 'Phone number verified successfully. Please complete your profile.',
                'user_id': user.id,
                'mobile_number': mobile_number,
                'next_step': 'complete_profile',
                'profile_complete': False
            }, status=status.HTTP_200_OK)
        
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(request=ProfileCompletionSerializer, responses={200: dict})
class CompleteProfileView(APIView):
    """Step 3: Complete user profile after phone verification"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        mobile_number = request.data.get('mobile_number')
        
        if not mobile_number:
            return Response({
                'success': False,
                'message': 'Mobile number is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Clean and validate mobile number format
        import re
        cleaned_number = re.sub(r'[^\d+]', '', mobile_number)
        if cleaned_number.startswith('+91'):
            cleaned_number = cleaned_number[3:]
        elif cleaned_number.startswith('91'):
            cleaned_number = cleaned_number[2:]
        
        try:
            user = CustomUser.objects.get(mobile_number=cleaned_number)
        except CustomUser.DoesNotExist:
            return Response({
                'success': False,
                'message': 'User with this mobile number does not exist'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Check if mobile number is verified
        if not user.is_mobile_verified:
            return Response({
                'success': False,
                'message': 'Please verify your mobile number first'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if profile is already complete
        if user.is_profile_complete:
            return Response({
                'success': False,
                'message': 'Profile is already complete'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        serializer = ProfileCompletionSerializer(user, data=request.data)
        
        if serializer.is_valid():
            # Save the user profile
            serializer.save()
            
            # Generate token for the user after profile completion
            # Prevent issuing tokens if account is suspended
            if not user.is_active:
                return Response({'success': False, 'message': 'Account suspended'}, status=status.HTTP_403_FORBIDDEN)

            token, created = Token.objects.get_or_create(user=user)
            user_session = UserSession.objects.create(user=user)
            
            response_message = 'Profile completed successfully! You can now login.'
            return Response({
                'success': True,
                'message': response_message,
                'user': UserProfileSerializer(user).data,
                'token': token.key,
                'session_token': user_session.session_token,
                'profile_complete': user.is_profile_complete
            }, status=status.HTTP_200_OK)
        
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(responses={200: dict})
class CompleteProfileWithSocialView(APIView):
    """Complete profile using social account info from failed Google/Facebook login"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        # Get both profile completion data and social account info
        mobile_number = request.data.get('mobile_number')
        social_account_info = request.data.get('social_account_info', {})
        
        if not mobile_number:
            return Response({
                'success': False,
                'message': 'Mobile number is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Clean and validate mobile number format
        import re
        cleaned_number = re.sub(r'[^\d+]', '', mobile_number)
        if cleaned_number.startswith('+91'):
            cleaned_number = cleaned_number[3:]
        elif cleaned_number.startswith('91'):
            cleaned_number = cleaned_number[2:]
        
        try:
            user = CustomUser.objects.get(mobile_number=cleaned_number)
        except CustomUser.DoesNotExist:
            return Response({
                'success': False,
                'message': 'User with this mobile number does not exist. Please register your phone number first.'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Check if mobile number is verified
        if not user.is_mobile_verified:
            return Response({
                'success': False,
                'message': 'Please verify your mobile number first'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if profile is already complete
        if user.is_profile_complete:
            return Response({
                'success': False,
                'message': 'Profile is already complete'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Complete the profile first
        serializer = ProfileCompletionSerializer(user, data=request.data)
        
        if serializer.is_valid():
            # Save the user profile
            serializer.save()
            
            # Now link the social account if provided
            if social_account_info:
                provider = social_account_info.get('provider')
                social_id = social_account_info.get('social_id')
                email = social_account_info.get('email')
                name = social_account_info.get('name')
                
                if provider == 'google' and social_id:
                    # Check if Google ID is already linked to another user
                    existing = CustomUser.objects.filter(google_id=social_id).exclude(id=user.id).first()
                    if existing:
                        return Response({
                            'success': False,
                            'message': 'This Google account is already linked to another user'
                        }, status=status.HTTP_400_BAD_REQUEST)
                    
                    user.google_id = social_id
                    user.registration_method = 'google'
                    if not user.email and email:
                        # Check if email is already used by another user
                        if not CustomUser.objects.filter(email=email).exclude(id=user.id).exists():
                            user.email = email
                    user.save()
                    
                elif provider == 'facebook' and social_id:
                    # Check if Facebook ID is already linked to another user
                    existing = CustomUser.objects.filter(facebook_id=social_id).exclude(id=user.id).first()
                    if existing:
                        return Response({
                            'success': False,
                            'message': 'This Facebook account is already linked to another user'
                        }, status=status.HTTP_400_BAD_REQUEST)
                    
                    user.facebook_id = social_id
                    user.registration_method = 'facebook'
                    if not user.email and email:
                        # Check if email is already used by another user
                        if not CustomUser.objects.filter(email=email).exclude(id=user.id).exists():
                            user.email = email
                    user.save()
            
            # Generate token for the user after profile completion
            # Prevent issuing tokens if account is suspended
            if not user.is_active:
                return Response({'success': False, 'message': 'Account suspended'}, status=status.HTTP_403_FORBIDDEN)

            token, created = Token.objects.get_or_create(user=user)
            user_session = UserSession.objects.create(user=user)
            
            social_message = f" and {social_account_info.get('provider', 'social')} account linked" if social_account_info else ""
            response_message = f'Profile completed successfully{social_message}! You can now login.'
            
            return Response({
                'success': True,
                'message': response_message,
                'user': UserProfileSerializer(user).data,
                'token': token.key,
                'session_token': user_session.session_token,
                'profile_complete': user.is_profile_complete,
                'social_linked': bool(social_account_info)
            }, status=status.HTTP_200_OK)
        
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


# LOGIN FLOWS
@extend_schema(request=PhoneLoginSerializer, responses={200: dict})
class PhoneLoginView(APIView):
    """Login using phone number + OTP"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = PhoneLoginSerializer(data=request.data)
        # Validate input and inspect errors to provide a clearer message when
        # the user's profile is incomplete. We must not consume or mark the
        # OTP as used in that case.
        if not serializer.is_valid():
            errors = serializer.errors
            # If validation failed because profile is incomplete, return a
            # specific message so frontend can redirect to signup/profile
            # completion flow.
            if 'profile' in errors or errors.get('profile'):
                return Response({
                    'success': False,
                    'message': 'Profile not completed. Please complete your profile to sign in.',
                    'next_step': 'complete_profile'
                }, status=status.HTTP_400_BAD_REQUEST)

            return Response({
                'success': False,
                'errors': errors
            }, status=status.HTTP_400_BAD_REQUEST)

        # Validated: proceed with login flow
        user = serializer.validated_data['user']
        otp_instance = serializer.validated_data['otp_instance']

        # Mark OTP as verified
        otp_instance.is_verified = True
        otp_instance.save()
        # Delete OTP instance after successful login/verification
        try:
            otp_instance.delete()
        except Exception:
            logger.exception('Failed to delete OTP instance after login')

        # Update user login time
        user.last_login = timezone.now()
        user.save()

        # Create new session
        token, created = Token.objects.get_or_create(user=user)
        UserSession.objects.filter(user=user, is_active=True).update(is_active=False)
        user_session = UserSession.objects.create(user=user)

        return Response({
            'success': True,
            'message': 'Login successful',
            'user': UserProfileSerializer(user).data,
            'token': token.key,
            'session_token': user_session.session_token
        }, status=status.HTTP_200_OK)


# UTILITY VIEWS
@extend_schema(responses={200: dict})
class CheckUserExistsView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        mobile_number = request.data.get('mobile_number', '')
        email = request.data.get('email', '')
        
        if not mobile_number and not email:
            return Response({
                'success': False,
                'message': 'Mobile number or email is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        response_data = {'success': True}
        
        if mobile_number:
            import re
            cleaned_number = re.sub(r'[^\d+]', '', mobile_number)
            if cleaned_number.startswith('+91'):
                cleaned_number = cleaned_number[3:]
            elif cleaned_number.startswith('91'):
                cleaned_number = cleaned_number[2:]
            
            try:
                user = CustomUser.objects.get(mobile_number=cleaned_number)
                response_data.update({
                    'phone_user_exists': True,
                    'mobile_number': cleaned_number,
                    'profile_complete': user.is_profile_complete,
                    'can_login': user.is_profile_complete
                })
            except CustomUser.DoesNotExist:
                response_data.update({
                    'phone_user_exists': False,
                    'mobile_number': cleaned_number,
                    'can_register': True
                })
        
        if email:
            try:
                user = CustomUser.objects.get(email=email)
                response_data.update({
                    'email_user_exists': True,
                    'email': email,
                    'has_phone': bool(user.mobile_number),
                    'profile_complete': user.is_profile_complete
                })
            except CustomUser.DoesNotExist:
                response_data.update({
                    'email_user_exists': False,
                    'email': email
                })
        
        return Response(response_data, status=status.HTTP_200_OK)


@extend_schema(responses={200: dict})
class UserLogoutView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            request.user.auth_token.delete()
            UserSession.objects.filter(user=request.user, is_active=True).update(is_active=False)
            
            return Response({
                'success': True,
                'message': 'Logged out successfully'
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                'success': False,
                'message': 'Logout failed'
            }, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(responses={200: UserProfileSerializer})
class UserProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = UserProfileSerializer
    permission_classes = [IsAuthenticated]
    
    def get_object(self):
        return self.request.user
    
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response({
            'success': True,
            'user': serializer.data
        })
    
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        
        if serializer.is_valid():
            self.perform_update(serializer)
            return Response({
                'success': True,
                'message': 'Profile updated successfully',
                'user': serializer.data
            })
        
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(responses={200: UserProfileSerializer})
class CurrentUserView(APIView):
    """Return the currently authenticated user's profile.

    Supports DRF Token authentication (Authorization: Token <key>)
    or session token via header X-Session-Token: <token> or query param ?session_token=<token>
    """
    permission_classes = [AllowAny]

    def get(self, request):
        # First, try standard DRF authentication
        user = None
        try:
            user = request.user if request.user and request.user.is_authenticated else None
        except Exception:
            user = None

        # If not authenticated by DRF token, try session token
        if not user:
            session_token = request.headers.get('X-Session-Token') or request.query_params.get('session_token')
            if session_token:
                try:
                    session = UserSession.objects.filter(session_token=session_token, is_active=True).select_related('user').first()
                    if session and not session.is_expired():
                        user = session.user
                except Exception:
                    user = None

        if not user:
            return Response({'success': False, 'message': 'Authentication credentials were not provided or are invalid'}, status=status.HTTP_401_UNAUTHORIZED)

        # Prevent suspended users from getting profile
        if not user.is_active:
            return Response({'success': False, 'message': 'Account suspended'}, status=status.HTTP_403_FORBIDDEN)

        serializer = UserProfileSerializer(user)
        return Response({'success': True, 'user': serializer.data})
 


@extend_schema(responses={200: dict})
class OAuthCallbackView(APIView):
    """Handle OAuth authorization code from frontend: exchange code for access token, get user info, create/return user and tokens"""
    permission_classes = [AllowAny]

    def post(self, request):
        provider = request.data.get('provider')
        code = request.data.get('code')
        redirect_uri = request.data.get('redirect_uri')

        if not provider or not code or not redirect_uri:
            return Response({'success': False, 'message': 'provider, code and redirect_uri are required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            if provider == 'google':
                token_data = self.exchange_google_code(code, redirect_uri)
                access_token = token_data.get('access_token')
                # fetch user info
                user_info = requests.get(
                    f'https://www.googleapis.com/oauth2/v1/userinfo?alt=json&access_token={access_token}'
                ).json()
                social_id = user_info.get('id')
                email = user_info.get('email')
                name = user_info.get('name') or f"{user_info.get('given_name','')} {user_info.get('family_name','')}".strip()
                provider_field = 'google'
            elif provider == 'facebook':
                token_data = self.exchange_facebook_code(code, redirect_uri)
                access_token = token_data.get('access_token')
                user_info = requests.get(
                    f'https://graph.facebook.com/me?access_token={access_token}&fields=id,name,email,first_name,last_name,picture'
                ).json()
                social_id = user_info.get('id')
                email = user_info.get('email')
                name = user_info.get('name')
                provider_field = 'facebook'
            else:
                return Response({'success': False, 'message': 'Unsupported provider'}, status=status.HTTP_400_BAD_REQUEST)

            # Find or create user
            # If the request is made by an authenticated user, treat this as a linking operation
            request_user = None
            try:
                if request.user and request.user.is_authenticated:
                    request_user = request.user
            except Exception:
                request_user = None

            if request_user:
                # Ensure the social id is not already linked to another account
                if provider_field == 'google':
                    existing = CustomUser.objects.filter(google_id=social_id).exclude(id=request_user.id).first()
                    if existing:
                        return Response({'success': False, 'message': 'This Google account is already linked to another user'}, status=status.HTTP_400_BAD_REQUEST)
                    request_user.google_id = social_id
                    request_user.registration_method = 'google'
                    # Optionally update email/name if empty
                    if not request_user.email and email:
                        if not CustomUser.objects.filter(email=email).exclude(id=request_user.id).exists():
                            request_user.email = email
                    if not request_user.full_name and name:
                        request_user.full_name = name
                    request_user.save()
                else:
                    existing = CustomUser.objects.filter(facebook_id=social_id).exclude(id=request_user.id).first()
                    if existing:
                        return Response({'success': False, 'message': 'This Facebook account is already linked to another user'}, status=status.HTTP_400_BAD_REQUEST)
                    request_user.facebook_id = social_id
                    request_user.registration_method = 'facebook'
                    if not request_user.email and email:
                        if not CustomUser.objects.filter(email=email).exclude(id=request_user.id).exists():
                            request_user.email = email
                    if not request_user.full_name and name:
                        request_user.full_name = name
                    request_user.save()

                # Return success for linking operation
                return Response({
                    'success': True,
                    'message': 'Social account linked successfully',
                    'linked': True,
                    'provider': provider,
                    'user': UserProfileSerializer(request_user).data
                }, status=status.HTTP_200_OK)

            # Otherwise, find or create user (existing login/registration flow)
            user = None
            if provider == 'google':
                user = CustomUser.objects.filter(google_id=social_id).first()
            else:
                user = CustomUser.objects.filter(facebook_id=social_id).first()

            if not user and email:
                # Try to find user by email
                user = CustomUser.objects.filter(email=email).first()

            if user:
                # Link social id if not linked
                if provider_field == 'google' and not user.google_id:
                    user.google_id = social_id
                    user.registration_method = 'google'
                    user.save()
                if provider_field == 'facebook' and not user.facebook_id:
                    user.facebook_id = social_id
                    user.registration_method = 'facebook'
                    user.save()
                
                # If profile is complete, issue token and session (login)
                if user.is_profile_complete:
                    # Ensure suspended users cannot receive tokens
                    if not user.is_active:
                        return Response({'success': False, 'message': 'Account suspended'}, status=status.HTTP_403_FORBIDDEN)

                    token, _ = Token.objects.get_or_create(user=user)
                    UserSession.objects.filter(user=user, is_active=True).update(is_active=False)
                    user_session = UserSession.objects.create(user=user)

                    return Response({
                        'success': True,
                        'message': 'OAuth login successful',
                        'user': UserProfileSerializer(user).data,
                        'token': token.key,
                        'session_token': user_session.session_token
                    }, status=status.HTTP_200_OK)
                else:
                    # User exists but profile incomplete - don't allow login, redirect to profile completion
                    return Response({
                        'success': False,
                        'message': 'Profile not completed. Please complete your profile to login.',
                        'next_step': 'complete_profile',
                        'user_id': user.id,
                        'mobile_number': user.mobile_number
                    }, status=status.HTTP_400_BAD_REQUEST)
            else:
                # User doesn't exist - DON'T create user account in DB
                # Instead, return the social account info for frontend to handle profile completion
                return Response({
                    'success': False,
                    'message': 'Account not found. Please register with your phone number first and complete your profile.',
                    'next_step': 'register_phone_first',
                    'social_account_info': {
                        'provider': provider,
                        'social_id': social_id,
                        'email': email,
                        'name': name,
                        'provider_access_token': access_token
                    }
                }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.exception('OAuth callback error')
            # If the exception carries provider response details, include them in the response for debugging
            message = str(e)
            return Response({'success': False, 'message': message}, status=status.HTTP_400_BAD_REQUEST)

    def exchange_google_code(self, code, redirect_uri):
        data = {
            'code': code,
            'client_id': getattr(settings, 'GOOGLE_OAUTH2_CLIENT_ID', ''),
            'client_secret': getattr(settings, 'GOOGLE_OAUTH2_CLIENT_SECRET', ''),
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'
        }
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        resp = requests.post('https://oauth2.googleapis.com/token', data=data, headers=headers)
        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            # Attach response body for easier debugging
            body = resp.text
            logger.error('Google token exchange failed: %s', body)
            raise requests.HTTPError(f'{e} - response body: {body}')
        return resp.json()

    def exchange_facebook_code(self, code, redirect_uri):
        params = {
            'client_id': getattr(settings, 'FACEBOOK_APP_ID', ''),
            'client_secret': getattr(settings, 'FACEBOOK_APP_SECRET', ''),
            'redirect_uri': redirect_uri,
            'code': code
        }
        resp = requests.get('https://graph.facebook.com/v18.0/oauth/access_token', params=params)
        resp.raise_for_status()
        return resp.json()


@extend_schema(responses={200: dict})
class OAuthTokenView(APIView):
    """Exchange authorization code for provider access token (used if frontend prefers server-side exchange)"""
    permission_classes = [AllowAny]

    def post(self, request):
        provider = request.data.get('provider')
        code = request.data.get('code')
        redirect_uri = request.data.get('redirect_uri')

        if not provider or not code or not redirect_uri:
            return Response({'success': False, 'message': 'provider, code and redirect_uri are required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            if provider == 'google':
                data = {
                    'code': code,
                    'client_id': getattr(settings, 'GOOGLE_OAUTH2_CLIENT_ID', ''),
                    'client_secret': getattr(settings, 'GOOGLE_OAUTH2_CLIENT_SECRET', ''),
                    'redirect_uri': redirect_uri,
                    'grant_type': 'authorization_code'
                }
                resp = requests.post('https://oauth2.googleapis.com/token', data=data)
                resp.raise_for_status()
                return Response(resp.json(), status=status.HTTP_200_OK)

            elif provider == 'facebook':
                params = {
                    'client_id': getattr(settings, 'FACEBOOK_APP_ID', ''),
                    'client_secret': getattr(settings, 'FACEBOOK_APP_SECRET', ''),
                    'redirect_uri': redirect_uri,
                    'code': code
                }
                resp = requests.get('https://graph.facebook.com/v18.0/oauth/access_token', params=params)
                resp.raise_for_status()
                return Response(resp.json(), status=status.HTTP_200_OK)

            else:
                return Response({'success': False, 'message': 'Unsupported provider'}, status=status.HTTP_400_BAD_REQUEST)

        except requests.HTTPError as e:
            logger.exception('Token exchange failed')
            return Response({'success': False, 'message': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(responses={200: dict})
class LinkSocialView(APIView):
    """Link a social account (google/facebook) to the authenticated user using provider access token"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        provider = request.data.get('provider')
        access_token = request.data.get('access_token')

        if not provider or not access_token:
            return Response({'success': False, 'message': 'provider and access_token are required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            if provider == 'google':
                # fetch userinfo
                user_info = requests.get(f'https://www.googleapis.com/oauth2/v1/userinfo?alt=json&access_token={access_token}').json()
                social_id = user_info.get('id')
                email = user_info.get('email')
                name = user_info.get('name')

                # check if already linked to another user
                existing = CustomUser.objects.filter(google_id=social_id).exclude(id=request.user.id).first()
                if existing:
                    return Response({'success': False, 'message': 'This Google account is already linked to another user'}, status=status.HTTP_400_BAD_REQUEST)

                request.user.google_id = social_id
                if not request.user.email and email:
                    if not CustomUser.objects.filter(email=email).exclude(id=request.user.id).exists():
                        request.user.email = email
                if not request.user.full_name and name:
                    request.user.full_name = name
                request.user.save()

            elif provider == 'facebook':
                user_info = requests.get(f'https://graph.facebook.com/me?access_token={access_token}&fields=id,name,email').json()
                social_id = user_info.get('id')
                email = user_info.get('email')
                name = user_info.get('name')

                existing = CustomUser.objects.filter(facebook_id=social_id).exclude(id=request.user.id).first()
                if existing:
                    return Response({'success': False, 'message': 'This Facebook account is already linked to another user'}, status=status.HTTP_400_BAD_REQUEST)

                request.user.facebook_id = social_id
                if not request.user.email and email:
                    if not CustomUser.objects.filter(email=email).exclude(id=request.user.id).exists():
                        request.user.email = email
                if not request.user.full_name and name:
                    request.user.full_name = name
                request.user.save()

            else:
                return Response({'success': False, 'message': 'Unsupported provider'}, status=status.HTTP_400_BAD_REQUEST)

            return Response({'success': True, 'message': 'Social account linked', 'user': UserProfileSerializer(request.user).data}, status=status.HTTP_200_OK)

        except requests.HTTPError as e:
            logger.exception('Link social failed')
            return Response({'success': False, 'message': str(e)}, status=status.HTTP_400_BAD_REQUEST)



@extend_schema(responses={200: dict})
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_dashboard(request):
    user = request.user
    
    dashboard_data = {
        'user_info': UserProfileSerializer(user).data,
        'user_type_display': user.get_user_type_display(),
    }
    
    if user.user_type == 'smart_buyer':
        dashboard_data['buyer_category_display'] = user.get_buyer_category_display()
    
    return Response({
        'success': True,
        'dashboard': dashboard_data
    })


@extend_schema(responses={200: dict})
@api_view(['GET'])
@permission_classes([AllowAny])
def user_statistics(request):
    total_users = CustomUser.objects.count()
    smart_sellers = CustomUser.objects.filter(user_type='smart_seller').count()
    smart_buyers = CustomUser.objects.filter(user_type='smart_buyer').count()
    verified_users = CustomUser.objects.filter(is_mobile_verified=True).count()
    complete_profiles = CustomUser.objects.filter(is_profile_complete=True).count()
    
    buyer_categories = CustomUser.objects.filter(user_type='smart_buyer')
    mandi_owners = buyer_categories.filter(buyer_category='mandi_owner').count()
    shopkeepers = buyer_categories.filter(buyer_category='shopkeeper').count()
    communities = buyer_categories.filter(buyer_category='community').count()
    
    return Response({
        'success': True,
        'statistics': {
            'total_users': total_users,
            'smart_sellers': smart_sellers,
            'smart_buyers': smart_buyers,
            'verified_users': verified_users,
            'complete_profiles': complete_profiles,
            'buyer_breakdown': {
                'mandi_owners': mandi_owners,
                'shopkeepers': shopkeepers,
                'communities': communities
            }
        }
    })



@extend_schema(responses={200: dict})
@api_view(['GET'])
@permission_classes([AllowAny])
def weather_view(request):
    """Return weather for the authenticated user (uses user's latitude/longitude and city).

    If the request is unauthenticated, return a default city ('Delhi') and its current weather.
    Response includes: city, latitude, longitude, temperature_c, condition_text, raw_provider (optional).
    """
    # Default fallback from settings
    default_city = getattr(settings, 'WEATHER_DEFAULT_CITY', 'Delhi')
    default_lat = float(getattr(settings, 'WEATHER_DEFAULT_LAT', 28.644800))
    default_lon = float(getattr(settings, 'WEATHER_DEFAULT_LON', 77.216721))

    user = None
    try:
        user = request.user if request.user and request.user.is_authenticated else None
    except Exception:
        user = None

    if user:
        city = user.city or default_city
        lat = float(user.latitude or default_lat)
        lon = float(user.longitude or default_lon)
    else:
        city = default_city
        lat = default_lat
        lon = default_lon

    api_key = getattr(settings, 'WEATHER_API_KEY', None)
    if not api_key:
        return Response({'success': False, 'message': 'Weather API key not configured'}, status=500)

    weather_url = f'https://api.weatherapi.com/v1/current.json?key={api_key}&q={lat},{lon}'
    try:
        resp = requests.get(weather_url, timeout=5)
        resp.raise_for_status()
        data = resp.json()

        current = data.get('current', {})
        location = data.get('location', {})

        result = {
            'success': True,
            'city': city,
            'latitude': lat,
            'longitude': lon,
            'provider_location_name': location.get('name'),
            'localtime': location.get('localtime'),
            'temperature_c': current.get('temp_c'),
            'temperature_f': current.get('temp_f'),
            'condition_text': current.get('condition', {}).get('text'),
            'humidity': current.get('humidity'),
            'wind_kph': current.get('wind_kph'),
            'vis_km': current.get('vis_km'),
            'raw': current,
        }

        return Response(result)
    except requests.RequestException as e:
        logger.exception('Weather API request failed')
        return Response({'success': False, 'message': 'Failed to fetch weather', 'error': str(e)}, status=502)


# CONTACT QUERY APIS
@extend_schema(request=ContactQuerySerializer, responses={201: dict})
class ContactQueryCreateView(APIView):
    """API for visitors to submit contact queries and """
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = ContactQuerySerializer(data=request.data)
        
        if serializer.is_valid():
            # Get IP address from request
            def get_client_ip(request):
                x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
                if x_forwarded_for:
                    ip = x_forwarded_for.split(',')[0]
                else:
                    ip = request.META.get('REMOTE_ADDR')
                return ip
            
            contact_query = serializer.save(ip_address=get_client_ip(request))
            
            return Response({
                'success': True,
                'message': 'Your query has been submitted successfully. We will get back to you soon!',
                'query_id': contact_query.id
            }, status=status.HTTP_201_CREATED)
        
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class AdminPermissionMixin:
    """Mixin to check X-Admin-Token header for admin authentication"""

    def check_admin(self, request):
        import base64
        from django.conf import settings
        
        header_token = request.headers.get('X-Admin-Token') or request.META.get('HTTP_X_ADMIN_TOKEN')
        if not header_token:
            # also support Authorization: Basic <base64>
            auth = request.headers.get('Authorization') or request.META.get('HTTP_AUTHORIZATION', '')
            if auth.startswith('Basic '):
                header_token = auth.split(' ', 1)[1].strip()

        if not header_token:
            return False

        expected_user = getattr(settings, 'ADMIN_USERNAME', None)
        expected_pass = getattr(settings, 'ADMIN_PASSWORD', None)
        if not expected_user or not expected_pass:
            return False
        
        # Create expected token
        raw = f"{expected_user}:{expected_pass}".encode('utf-8')
        expected = base64.b64encode(raw).decode('utf-8')
        return header_token == expected


@extend_schema(responses={200: ContactQueryListSerializer(many=True)})
class ContactQueryListView(AdminPermissionMixin, APIView):
    """API for admin to view all contact queries"""
    permission_classes = [AllowAny]
    
    def dispatch(self, request, *args, **kwargs):
        if not self.check_admin(request):
            return Response({
                'success': False, 
                'message': 'Admin authentication required'
            }, status=status.HTTP_401_UNAUTHORIZED)
        return super().dispatch(request, *args, **kwargs)
    
    def get(self, request, *args, **kwargs):
        queries = ContactQuery.objects.all().order_by('-created_at')
        serializer = ContactQueryListSerializer(queries, many=True)
        
        return Response({
            'success': True,
            'message': f'Found {len(serializer.data)} contact queries',
            'queries': serializer.data
        }, status=status.HTTP_200_OK)
