"""
Tenant Dashboard views for client analytics.
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta

from campaigns.models import (
    Campaign, CampaignMessage, ScheduledMessage,
    CampaignStatus, ScheduledMessageStatus
)
from scheduler.models import SchedulerJobRecipient, RecipientStatus
from tenants.models import AuditLog


class MyDashboardView(APIView):
    """
    Tenant Dashboard Analytics.
    
    GET /api/my-dashboard/
    
    Returns message and campaign analytics for the authenticated user's tenant.
    Available to TENANT_ADMIN and TENANT_USER roles.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        
        # Ensure user belongs to a tenant
        if not user.tenant:
            return Response(
                {'error': 'User does not belong to a tenant'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        tenant = user.tenant
        
        # ============================================
        # MESSAGE ANALYTICS (from SchedulerJobRecipient — actual delivery tracking)
        # ============================================
        message_stats = SchedulerJobRecipient.objects.filter(
            job__tenant=tenant
        ).aggregate(
            total=Count('id'),
            pending=Count('id', filter=Q(status=RecipientStatus.PENDING)),
            sent=Count('id', filter=Q(status=RecipientStatus.SENT)),
            failed=Count('id', filter=Q(status=RecipientStatus.FAILED)),
        )
        
        # ============================================
        # CAMPAIGN ANALYTICS
        # ============================================
        campaign_stats = Campaign.objects.filter(tenant=tenant).aggregate(
            total=Count('id'),
            draft=Count('id', filter=Q(status=CampaignStatus.DRAFT)),
            scheduled=Count('id', filter=Q(status=CampaignStatus.SCHEDULED)),
            active=Count('id', filter=Q(status=CampaignStatus.ACTIVE)),
            paused=Count('id', filter=Q(status=CampaignStatus.PAUSED)),
            completed=Count('id', filter=Q(status=CampaignStatus.COMPLETED)),
            cancelled=Count('id', filter=Q(status=CampaignStatus.CANCELLED)),
        )
        
        # ============================================
        # RECENT CAMPAIGNS
        # ============================================
        recent_campaigns = Campaign.objects.filter(
            tenant=tenant
        ).order_by('-created_at')[:5]
        
        recent_campaigns_data = [
            {
                'id': str(c.id),
                'name': c.name,
                'status': c.status,
                'created_at': c.created_at.isoformat() if c.created_at else None,
                'recipient_count': c.recipient_count,
                'sent_count': c.sent_count,
            }
            for c in recent_campaigns
        ]
        
        # ============================================
        # MESSAGE TREND (Last 7 days)
        # ============================================
        now = timezone.now()
        week_ago = now - timedelta(days=7)
        
        # Daily message counts
        from django.db.models.functions import TruncDate
        
        daily_messages = list(SchedulerJobRecipient.objects.filter(
            job__tenant=tenant,
            created_at__gte=week_ago
        ).annotate(
            date=TruncDate('created_at')
        ).values('date').annotate(
            count=Count('id')
        ).order_by('date'))
        
        # Create a dict with existing counts
        existing_counts = {
            item['date']: item['count'] 
            for item in daily_messages if item['date']
        }
        
        # Generate all 7 days with 0 for missing days
        trend_data = []
        for i in range(6, -1, -1):
            day = (now - timedelta(days=i)).date()
            trend_data.append({
                'date': day.isoformat(),
                'count': existing_counts.get(day, 0)
            })
        
        # Log dashboard access for audit trail
        AuditLog.log(
            action='tenant.view_dashboard',
            user=user,
            tenant=tenant,
            metadata={'tenant_id': str(tenant.id)},
            request=request
        )
        
        return Response({
            'messages': {
                'total': message_stats['total'] or 0,
                'pending': message_stats['pending'] or 0,
                'sent': message_stats['sent'] or 0,
                'failed': message_stats['failed'] or 0,
            },
            'campaigns': {
                'total': campaign_stats['total'] or 0,
                'draft': campaign_stats['draft'] or 0,
                'scheduled': campaign_stats['scheduled'] or 0,
                'active': campaign_stats['active'] or 0,
                'paused': campaign_stats['paused'] or 0,
                'completed': campaign_stats['completed'] or 0,
                'cancelled': campaign_stats['cancelled'] or 0,
            },
            'recent_campaigns': recent_campaigns_data,
            'message_trend': trend_data,
        })
