"""
User management views.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from api.permissions import IsTenantAdmin, TenantAccessPermission
from api.views.base import TenantQuerysetMixin
from users.serializers import (
    UserSerializer, UserCreateSerializer, 
    UserUpdateSerializer, ChangePasswordSerializer
)
from tenants.models import AuditLog
from users.models import UserRole
from notifications.services import NotificationService

User = get_user_model()


class UserViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    """
    ViewSet for user management.
    
    🔵 TENANT ADMIN: Can manage users in own tenant
    🔴 SUPER ADMIN: Can manage all users
    
    Endpoints:
    - GET /api/users/ - List users
    - POST /api/users/ - Create user
    - GET /api/users/{id}/ - Get user details
    - PUT/PATCH /api/users/{id}/ - Update user
    - DELETE /api/users/{id}/ - Delete user
    - POST /api/users/{id}/change-password/ - Change password
    """
    queryset = User.objects.select_related('tenant').all()
    permission_classes = [IsTenantAdmin, TenantAccessPermission]
    tenant_field = 'tenant'
    
    def get_serializer_class(self):
        if self.action == 'create':
            return UserCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return UserUpdateSerializer
        elif self.action == 'change_password':
            return ChangePasswordSerializer
        return UserSerializer
    
    def get_queryset(self):
        """
        Filter users by tenant.
        Super admin sees all, tenant admin sees own tenant's users.
        """
        queryset = super().get_queryset()
        user = self.request.user
        
        # Super admin with X-Tenant-ID header filter
        if user.role == UserRole.SUPER_ADMIN:
            if self.request.tenant:
                return queryset.filter(tenant=self.request.tenant)
            return queryset
        
        # Tenant admin only sees own tenant's users
        if user.role == UserRole.TENANT_ADMIN:
            return queryset.filter(tenant=user.tenant)
        
        return queryset.none()
    
    def perform_create(self, serializer):
        # If tenant admin, force their tenant
        user = self.request.user
        if user.role == UserRole.TENANT_ADMIN:
            new_user = serializer.save(tenant=user.tenant)
        else:
            new_user = serializer.save()
        
        AuditLog.log(
            action='user.created',
            user=user,
            tenant=new_user.tenant,
            metadata={'new_user_id': str(new_user.id), 'email': new_user.email},
            request=self.request
        )
        
        # Notify tenant admins of new team member
        NotificationService.notify_on_new_user_added(new_user, added_by=user)
    
    def perform_update(self, serializer):
        updated_user = serializer.save()
        
        AuditLog.log(
            action='user.updated',
            user=self.request.user,
            tenant=updated_user.tenant,
            metadata={
                'updated_user_id': str(updated_user.id),
                'updated_fields': list(serializer.validated_data.keys())
            },
            request=self.request
        )
    
    def perform_destroy(self, instance):
        user_id = str(instance.id)
        user_email = instance.email
        tenant = instance.tenant
        instance.delete()
        
        AuditLog.log(
            action='user.deleted',
            user=self.request.user,
            tenant=tenant,
            metadata={'deleted_user_id': user_id, 'email': user_email},
            request=self.request
        )
    
    @action(detail=True, methods=['post'])
    def change_password(self, request, pk=None):
        """Change user password."""
        target_user = self.get_object()
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={'request': request, 'user': target_user}
        )
        serializer.is_valid(raise_exception=True)
        
        target_user.set_password(serializer.validated_data['new_password'])
        target_user.save()
        
        AuditLog.log(
            action='user.password_changed',
            user=request.user,
            tenant=target_user.tenant,
            metadata={'target_user_id': str(target_user.id)},
            request=request
        )
        
        return Response({'message': 'Password changed successfully'})
