"""
Authentication views.
Handles login, registration, token refresh, and current user endpoints.
"""
from rest_framework import status, generics
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView
from django.contrib.auth import get_user_model, authenticate
from users.serializers import UserSerializer, UserCreateSerializer
from tenants.models import AuditLog
from notifications.services import NotificationService

User = get_user_model()


class LoginView(APIView):
    """
    User login endpoint.
    
    POST /api/auth/login/
    
    Request:
        {
            "email": "user@example.com",
            "password": "password123"
        }
    
    Response:
        {
            "access": "jwt_access_token",
            "refresh": "jwt_refresh_token",
            "user": { ... user details ... }
        }
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        email = request.data.get('email', '').lower().strip()
        password = request.data.get('password', '')
        
        if not email or not password:
            return Response(
                {'error': 'Email and password are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Authenticate user
        user = authenticate(request, username=email, password=password)
        
        if user is None:
            # Log failed attempt
            AuditLog.log(
                action='auth.login_failed',
                metadata={'email': email},
                request=request
            )
            return Response(
                {'error': 'Invalid credentials'},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        if not user.is_active:
            return Response(
                {'error': 'Account is disabled'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check tenant status for non-super admins
        if not user.is_super_admin and user.tenant:
            if not user.tenant.is_active:
                return Response(
                    {'error': 'Tenant is suspended'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        # Generate tokens
        refresh = RefreshToken.for_user(user)
        
        # Add custom claims
        refresh['role'] = user.role
        refresh['tenant_id'] = str(user.tenant_id) if user.tenant_id else None
        
        # Log successful login
        AuditLog.log(
            action='auth.login_success',
            user=user,
            tenant=user.tenant,
            request=request
        )
        
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UserSerializer(user).data
        })


class RegisterView(generics.CreateAPIView):
    """
    User registration endpoint (Super Admin only).
    
    POST /api/auth/register/
    """
    queryset = User.objects.all()
    serializer_class = UserCreateSerializer
    permission_classes = [AllowAny]  # Will be restricted in production
    
    def perform_create(self, serializer):
        user = serializer.save()
        
        # Log registration
        AuditLog.log(
            action='auth.user_registered',
            user=self.request.user if self.request.user.is_authenticated else None,
            tenant=user.tenant,
            metadata={'new_user_id': str(user.id), 'email': user.email},
            request=self.request
        )
        
        # Notify super admins of new user registration
        NotificationService.notify_on_user_registration(user)


class MeView(APIView):
    """
    Get current user details.
    
    GET /api/auth/me/
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        return Response(UserSerializer(request.user).data)
    
    def patch(self, request):
        """Update current user profile."""
        serializer = UserSerializer(
            request.user,
            data=request.data,
            partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class RefreshTokenView(TokenRefreshView):
    """
    Refresh access token.
    
    POST /api/auth/refresh/
    
    Request:
        {
            "refresh": "jwt_refresh_token"
        }
    
    Response:
        {
            "access": "new_jwt_access_token"
        }
    """
    pass


class LogoutView(APIView):
    """
    Logout endpoint - blacklist refresh token.
    
    POST /api/auth/logout/
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
            
            AuditLog.log(
                action='auth.logout',
                user=request.user,
                tenant=request.tenant,
                request=request
            )
            
            return Response({'message': 'Logged out successfully'})
        except Exception:
            return Response({'message': 'Logged out successfully'})


class MyTenantView(APIView):
    """
    Get current user's tenant details.
    
    GET /api/auth/my-tenant/
    
    Returns tenant details for users who belong to a tenant.
    Returns 404 for users without a tenant (Super Admin, Agency Admin without tenant).
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        
        if not user.tenant:
            return Response(
                {'error': 'User does not belong to a tenant'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Log tenant details access for audit trail
        AuditLog.log(
            action='tenant.view_details',
            user=user,
            tenant=user.tenant,
            metadata={'tenant_id': str(user.tenant.id)},
            request=request
        )
        
        from tenants.serializers import TenantBasicSerializer
        return Response(TenantBasicSerializer(user.tenant).data)
