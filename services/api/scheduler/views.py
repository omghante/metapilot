"""
DRF views for scheduler API endpoints.
"""
import logging
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone

from api.permissions import IsTenantMember, TenantAccessPermission
from .models import SchedulerJob, SchedulerJobStatus
from .serializers import (
    SchedulerJobSerializer,
    SchedulerJobListSerializer,
    SchedulerJobCreateSerializer,
    SchedulerJobStatusSerializer,
    SchedulerStatsSerializer,
    SchedulerJobRecipientSerializer
)
from .services.scheduler_service import SchedulerService

logger = logging.getLogger(__name__)


class SchedulerJobViewSet(viewsets.ModelViewSet):
    """
    ViewSet for scheduler job management.

    Endpoints:
    - GET /api/scheduler/jobs/ - List jobs for tenant
    - POST /api/scheduler/jobs/ - Create new job
    - GET /api/scheduler/jobs/{id}/ - Get job details
    - DELETE /api/scheduler/jobs/{id}/ - Cancel pending job
    - GET /api/scheduler/jobs/{id}/status/ - Get job status
    - POST /api/scheduler/jobs/{id}/retry/ - Retry failed recipients
    - GET /api/scheduler/jobs/stats/ - Get scheduler statistics
    """
    permission_classes = [IsAuthenticated, IsTenantMember, TenantAccessPermission]

    def get_queryset(self):
        """Return jobs for the user's tenant."""
        user = self.request.user

        if user.is_super_admin:
            return SchedulerJob.objects.all().order_by('-scheduled_time')

        if user.tenant:
            return SchedulerJob.objects.filter(
                tenant=user.tenant
            ).order_by('-scheduled_time')

        return SchedulerJob.objects.none()

    def get_serializer_class(self):
        """Return appropriate serializer for action."""
        if self.action == 'create':
            return SchedulerJobCreateSerializer
        if self.action == 'list':
            return SchedulerJobListSerializer
        if self.action == 'status':
            return SchedulerJobStatusSerializer
        if self.action == 'stats':
            return SchedulerStatsSerializer
        return SchedulerJobSerializer

    def create(self, request, *args, **kwargs):
        """Create a new scheduler job."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        user = request.user
        tenant = user.tenant

        if not tenant and not user.is_super_admin:
            return Response(
                {'error': 'No tenant associated with user'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Get campaign if provided
        campaign = None
        if data.get('campaign_id'):
            from campaigns.models import Campaign
            try:
                campaign = Campaign.objects.get(id=data['campaign_id'], tenant=tenant)
            except Campaign.DoesNotExist:
                return Response(
                    {'error': 'Campaign not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

        # Create job
        service = SchedulerService()
        job = service.create_job(
            tenant=tenant,
            template_name=data['template_name'],
            scheduled_time=data['scheduled_time'],
            recipients=data['recipients'],
            template_id=data.get('template_id'),
            language_code=data.get('language_code', 'en_US'),
            header_image_url=data.get('header_image_url', ''),
            body_params=data.get('body_params', []),
            button_params=data.get('button_params', []),
            campaign=campaign,
            priority=data.get('priority', 5),
            max_retries=data.get('max_retries', 3),
            template_type=data.get('template_type', 'standard'),
            header_data=data.get('header_data'),
            cards_json=data.get('cards_json'),
        )

        output_serializer = SchedulerJobSerializer(job)
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        """Cancel a pending job."""
        job = self.get_object()

        if job.status not in [SchedulerJobStatus.PENDING]:
            return Response(
                {'error': f'Cannot cancel job with status: {job.status}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        job.status = SchedulerJobStatus.CANCELLED
        job.completed_at = timezone.now()
        job.save()

        return Response({'message': 'Job cancelled successfully'})

    @action(detail=True, methods=['get'], url_path='status')
    def status(self, request, pk=None):
        """Get job status for polling."""
        job = self.get_object()
        serializer = SchedulerJobStatusSerializer(job)
        return Response(serializer.data)

    @action(detail=True, methods=['post'], url_path='retry')
    def retry(self, request, pk=None):
        """Retry failed recipients for a job."""
        job = self.get_object()

        if job.status not in [SchedulerJobStatus.FAILED, SchedulerJobStatus.PARTIAL_FAILURE]:
            return Response(
                {'error': 'Can only retry failed or partial failure jobs'},
                status=status.HTTP_400_BAD_REQUEST
            )

        from .tasks import retry_failed_recipients
        retry_failed_recipients.delay(str(job.id))

        return Response({
            'message': 'Retry scheduled',
            'job_id': str(job.id)
        })

    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        """Get scheduler statistics."""
        user = request.user
        tenant_id = str(user.tenant.id) if user.tenant else None

        service = SchedulerService()
        stats = service.get_stats(tenant_id=tenant_id)

        serializer = SchedulerStatsSerializer(data=stats)
        serializer.is_valid()
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='recipients')
    def recipients(self, request, pk=None):
        """Get job recipients with pagination."""
        job = self.get_object()

        # Get query params
        status_filter = request.query_params.get('status')

        recipients = job.recipients.all()
        if status_filter:
            recipients = recipients.filter(status=status_filter)

        # Pagination
        page = self.paginate_queryset(recipients)
        if page is not None:
            serializer = SchedulerJobRecipientSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = SchedulerJobRecipientSerializer(recipients, many=True)
        return Response(serializer.data)
