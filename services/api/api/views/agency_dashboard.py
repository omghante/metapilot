"""
Agency Dashboard views.
Endpoints for Agency Admins to view their assigned clients' data.
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from api.permissions import IsAgencyAdmin
from tenants.models import Tenant, TenantStatus, AuditLog
from tenants.serializers import TenantSerializer
from django.db.models import Count, Sum
from django.utils import timezone


class AgencyDashboardView(APIView):
    """
    Agency Dashboard Overview.
    
    GET /api/agency/dashboard/
    
    Returns:
    - Total assigned clients
    - Client stats (active, suspended)
    - Recent activity for agency's clients
    
    🟡 AGENCY ADMIN ONLY
    """
    permission_classes = [IsAgencyAdmin]
    
    def get(self, request):
        user = request.user
        agency = user.agency
        
        if not agency:
            return Response(
                {'error': 'No agency associated with this user'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get all clients assigned to this agency
        clients = Tenant.objects.filter(agency=agency)
        
        # Client stats
        total_clients = clients.count()
        active_clients = clients.filter(status=TenantStatus.ACTIVE).count()
        suspended_clients = clients.filter(status=TenantStatus.SUSPENDED).count()
        pending_clients = clients.filter(status=TenantStatus.PENDING).count()
        
        # Clients by plan
        clients_by_plan = list(
            clients.values('plan_type')
            .annotate(count=Count('id'))
            .order_by('plan_type')
        )
        
        # Recent activity for this agency's clients
        recent_logs = AuditLog.objects.filter(
            tenant__agency=agency
        ).select_related(
            'performed_by', 'tenant'
        ).order_by('-timestamp')[:10]
        
        recent_activity = [
            {
                'id': str(log.id),
                'action': log.action,
                'performed_by': log.performed_by.email if log.performed_by else None,
                'tenant': log.tenant.name if log.tenant else None,
                'timestamp': log.timestamp.isoformat()
            }
            for log in recent_logs
        ]
        
        # Today's stats
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        clients_today = clients.filter(created_at__gte=today_start).count()
        
        return Response({
            'agency': {
                'id': str(agency.id),
                'name': agency.name,
                'slug': agency.slug,
                'status': agency.status,
            },
            'overview': {
                'total_clients': total_clients,
                'active_clients': active_clients,
                'suspended_clients': suspended_clients,
                'pending_clients': pending_clients,
            },
            'today': {
                'new_clients': clients_today,
            },
            'clients_by_plan': clients_by_plan,
            'recent_activity': recent_activity,
        })


class AgencyClientsListView(APIView):
    """
    List all clients assigned to the agency.
    
    GET /api/agency/clients/
    
    Query params:
    - status: Filter by status (ACTIVE/SUSPENDED/PENDING)
    - plan_type: Filter by plan
    
    🟡 AGENCY ADMIN ONLY
    """
    permission_classes = [IsAgencyAdmin]
    
    def get(self, request):
        user = request.user
        agency = user.agency
        
        if not agency:
            return Response(
                {'error': 'No agency associated with this user'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get all clients assigned to this agency
        clients = Tenant.objects.filter(agency=agency)
        
        # Apply filters
        status_filter = request.query_params.get('status')
        plan_filter = request.query_params.get('plan_type')
        
        if status_filter:
            clients = clients.filter(status=status_filter)
        if plan_filter:
            clients = clients.filter(plan_type=plan_filter)
        
        # Order by created_at
        clients = clients.order_by('-created_at')
        
        return Response({
            'count': clients.count(),
            'results': TenantSerializer(clients, many=True).data
        })


class AgencyClientDetailView(APIView):
    """
    Get detailed info for a specific client assigned to the agency.
    
    GET /api/agency/clients/{client_id}/
    PATCH /api/agency/clients/{client_id}/ - Update client
    POST /api/agency/clients/{client_id}/suspend/ - Suspend client
    POST /api/agency/clients/{client_id}/activate/ - Activate client
    
    🟡 AGENCY ADMIN ONLY
    """
    permission_classes = [IsAgencyAdmin]
    
    def _get_client(self, request, client_id):
        """Helper to get client with agency validation."""
        user = request.user
        agency = user.agency
        
        if not agency:
            return None, Response(
                {'error': 'No agency associated with this user'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            client = Tenant.objects.get(id=client_id, agency=agency)
            return client, None
        except Tenant.DoesNotExist:
            return None, Response(
                {'error': 'Client not found or not assigned to your agency'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    def get(self, request, client_id):
        client, error = self._get_client(request, client_id)
        if error:
            return error
        
        # Get client stats (can be extended later with messaging stats)
        user_count = client.users.count()
        config_count = client.configs.filter(is_active=True).count()
        
        # Recent audit logs for this client
        recent_logs = AuditLog.objects.filter(
            tenant=client
        ).select_related('performed_by').order_by('-timestamp')[:10]
        
        return Response({
            'client': TenantSerializer(client).data,
            'stats': {
                'user_count': user_count,
                'config_count': config_count,
            },
            'recent_activity': [
                {
                    'id': str(log.id),
                    'action': log.action,
                    'performed_by': log.performed_by.email if log.performed_by else None,
                    'timestamp': log.timestamp.isoformat()
                }
                for log in recent_logs
            ]
        })
    
    def patch(self, request, client_id):
        """Update client details."""
        client, error = self._get_client(request, client_id)
        if error:
            return error
        
        # Allow updating limited fields
        allowed_fields = ['name', 'plan_type', 'monthly_message_limit']
        for field in allowed_fields:
            if field in request.data:
                setattr(client, field, request.data[field])
        
        client.save()
        
        # Log the action
        AuditLog.objects.create(
            action='tenant.updated',
            performed_by=request.user,
            tenant=client,
            agency=request.user.agency,
            details={'updated_fields': list(request.data.keys())}
        )
        
        return Response({
            'message': 'Client updated successfully',
            'client': TenantSerializer(client).data
        })


class AgencyClientSuspendView(APIView):
    """
    Suspend a client assigned to the agency.
    
    POST /api/agency/clients/{client_id}/suspend/
    
    🟡 AGENCY ADMIN ONLY
    """
    permission_classes = [IsAgencyAdmin]
    
    def post(self, request, client_id):
        user = request.user
        agency = user.agency
        
        if not agency:
            return Response(
                {'error': 'No agency associated with this user'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            client = Tenant.objects.get(id=client_id, agency=agency)
        except Tenant.DoesNotExist:
            return Response(
                {'error': 'Client not found or not assigned to your agency'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if client.status == TenantStatus.SUSPENDED:
            return Response(
                {'error': 'Client is already suspended'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        client.status = TenantStatus.SUSPENDED
        client.save()
        
        # Log the action
        AuditLog.objects.create(
            action='tenant.suspended',
            performed_by=request.user,
            tenant=client,
            agency=agency,
            details={'previous_status': 'ACTIVE'}
        )
        
        return Response({
            'message': 'Client suspended successfully',
            'client': TenantSerializer(client).data
        })


class AgencyClientActivateView(APIView):
    """
    Activate a suspended client assigned to the agency.
    
    POST /api/agency/clients/{client_id}/activate/
    
    🟡 AGENCY ADMIN ONLY
    """
    permission_classes = [IsAgencyAdmin]
    
    def post(self, request, client_id):
        user = request.user
        agency = user.agency
        
        if not agency:
            return Response(
                {'error': 'No agency associated with this user'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            client = Tenant.objects.get(id=client_id, agency=agency)
        except Tenant.DoesNotExist:
            return Response(
                {'error': 'Client not found or not assigned to your agency'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if client.status == TenantStatus.ACTIVE:
            return Response(
                {'error': 'Client is already active'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        previous_status = client.status
        client.status = TenantStatus.ACTIVE
        client.save()
        
        # Log the action
        AuditLog.objects.create(
            action='tenant.activated',
            performed_by=request.user,
            tenant=client,
            agency=agency,
            details={'previous_status': previous_status}
        )
        
        return Response({
            'message': 'Client activated successfully',
            'client': TenantSerializer(client).data
        })

