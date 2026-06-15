"""
Agency management views.
Super Admin endpoint for managing agencies (resellers/partners).
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from api.permissions import IsSuperAdmin
from tenants.models import Agency, AgencyStatus, AuditLog
from tenants.serializers import AgencySerializer, AgencyCreateSerializer
from notifications.services import NotificationService


class AgencyViewSet(viewsets.ModelViewSet):
    """
    ViewSet for agency management.
    
    🔴 SUPER ADMIN ONLY
    
    Endpoints:
    - GET /api/agencies/ - List all agencies
    - POST /api/agencies/ - Create new agency (with admin user)
    - GET /api/agencies/{id}/ - Get agency details
    - PUT/PATCH /api/agencies/{id}/ - Update agency
    - DELETE /api/agencies/{id}/ - Delete agency
    - POST /api/agencies/{id}/suspend/ - Suspend agency
    - POST /api/agencies/{id}/activate/ - Activate agency
    """
    queryset = Agency.objects.prefetch_related('tenants').all()
    permission_classes = [IsSuperAdmin]
    
    def get_serializer_class(self):
        if self.action == 'create':
            return AgencyCreateSerializer
        return AgencySerializer
    
    def perform_create(self, serializer):
        agency = serializer.save()
        
        AuditLog.log(
            action='agency.created',
            user=self.request.user,
            agency=agency,
            metadata={
                'agency_name': agency.name,
                'slug': agency.slug,
                'admin_email': self.request.data.get('admin_email')
            },
            request=self.request
        )
        
        # Notify super admins of new agency
        NotificationService.notify_on_new_agency(agency, created_by=self.request.user)
    
    def perform_update(self, serializer):
        agency = serializer.save()
        
        AuditLog.log(
            action='agency.updated',
            user=self.request.user,
            agency=agency,
            metadata={'updated_fields': list(serializer.validated_data.keys())},
            request=self.request
        )
    
    def perform_destroy(self, instance):
        agency_name = instance.name
        agency_id = str(instance.id)
        instance.delete()
        
        AuditLog.log(
            action='agency.deleted',
            user=self.request.user,
            metadata={'agency_id': agency_id, 'agency_name': agency_name},
            request=self.request
        )
    
    @action(detail=True, methods=['post'])
    def suspend(self, request, pk=None):
        """Suspend an agency and all its clients."""
        agency = self.get_object()
        agency.status = AgencyStatus.SUSPENDED
        agency.save()
        
        # Optionally suspend all agency's clients
        # agency.tenants.update(status=TenantStatus.SUSPENDED)
        
        AuditLog.log(
            action='agency.suspended',
            user=request.user,
            agency=agency,
            request=request
        )
        
        return Response({
            'message': f'Agency {agency.name} has been suspended',
            'agency': AgencySerializer(agency).data
        })
    
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate a suspended agency."""
        agency = self.get_object()
        agency.status = AgencyStatus.ACTIVE
        agency.save()
        
        AuditLog.log(
            action='agency.activated',
            user=request.user,
            agency=agency,
            request=request
        )
        
        return Response({
            'message': f'Agency {agency.name} has been activated',
            'agency': AgencySerializer(agency).data
        })
    
    @action(detail=True, methods=['get'])
    def clients(self, request, pk=None):
        """Get all clients (tenants) for this agency."""
        agency = self.get_object()
        from tenants.serializers import TenantSerializer
        tenants = agency.tenants.all()
        return Response(TenantSerializer(tenants, many=True).data)
