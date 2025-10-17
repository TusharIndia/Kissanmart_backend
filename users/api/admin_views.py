from rest_framework.views import APIView
from rest_framework import status, generics
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.conf import settings
from .serializers_new import UserListSerializer, UserProfileSerializer
from .admin_serializers import (
    AdminUserListSerializer, AdminUserDetailSerializer, AdminUserUpdateSerializer
)
from ..models import AdminActionLog
from .admin_serializers import AdminActionLogSerializer
from ..models import CustomUser
from django.shortcuts import get_object_or_404
import base64
from drf_spectacular.utils import extend_schema


def make_admin_token(username: str, password: str) -> str:
    """Create a simple base64 token from username:password"""
    raw = f"{username}:{password}".encode('utf-8')
    return base64.b64encode(raw).decode('utf-8')


@extend_schema(responses={200: dict})
class AdminAuthView(APIView):
    """Authenticate admin credentials against env vars and return a token.

    POST payload: {"username": "admin", "password": "admin123"}
    Returns: {"success": True, "token": "..."}
    """
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        username = data.get('username')
        password = data.get('password')
        if not username or not password:
            return Response({'success': False, 'message': 'username and password required'}, status=status.HTTP_400_BAD_REQUEST)

        expected_user = getattr(settings, 'ADMIN_USERNAME', None)
        expected_pass = getattr(settings, 'ADMIN_PASSWORD', None)
        if not expected_user or not expected_pass:
            return Response({'success': False, 'message': 'Admin credentials are not configured on the server'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if username == expected_user and password == expected_pass:
            token = make_admin_token(username, password)
            return Response({'success': True, 'token': token})
        return Response({'success': False, 'message': 'Invalid admin credentials'}, status=status.HTTP_401_UNAUTHORIZED)


class AdminPermissionMixin:
    """Mixin to check X-Admin-Token header or basic auth style token"""

    def check_admin(self, request):
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
        expected = make_admin_token(expected_user, expected_pass)
        return header_token == expected


class AdminUserListCreate(AdminPermissionMixin, generics.ListCreateAPIView):
    """List all users or create a new user. Protected by admin token header.

    GET /api/admin/users/ -> list users
    POST /api/admin/users/ -> create user (use UserProfileSerializer fields)
    """
    queryset = CustomUser.objects.all().order_by('-created_at')
    # Use admin-locked serializer for listing
    serializer_class = AdminUserListSerializer

    permission_classes = [AllowAny]

    def dispatch(self, request, *args, **kwargs):
        if not self.check_admin(request):
            return Response({'success': False, 'message': 'Admin authentication required'}, status=status.HTTP_401_UNAUTHORIZED)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        users = self.get_queryset()
        serializer = AdminUserListSerializer(users, many=True)
        return Response({'success': True, 'users': serializer.data})

    def post(self, request, *args, **kwargs):
        # Admins should not create users via this endpoint - disallow
        return Response({'success': False, 'message': 'Admin user creation not allowed via this endpoint'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)


@extend_schema(responses={200: dict})
class AdminUserRetrieveUpdateDelete(AdminPermissionMixin, APIView):
    permission_classes = [AllowAny]
    """Retrieve, update or delete a user by ID. Protected by admin token header.

    GET /api/admin/users/<id>/
    PUT/PATCH /api/admin/users/<id>/
    DELETE /api/admin/users/<id>/
    """

    def get_object(self, pk):
        return get_object_or_404(CustomUser, pk=pk)

    def dispatch(self, request, *args, **kwargs):
        if not self.check_admin(request):
            return Response({'success': False, 'message': 'Admin authentication required'}, status=status.HTTP_401_UNAUTHORIZED)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, id):
        user = self.get_object(id)
        serializer = AdminUserDetailSerializer(user)
        return Response({'success': True, 'user': serializer.data})

    def put(self, request, id):
        # Admins are not allowed to update user details via this endpoint
        return Response({'success': False, 'message': 'Admin update not allowed'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def patch(self, request, id):
        # Admins are not allowed to update user details via this endpoint
        return Response({'success': False, 'message': 'Admin update not allowed'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def delete(self, request, id):
        # Permanently delete user and log action
        user = self.get_object(id)
        admin_user = None
        # try to get admin username from basic auth header or token (best-effort)
        auth = request.headers.get('Authorization') or request.META.get('HTTP_AUTHORIZATION', '')
        if auth.startswith('Basic '):
            token = auth.split(' ', 1)[1]
            try:
                import base64
                raw = base64.b64decode(token).decode('utf-8')
                admin_user = raw.split(':', 1)[0]
            except Exception:
                admin_user = None

        AdminActionLog.objects.create(admin_username=admin_user, user=user, action='delete', details='Deleted by admin')
        user.delete()
        return Response({'success': True, 'message': 'User deleted'})

    # Additional admin-only actions
    def post_suspend(self, request, id):
        # Suspend (deactivate) a user
        user = self.get_object(id)
        if not user.is_active:
            return Response({'success': False, 'message': 'User already suspended'}, status=status.HTTP_400_BAD_REQUEST)
        user.is_active = False
        user.save()
        admin_user = None
        auth = request.headers.get('Authorization') or request.META.get('HTTP_AUTHORIZATION', '')
        if auth.startswith('Basic '):
            token = auth.split(' ', 1)[1]
            try:
                import base64
                raw = base64.b64decode(token).decode('utf-8')
                admin_user = raw.split(':', 1)[0]
            except Exception:
                admin_user = None
        AdminActionLog.objects.create(admin_username=admin_user, user=user, action='suspend', details='Suspended by admin')
        return Response({'success': True, 'message': 'User suspended'})

    def get_logs(self, request, id):
        # Return admin action logs for a user
        user = self.get_object(id)
        logs = AdminActionLog.objects.filter(user=user).order_by('-created_at')
        serializer = AdminActionLogSerializer(logs, many=True)
        return Response({'success': True, 'logs': serializer.data})


@extend_schema(responses={200: dict})
class AdminUserSuspendView(AdminPermissionMixin, APIView):
    permission_classes = [AllowAny]

    def dispatch(self, request, *args, **kwargs):
        if not self.check_admin(request):
            return Response({'success': False, 'message': 'Admin authentication required'}, status=status.HTTP_401_UNAUTHORIZED)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, id):
        user = get_object_or_404(CustomUser, pk=id)
        if not user.is_active:
            return Response({'success': False, 'message': 'User already suspended'}, status=status.HTTP_400_BAD_REQUEST)
        user.is_active = False
        user.save()
        admin_user = None
        auth = request.headers.get('Authorization') or request.META.get('HTTP_AUTHORIZATION', '')
        if auth.startswith('Basic '):
            token = auth.split(' ', 1)[1]
            try:
                raw = base64.b64decode(token).decode('utf-8')
                admin_user = raw.split(':', 1)[0]
            except Exception:
                admin_user = None
        AdminActionLog.objects.create(admin_username=admin_user, user=user, action='suspend', details='Suspended by admin')
        return Response({'success': True, 'message': 'User suspended'})


@extend_schema(responses={200: dict})
class AdminUserLogsView(AdminPermissionMixin, APIView):
    permission_classes = [AllowAny]

    def dispatch(self, request, *args, **kwargs):
        if not self.check_admin(request):
            return Response({'success': False, 'message': 'Admin authentication required'}, status=status.HTTP_401_UNAUTHORIZED)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, id):
        user = get_object_or_404(CustomUser, pk=id)
        logs = AdminActionLog.objects.filter(user=user).order_by('-created_at')
        serializer = AdminActionLogSerializer(logs, many=True)
        return Response({'success': True, 'logs': serializer.data})
