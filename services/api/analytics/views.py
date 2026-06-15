"""
Analytics views for quota management.
"""
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework import serializers
from api.permissions import IsSuperAdminOrAgencyAdmin
from analytics.models import ClientQuota
from tenants.models import Tenant


class ClientQuotaSerializer(serializers.ModelSerializer):
    """Serializer for client quota details."""
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)
    usage_percentage_daily = serializers.SerializerMethodField()
    usage_percentage_monthly = serializers.SerializerMethodField()
    
    class Meta:
        model = ClientQuota
        fields = [
            'id', 'tenant', 'tenant_name',
            'daily_message_limit', 'monthly_message_limit',
            'messages_sent_today', 'messages_sent_this_month',
            'usage_percentage_daily', 'usage_percentage_monthly',
            'last_daily_reset', 'last_monthly_reset', 'updated_at'
        ]
        read_only_fields = [
            'id', 'messages_sent_today', 'messages_sent_this_month',
            'last_daily_reset', 'last_monthly_reset', 'updated_at'
        ]
    
    def get_usage_percentage_daily(self, obj):
        if obj.daily_message_limit > 0:
            return round((obj.messages_sent_today / obj.daily_message_limit) * 100, 1)
        return 0
    
    def get_usage_percentage_monthly(self, obj):
        if obj.monthly_message_limit > 0:
            return round((obj.messages_sent_this_month / obj.monthly_message_limit) * 100, 1)
        return 0


class QuotaUpdateSerializer(serializers.Serializer):
    """Serializer for updating quota limits."""
    daily_message_limit = serializers.IntegerField(min_value=0, required=False)
    monthly_message_limit = serializers.IntegerField(min_value=0, required=False)


class ClientQuotaViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing client quotas.
    
    🔴 SUPER ADMIN - Can manage ALL client quotas
    🟠 AGENCY ADMIN - Can manage quotas for their assigned clients only
    
    Endpoints:
    - GET /api/quotas/ - List quotas
    - GET /api/quotas/{id}/ - Get quota details
    - PATCH /api/quotas/{id}/ - Update limits
    - POST /api/quotas/{id}/reset_daily/ - Reset daily counter
    - POST /api/quotas/{id}/reset_monthly/ - Reset monthly counter
    """
    serializer_class = ClientQuotaSerializer
    http_method_names = ['get', 'patch', 'post']
    
    def get_permissions(self):
        # Allow Super Admin and Agency Admin
        return [IsSuperAdminOrAgencyAdmin()]
    
    def get_queryset(self):
        user = self.request.user
        
        # Super admin sees all
        if user.is_super_admin:
            return ClientQuota.objects.select_related('tenant').all()
        
        # Agency admin sees only their assigned clients
        if user.is_agency_admin and user.agency:
            return ClientQuota.objects.select_related('tenant').filter(
                tenant__agency=user.agency
            )
        
        return ClientQuota.objects.none()
    
    def partial_update(self, request, *args, **kwargs):
        """Update quota limits (daily/monthly)."""
        quota = self.get_object()
        serializer = QuotaUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Update limits
        if 'daily_message_limit' in serializer.validated_data:
            quota.daily_message_limit = serializer.validated_data['daily_message_limit']
        if 'monthly_message_limit' in serializer.validated_data:
            quota.monthly_message_limit = serializer.validated_data['monthly_message_limit']
        
        quota.save()
        return Response(ClientQuotaSerializer(quota).data)
    
    @action(detail=True, methods=['post'])
    def reset_daily(self, request, pk=None):
        """Reset daily usage counter to 0."""
        quota = self.get_object()
        quota.messages_sent_today = 0
        quota.save()
        return Response({
            'message': f'Daily counter reset for {quota.tenant.name}',
            'data': ClientQuotaSerializer(quota).data
        })
    
    @action(detail=True, methods=['post'])
    def reset_monthly(self, request, pk=None):
        """Reset monthly usage counter to 0."""
        quota = self.get_object()
        quota.messages_sent_this_month = 0
        quota.save()
        return Response({
            'message': f'Monthly counter reset for {quota.tenant.name}',
            'data': ClientQuotaSerializer(quota).data
        })


class ClientQuotaByTenantView(viewsets.ViewSet):
    """
    Get or create quota for a specific client.
    
    GET /api/clients/{client_id}/quota/
    PATCH /api/clients/{client_id}/quota/
    """
    
    def get_permissions(self):
        return [IsSuperAdminOrAgencyAdmin()]
    
    def retrieve(self, request, client_id=None):
        """Get quota for a specific client."""
        user = request.user
        
        # Get tenant
        try:
            if user.is_super_admin:
                tenant = Tenant.objects.get(id=client_id)
            elif user.is_agency_admin and user.agency:
                tenant = Tenant.objects.get(id=client_id, agency=user.agency)
            else:
                return Response(
                    {'error': 'Access denied'},
                    status=status.HTTP_403_FORBIDDEN
                )
        except Tenant.DoesNotExist:
            return Response(
                {'error': 'Client not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get or create quota
        quota, created = ClientQuota.objects.get_or_create(
            tenant=tenant,
            defaults={
                'daily_message_limit': 100,
                'monthly_message_limit': 1000
            }
        )
        
        return Response(ClientQuotaSerializer(quota).data)
    
    def partial_update(self, request, client_id=None):
        """Update quota for a specific client."""
        user = request.user
        
        # Get tenant
        try:
            if user.is_super_admin:
                tenant = Tenant.objects.get(id=client_id)
            elif user.is_agency_admin and user.agency:
                tenant = Tenant.objects.get(id=client_id, agency=user.agency)
            else:
                return Response(
                    {'error': 'Access denied'},
                    status=status.HTTP_403_FORBIDDEN
                )
        except Tenant.DoesNotExist:
            return Response(
                {'error': 'Client not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get or create quota
        quota, created = ClientQuota.objects.get_or_create(
            tenant=tenant,
            defaults={
                'daily_message_limit': 100,
                'monthly_message_limit': 1000
            }
        )
        
        # Update limits
        serializer = QuotaUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        if 'daily_message_limit' in serializer.validated_data:
            quota.daily_message_limit = serializer.validated_data['daily_message_limit']
        if 'monthly_message_limit' in serializer.validated_data:
            quota.monthly_message_limit = serializer.validated_data['monthly_message_limit']
        
        quota.save()
        
        return Response({
            'message': f'Quota updated for {tenant.name}',
            'data': ClientQuotaSerializer(quota).data
        })
