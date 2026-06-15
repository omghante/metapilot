"""
Tenant (Client) management views.
Super Admin endpoint for managing tenants/clients.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Count

from api.permissions import IsSuperAdminOrAgencyAdmin, IsTenantAdmin
from tenants.models import Tenant, TenantStatus, TenantConfig, AuditLog, ConfigProvider
from tenants.serializers import (
    TenantSerializer, TenantCreateSerializer, 
    TenantUpdateSerializer, TenantConfigSerializer
)
from users.models import UserRole
from notifications.services import NotificationService


class TenantViewSet(viewsets.ModelViewSet):
    """
    ViewSet for tenant (client) management.
    
    🔴 SUPER ADMIN: Full access to all tenants
    🟡 AGENCY ADMIN: Access to tenants under their agency
    
    Endpoints:
    - GET /api/tenants/ - List all tenants
    - POST /api/tenants/ - Create new tenant (with admin user + API keys)
    - GET /api/tenants/{id}/ - Get tenant details
    - PUT/PATCH /api/tenants/{id}/ - Update tenant
    - DELETE /api/tenants/{id}/ - Delete tenant
    - POST /api/tenants/{id}/suspend/ - Suspend tenant
    - POST /api/tenants/{id}/activate/ - Activate tenant
    - GET /api/tenants/{id}/configs/ - Get tenant's API configs
    - POST /api/tenants/{id}/add-config/ - Add API config
    """
    permission_classes = [IsSuperAdminOrAgencyAdmin]
    
    def get_serializer_class(self):
        if self.action == 'create':
            return TenantCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return TenantUpdateSerializer
        return TenantSerializer
    
    def get_queryset(self):
        """
        Return tenants with optimized queries.
        - select_related for agency FK
        - annotate user_count to avoid N+1
        """
        queryset = Tenant.objects.select_related(
            'agency'
        ).annotate(
            _user_count=Count('users', distinct=True),
            _campaign_count=Count('campaigns', distinct=True)
        ).order_by('-created_at')
        
        user = self.request.user
        
        # Super admin sees all
        if user.role == UserRole.SUPER_ADMIN:
            return queryset
        
        # Agency admin sees only their agency's clients
        if user.role == UserRole.AGENCY_ADMIN and user.agency:
            return queryset.filter(agency=user.agency)
        
        return queryset.none()
    
    def perform_create(self, serializer):
        tenant = serializer.save()
        
        AuditLog.log(
            action='tenant.created',
            user=self.request.user,
            tenant=tenant,
            agency=tenant.agency,
            metadata={
                'tenant_name': tenant.name,
                'slug': tenant.slug,
                'admin_email': self.request.data.get('admin_email'),
                'plan_type': tenant.plan_type
            },
            request=self.request
        )
        
        # Notify super admins and agency admins of new client
        NotificationService.notify_on_new_client(tenant, created_by=self.request.user)
    
    def perform_update(self, serializer):
        tenant = serializer.save()
        
        AuditLog.log(
            action='tenant.updated',
            user=self.request.user,
            tenant=tenant,
            metadata={'updated_fields': list(serializer.validated_data.keys())},
            request=self.request
        )
    
    def perform_destroy(self, instance):
        tenant_name = instance.name
        tenant_id = str(instance.id)
        instance.delete()
        
        AuditLog.log(
            action='tenant.deleted',
            user=self.request.user,
            metadata={'tenant_id': tenant_id, 'tenant_name': tenant_name},
            request=self.request
        )
    
    @action(detail=True, methods=['post'])
    def suspend(self, request, pk=None):
        """Suspend a tenant (disable all access)."""
        tenant = self.get_object()
        tenant.status = TenantStatus.SUSPENDED
        tenant.save()
        
        AuditLog.log(
            action='tenant.suspended',
            user=request.user,
            tenant=tenant,
            request=request
        )
        
        return Response({
            'message': f'Tenant {tenant.name} has been suspended',
            'tenant': TenantSerializer(tenant).data
        })
    
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate a suspended tenant."""
        tenant = self.get_object()
        tenant.status = TenantStatus.ACTIVE
        tenant.save()
        
        AuditLog.log(
            action='tenant.activated',
            user=request.user,
            tenant=tenant,
            request=request
        )
        
        return Response({
            'message': f'Tenant {tenant.name} has been activated',
            'tenant': TenantSerializer(tenant).data
        })
    
    @action(detail=True, methods=['get'])
    def configs(self, request, pk=None):
        """Get all API configs for this tenant (masked values)."""
        tenant = self.get_object()
        configs = TenantConfig.objects.filter(tenant=tenant)
        return Response(TenantConfigSerializer(configs, many=True, context={'request': request}).data)
    
    @action(detail=True, methods=['post'], url_path='add-config')
    def add_config(self, request, pk=None):
        """
        Add a new API config to tenant.
        
        Request body:
        {
            "provider": "META_WHATSAPP",
            "key_name": "access_token",
            "value": "your_secret_token"
        }
        """
        tenant = self.get_object()
        
        provider = request.data.get('provider', ConfigProvider.META_WHATSAPP)
        key_name = request.data.get('key_name')
        value = request.data.get('value')
        
        if not key_name or not value:
            return Response(
                {'error': 'key_name and value are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if config already exists
        existing = TenantConfig.objects.filter(
            tenant=tenant,
            provider=provider,
            key_name=key_name
        ).first()
        
        if existing:
            # Update existing
            existing.set_value(value)
            existing.is_active = True
            existing.save()
            config = existing
            action_type = 'config.updated'
        else:
            # Create new
            config = TenantConfig(
                tenant=tenant,
                provider=provider,
                key_name=key_name
            )
            config.set_value(value)
            config.save()
            action_type = 'config.created'
        
        AuditLog.log(
            action=action_type,
            user=request.user,
            tenant=tenant,
            metadata={'provider': provider, 'key_name': key_name},
            request=request
        )
        
        return Response({
            'message': f'Config {key_name} has been added/updated',
            'config': TenantConfigSerializer(config, context={'request': request}).data
        })
    
    @action(detail=True, methods=['get'])
    def users(self, request, pk=None):
        """Get all users for this tenant."""
        tenant = self.get_object()
        from users.serializers import UserSerializer
        users = tenant.users.all()
        return Response(UserSerializer(users, many=True).data)
    
    @action(detail=True, methods=['get'])
    def stats(self, request, pk=None):
        """Get usage stats for this tenant."""
        tenant = self.get_object()
        
        # Calculate actual usage
        from campaigns.models import ScheduledMessage, ScheduledMessageStatus, CampaignMessage
        
        scheduled_msgs_count = ScheduledMessage.objects.filter(
            campaign__tenant=tenant
        ).count()
        
        campaign_msgs_count = CampaignMessage.objects.filter(
            campaign__tenant=tenant
        ).count()
        
        messages_used = scheduled_msgs_count + campaign_msgs_count
        
        return Response({
            'tenant_id': str(tenant.id),
            'name': tenant.name,
            'user_count': tenant.user_count,
            'config_count': tenant.configs.filter(is_active=True).count(),
            'plan_type': tenant.plan_type,
            'monthly_message_limit': tenant.monthly_message_limit,
            'active_users_limit': tenant.active_users_limit,
            'messages_used': messages_used,
            'messages_remaining': max(0, tenant.monthly_message_limit - messages_used)
        })
