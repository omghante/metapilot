"""
Setup views for initial configuration.
Used when Shell access is not available (free Render plan).
"""
import os
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status
from django.contrib.auth import get_user_model
from users.models import UserRole
from tenants.models import AuditLog

User = get_user_model()


class CreateSuperAdminView(APIView):
    """
    One-time setup endpoint to create Super Admin.
    
    POST /api/setup/create-superadmin/
    
    Request:
    {
        "setup_key": "YOUR_FERNET_KEY",  # Must match FERNET_KEY env var
        "email": "admin@example.com",
        "password": "your-password",
        "first_name": "Admin",
        "last_name": "User"
    }
    
    🔐 Security:
    - Requires FERNET_KEY as setup_key for authorization
    - Only works if no Super Admin exists yet
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        # Get the setup key from environment
        setup_key = os.getenv('FERNET_KEY', '')
        provided_key = request.data.get('setup_key', '')
        
        # Verify setup key
        if not setup_key or provided_key != setup_key:
            return Response(
                {'error': 'Invalid setup key'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if Super Admin already exists
        if User.objects.filter(role=UserRole.SUPER_ADMIN).exists():
            return Response(
                {'error': 'Super Admin already exists. Use login instead.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get user data
        email = request.data.get('email', '').lower().strip()
        password = request.data.get('password', '')
        first_name = request.data.get('first_name', '')
        last_name = request.data.get('last_name', '')
        
        if not email or not password:
            return Response(
                {'error': 'Email and password are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if len(password) < 8:
            return Response(
                {'error': 'Password must be at least 8 characters'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if email already exists
        if User.objects.filter(email=email).exists():
            return Response(
                {'error': 'User with this email already exists'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create Super Admin
        user = User.objects.create_superuser(
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name
        )
        
        # Log the action
        AuditLog.log(
            action='setup.superadmin_created',
            user=user,
            metadata={'email': email},
            request=request
        )
        
        return Response({
            'message': 'Super Admin created successfully!',
            'user': {
                'id': str(user.id),
                'email': user.email,
                'role': user.role,
                'first_name': user.first_name,
                'last_name': user.last_name
            }
        }, status=status.HTTP_201_CREATED)


class SetupStatusView(APIView):
    """
    Check if initial setup is complete.
    
    GET /api/setup/status/
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        super_admin_exists = User.objects.filter(role=UserRole.SUPER_ADMIN).exists()
        user_count = User.objects.count()
        
        return Response({
            'setup_complete': super_admin_exists,
            'super_admin_exists': super_admin_exists,
            'total_users': user_count
        })
