"""
Dashboard views for Super Admin overview.
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from api.permissions import IsSuperAdmin
from tenants.models import Agency, Tenant, TenantConfig, AuditLog, TenantStatus, AgencyStatus
from users.models import User, UserRole
from django.db.models import Count
from django.utils import timezone
from datetime import timedelta


class DashboardOverviewView(APIView):
    """
    Super Admin Dashboard Overview.
    
    GET /api/dashboard/
    
    Returns:
    - Total counts (agencies, clients, users)
    - Active vs Suspended stats
    - Recent activity
    """
    permission_classes = [IsSuperAdmin]
    
    def get(self, request):
        # Counts
        total_agencies = Agency.objects.count()
        active_agencies = Agency.objects.filter(status=AgencyStatus.ACTIVE).count()
        
        total_clients = Tenant.objects.count()
        active_clients = Tenant.objects.filter(status=TenantStatus.ACTIVE).count()
        suspended_clients = Tenant.objects.filter(status=TenantStatus.SUSPENDED).count()
        
        total_users = User.objects.exclude(role=UserRole.SUPER_ADMIN).count()
        active_users = User.objects.filter(is_active=True).exclude(role=UserRole.SUPER_ADMIN).count()
        
        # API configs
        total_api_configs = TenantConfig.objects.filter(is_active=True).count()
        
        # Clients by plan
        clients_by_plan = list(
            Tenant.objects.values('plan_type')
            .annotate(count=Count('id'))
            .order_by('plan_type')
        )
        
        # Recent audit logs
        recent_logs = AuditLog.objects.select_related(
            'performed_by', 'tenant', 'agency'
        ).order_by('-timestamp')[:10]
        
        recent_activity = [
            {
                'id': str(log.id),
                'action': log.action,
                'performed_by': log.performed_by.email if log.performed_by else None,
                'tenant': log.tenant.name if log.tenant else None,
                'agency': log.agency.name if log.agency else None,
                'timestamp': log.timestamp.isoformat()
            }
            for log in recent_logs
        ]
        
        # Today's stats
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        clients_today = Tenant.objects.filter(created_at__gte=today_start).count()
        users_today = User.objects.filter(created_at__gte=today_start).count()
        
        return Response({
            'overview': {
                'total_agencies': total_agencies,
                'active_agencies': active_agencies,
                'total_clients': total_clients,
                'active_clients': active_clients,
                'suspended_clients': suspended_clients,
                'total_users': total_users,
                'active_users': active_users,
                'total_api_configs': total_api_configs,
            },
            'today': {
                'new_clients': clients_today,
                'new_users': users_today,
            },
            'clients_by_plan': clients_by_plan,
            'recent_activity': recent_activity,
        })


class AuditLogListView(APIView):
    """
    Audit Log listing for Super Admin.
    
    GET /api/audit-logs/
    
    Query params:
    - tenant_id: Filter by tenant
    - agency_id: Filter by agency
    - action: Filter by action type
    - limit: Number of logs (default 50)
    """
    permission_classes = [IsSuperAdmin]
    
    def get(self, request):
        queryset = AuditLog.objects.select_related(
            'performed_by', 'tenant', 'agency'
        ).order_by('-timestamp')
        
        # Filters
        tenant_id = request.query_params.get('tenant_id')
        agency_id = request.query_params.get('agency_id')
        action = request.query_params.get('action')
        limit = int(request.query_params.get('limit', 50))
        
        if tenant_id:
            queryset = queryset.filter(tenant_id=tenant_id)
        if agency_id:
            queryset = queryset.filter(agency_id=agency_id)
        if action:
            queryset = queryset.filter(action__icontains=action)
        
        logs = queryset[:limit]
        
        return Response({
            'count': queryset.count(),
            'results': [
                {
                    'id': str(log.id),
                    'action': log.action,
                    'performed_by': log.performed_by.email if log.performed_by else None,
                    'tenant': log.tenant.name if log.tenant else None,
                    'tenant_id': str(log.tenant_id) if log.tenant_id else None,
                    'agency': log.agency.name if log.agency else None,
                    'metadata': log.metadata,
                    'ip_address': log.ip_address,
                    'timestamp': log.timestamp.isoformat()
                }
                for log in logs
            ]
        })

class DashboardAnalyticsView(APIView):
    """
    Analytics for Message Traffic (Peak Time Analysis).
    
    GET /api/dashboard/analytics/
    Params: range = 'day' | 'week' | 'month' (default: 'week')
    """
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        time_range = request.query_params.get('range', 'week')
        now = timezone.now()
        
        # Determine date range and truncation level
        if time_range == 'day':
            start_date = now - timedelta(hours=24)
            trunc_func = 'hour'
            step_delta = timedelta(hours=1)
        elif time_range == 'month':
            start_date = now - timedelta(days=365)
            trunc_func = 'month'
            step_delta = None # Special handling
        else:  # week
            start_date = now - timedelta(days=7)
            trunc_func = 'hour'
            step_delta = timedelta(hours=4) # 4-hour buckets for smoother curve
            
        from django.db.models.functions import TruncHour, TruncDay, TruncMonth
        from campaigns.models import ScheduledMessage, CampaignMessage
        
        if trunc_func == 'hour':
            TruncClass = TruncHour
        elif trunc_func == 'month':
            TruncClass = TruncMonth
        else:
            TruncClass = TruncDay
        
        # 1. Scheduled Messages (Campaigns)
        sched_data = list(ScheduledMessage.objects.filter(
            created_at__gte=start_date
        ).annotate(
            period=TruncClass('created_at')
        ).values('period').annotate(count=Count('id')).order_by('period'))
        
        # 2. Campaign Messages (Direct)
        direct_data = list(CampaignMessage.objects.filter(
            created_at__gte=start_date
        ).annotate(
            period=TruncClass('created_at')
        ).values('period').annotate(count=Count('id')).order_by('period'))
        
        # Prepare buckets for zero-filling
        merged_data = {}
        current = start_date
        
        # Align start date to bucket
        if trunc_func == 'month':
            current = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif trunc_func == 'hour':
            current = current.replace(minute=0, second=0, microsecond=0)
            if step_delta and step_delta.seconds == 14400: # 4 hours
                 current = current.replace(hour=(current.hour // 4) * 4)
        else: # day
            current = current.replace(hour=0, minute=0, second=0, microsecond=0)
            
        while current <= now:
            merged_data[current.isoformat()] = 0
            # Increment
            if trunc_func == 'month':
                # Add ~1 month safe logic
                next_month = current.month + 1 if current.month < 12 else 1
                next_year = current.year + 1 if current.month == 12 else current.year
                current = current.replace(year=next_year, month=next_month)
            else:
                current += step_delta

        for entry in sched_data + direct_data:
            # Entry 'period' is a datetime, ensure it matches bucket key
            if not entry['period']: continue
            
            p = entry['period']
            
            # Apply custom bucketing if needed (e.g. 4-hour for week)
            if time_range == 'week':
                 p = p.replace(hour=(p.hour // 4) * 4, minute=0, second=0, microsecond=0)
            
            period_str = p.isoformat()
            
            # Only update if within range (Trunc might include boundary logic)
            if period_str in merged_data:
                merged_data[period_str] += entry['count']
            
        # Format for frontend
        results = [
            {'time': k, 'count': v} 
            for k, v in merged_data.items()
        ]
        results.sort(key=lambda x: x['time'])
        
        # Calculate Peak
        peak_volume = 0
        peak_time = None
        total_volume = 0
        
        for item in results:
            total_volume += item['count']
            if item['count'] > peak_volume:
                peak_volume = item['count']
                peak_time = item['time']
                
        return Response({
            'range': time_range,
            'data': results,
            'summary': {
                'peak_volume': peak_volume,
                'peak_time': peak_time,
                'total_volume': total_volume
            }
        })
