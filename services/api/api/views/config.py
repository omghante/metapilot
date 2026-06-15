"""
Tenant configuration views.
Handles encrypted API key management.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from api.permissions import CanManageAPIKeys, IsSuperAdmin
from api.views.base import TenantQuerysetMixin
from tenants.models import TenantConfig, AuditLog
from tenants.serializers import TenantConfigSerializer, TenantConfigCreateSerializer
from users.models import UserRole


class TenantConfigViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    """
    ViewSet for tenant API key configuration.
    
    🔐 SECURITY:
    - Never exposes decrypted values
    - Only Super Admin and Tenant Admin can manage
    - All operations are logged
    
    Endpoints:
    - GET /api/configs/ - List configs (masked values)
    - POST /api/configs/ - Add new config
    - GET /api/configs/{id}/ - Get config detail
    - PUT/PATCH /api/configs/{id}/ - Update config
    - DELETE /api/configs/{id}/ - Delete config
    - POST /api/configs/{id}/rotate/ - Rotate key
    """
    queryset = TenantConfig.objects.select_related('tenant').all()
    permission_classes = [CanManageAPIKeys]
    tenant_field = 'tenant'
    
    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update', 'rotate']:
            return TenantConfigCreateSerializer
        return TenantConfigSerializer
    
    def get_queryset(self):
        """Filter by tenant access."""
        queryset = super().get_queryset()
        user = self.request.user
        
        if user.role == UserRole.SUPER_ADMIN:
            if self.request.tenant:
                return queryset.filter(tenant=self.request.tenant)
            return queryset
        
        if user.role == UserRole.TENANT_ADMIN:
            return queryset.filter(tenant=user.tenant)
        
        return queryset.none()
    
    def perform_create(self, serializer):
        user = self.request.user
        
        # Tenant admin can only create for their tenant
        if user.role == UserRole.TENANT_ADMIN:
            config = serializer.save(tenant=user.tenant)
        else:
            config = serializer.save()
        
        AuditLog.log(
            action='config.created',
            user=user,
            tenant=config.tenant,
            metadata={
                'provider': config.provider,
                'key_name': config.key_name
            },
            request=self.request
        )
    
    def perform_update(self, serializer):
        config = serializer.save()
        
        AuditLog.log(
            action='config.updated',
            user=self.request.user,
            tenant=config.tenant,
            metadata={
                'config_id': str(config.id),
                'provider': config.provider,
                'key_name': config.key_name
            },
            request=self.request
        )
    
    def perform_destroy(self, instance):
        config_info = {
            'config_id': str(instance.id),
            'provider': instance.provider,
            'key_name': instance.key_name
        }
        tenant = instance.tenant
        instance.delete()
        
        AuditLog.log(
            action='config.deleted',
            user=self.request.user,
            tenant=tenant,
            metadata=config_info,
            request=self.request
        )
    
    @action(detail=True, methods=['post'])
    def rotate(self, request, pk=None):
        """
        Rotate an API key.
        
        POST /api/configs/{id}/rotate/
        {
            "value": "new_api_key_value"
        }
        """
        config = self.get_object()
        new_value = request.data.get('value')
        
        if not new_value:
            return Response(
                {'error': 'New value is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        config.set_value(new_value)
        config.save()
        
        AuditLog.log(
            action='config.rotated',
            user=request.user,
            tenant=config.tenant,
            metadata={
                'config_id': str(config.id),
                'provider': config.provider,
                'key_name': config.key_name
            },
            request=request
        )
        
        return Response({
            'message': 'API key rotated successfully',
            'config': TenantConfigSerializer(config, context={'request': request}).data
        })
