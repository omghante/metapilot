"""
CampaignViewSet — CRUD and lifecycle management for campaigns.

Endpoints:
    GET    /api/campaigns/              List tenant campaigns
    POST   /api/campaigns/              Create campaign
    GET    /api/campaigns/{id}/         Get campaign details
    PUT    /api/campaigns/{id}/         Update campaign
    DELETE /api/campaigns/{id}/         Delete campaign
    POST   /api/campaigns/{id}/schedule/ Schedule campaign
    POST   /api/campaigns/{id}/start/   Start campaign immediately
    POST   /api/campaigns/{id}/pause/   Pause active campaign
    POST   /api/campaigns/{id}/cancel/  Cancel campaign
    GET    /api/campaigns/{id}/stats/   Campaign delivery statistics
    GET    /api/campaigns/{id}/recipients/ List recipients with status
"""
import logging

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.permissions import AgencyTenantAccessPermission, IsTenantMemberOrAgencyAdmin
from campaigns.models import (
    Campaign,
    CampaignStatus,
    ScheduledMessage,
    ScheduledMessageStatus,
)
from campaigns.serializers import (
    CampaignCreateSerializer,
    CampaignSerializer,
    ScheduledMessageSerializer,
)
from messaging.models import Contact
from scheduler.models import SchedulerJobStatus
from scheduler.services.scheduler_service import SchedulerService
from users.models import UserRole

logger = logging.getLogger(__name__)


class CampaignViewSet(viewsets.ModelViewSet):
    """
    ViewSet for campaign management.

    Access:
    - TENANT MEMBERS: Can manage their own campaigns
    - AGENCY ADMINS: Can manage campaigns for their client tenants
    """

    permission_classes = [IsTenantMemberOrAgencyAdmin, AgencyTenantAccessPermission]

    # ── Queryset & Serializer ─────────────────────────────────────────────────

    def get_queryset(self):
        user = self.request.user
        tenant_id = self.request.query_params.get("tenant_id")
        base_qs = Campaign.objects.select_related("tenant", "created_by")

        if user.is_super_admin:
            if tenant_id:
                try:
                    from uuid import UUID
                    UUID(tenant_id)
                except ValueError:
                    return base_qs.none()
                return base_qs.filter(tenant_id=tenant_id)
            return base_qs.all()

        if user.role == UserRole.AGENCY_ADMIN and user.agency:
            if tenant_id:
                from tenants.models import Tenant
                if Tenant.objects.filter(id=tenant_id, agency=user.agency).exists():
                    return base_qs.filter(tenant_id=tenant_id)
                return Campaign.objects.none()
            return base_qs.filter(tenant__agency=user.agency)

        return base_qs.filter(tenant=user.tenant)

    def get_serializer_class(self):
        if self.action == "create":
            return CampaignCreateSerializer
        return CampaignSerializer

    # ── CRUD Hooks ────────────────────────────────────────────────────────────

    def perform_create(self, serializer):
        user = self.request.user
        tenant_id = (
            self.request.data.get("tenant_id")
            or self.request.query_params.get("tenant_id")
        )
        start_date = serializer.validated_data.get("start_date")
        initial_status = CampaignStatus.SCHEDULED if start_date else CampaignStatus.DRAFT
        tenant = self._resolve_tenant_for_create(user, tenant_id)

        campaign = serializer.save(
            tenant=tenant,
            created_by=user,
            status=initial_status,
        )
        if start_date:
            self._create_scheduled_messages(campaign)

    def perform_update(self, serializer):
        instance = serializer.instance
        start_date = serializer.validated_data.get("start_date") or instance.start_date
        regenerate_jobs = self.request.data.get("regenerate_jobs", False)

        if start_date and instance.status == CampaignStatus.DRAFT:
            serializer.save(status=CampaignStatus.SCHEDULED)
            self._create_scheduled_messages(serializer.instance)
        elif regenerate_jobs and instance.status == CampaignStatus.SCHEDULED:
            from scheduler.models import SchedulerJob
            SchedulerJob.objects.filter(
                campaign=instance, status=SchedulerJobStatus.PENDING
            ).delete()
            ScheduledMessage.objects.filter(campaign=instance, status="pending").delete()
            serializer.save()
            self._create_scheduled_messages(serializer.instance)
        else:
            serializer.save()

    def perform_destroy(self, instance):
        from scheduler.models import SchedulerJob
        from tenants.models import AuditLog

        scheduler_jobs = SchedulerJob.objects.filter(campaign=instance)
        jobs_count = scheduler_jobs.count()
        recipients_count = sum(j.total_recipients for j in scheduler_jobs)
        scheduled_msgs_count = instance.scheduled_messages.count()

        scheduler_jobs.delete()

        AuditLog.log(
            action="campaign.deleted",
            user=self.request.user,
            tenant=instance.tenant,
            metadata={
                "campaign_id": str(instance.id),
                "campaign_name": instance.name,
                "campaign_status": instance.status,
                "scheduler_jobs_deleted": jobs_count,
                "recipients_deleted": recipients_count,
                "scheduled_messages_deleted": scheduled_msgs_count,
            },
            request=self.request,
        )
        logger.info(
            "Campaign '%s' (%s) deleted by %s. Cleaned up %d jobs, %d recipients, %d messages.",
            instance.name, instance.id, self.request.user,
            jobs_count, recipients_count, scheduled_msgs_count,
        )
        instance.delete()

    # ── Lifecycle Actions ─────────────────────────────────────────────────────

    @action(detail=True, methods=["post"])
    def schedule(self, request, pk=None):
        """Schedule a draft or paused campaign for a specific time."""
        campaign = self.get_object()
        if campaign.status not in [CampaignStatus.DRAFT, CampaignStatus.PAUSED]:
            return Response(
                {"error": "Can only schedule draft or paused campaigns"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        scheduled_at = request.data.get("scheduled_at")
        if not scheduled_at:
            return Response(
                {"error": "scheduled_at is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        campaign.scheduled_at = scheduled_at
        campaign.status = CampaignStatus.SCHEDULED
        campaign.save()
        self._create_scheduled_messages(campaign)
        return Response({"message": f"Campaign scheduled for {scheduled_at}",
                         "data": CampaignSerializer(campaign).data})

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        """Start a draft or scheduled campaign immediately."""
        campaign = self.get_object()
        if campaign.status not in [CampaignStatus.DRAFT, CampaignStatus.SCHEDULED]:
            return Response(
                {"error": "Can only start draft or scheduled campaigns"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        campaign.status = CampaignStatus.ACTIVE
        campaign.started_at = timezone.now()
        campaign.save()
        if campaign.scheduled_messages.count() == 0:
            self._create_scheduled_messages(campaign)
        return Response({"message": "Campaign started",
                         "data": CampaignSerializer(campaign).data})

    @action(detail=True, methods=["post"])
    def pause(self, request, pk=None):
        """Pause an active campaign."""
        campaign = self.get_object()
        if campaign.status != CampaignStatus.ACTIVE:
            return Response(
                {"error": "Can only pause active campaigns"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        campaign.status = CampaignStatus.PAUSED
        campaign.save()
        return Response({"message": "Campaign paused",
                         "data": CampaignSerializer(campaign).data})

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancel a campaign and mark pending messages as cancelled."""
        campaign = self.get_object()
        if campaign.status in [CampaignStatus.COMPLETED, CampaignStatus.CANCELLED]:
            return Response(
                {"error": "Campaign already finished"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        campaign.status = CampaignStatus.CANCELLED
        campaign.save()
        campaign.scheduled_messages.filter(
            status=ScheduledMessageStatus.PENDING
        ).update(status=ScheduledMessageStatus.CANCELLED)
        return Response({"message": "Campaign cancelled",
                         "data": CampaignSerializer(campaign).data})

    # ── Stats & Recipients ────────────────────────────────────────────────────

    @action(detail=True, methods=["get"])
    def stats(self, request, pk=None):
        """Aggregate delivery stats for a campaign."""
        campaign = self.get_object()
        agg = campaign.scheduled_messages.aggregate(
            total=Count("id"),
            pending=Count("id", filter=Q(status=ScheduledMessageStatus.PENDING)),
            sent=Count("id", filter=Q(status=ScheduledMessageStatus.SENT)),
            failed=Count("id", filter=Q(status=ScheduledMessageStatus.FAILED)),
            cancelled=Count("id", filter=Q(status=ScheduledMessageStatus.CANCELLED)),
        )
        return Response({
            "campaign_id": str(campaign.id),
            "campaign_name": campaign.name,
            "status": campaign.status,
            **agg,
        })

    @action(detail=True, methods=["get"])
    def recipients(self, request, pk=None):
        """List all recipients of a campaign with their delivery status."""
        campaign = self.get_object()
        msgs = campaign.scheduled_messages.select_related("contact")
        return Response({
            "count": msgs.count(),
            "results": ScheduledMessageSerializer(msgs, many=True).data,
        })

    # ── Private Helpers ───────────────────────────────────────────────────────

    def _resolve_tenant_for_create(self, user, tenant_id):
        from rest_framework.exceptions import PermissionDenied, ValidationError
        from tenants.models import Tenant

        if user.role == UserRole.AGENCY_ADMIN:
            if not tenant_id:
                raise ValidationError({"tenant_id": "Agency admins must specify a tenant_id."})
            if not user.agency:
                raise ValidationError({"error": "Agency admin must belong to an agency."})
            tenant = Tenant.objects.filter(id=tenant_id, agency=user.agency).first()
            if not tenant:
                raise PermissionDenied("You do not have access to this tenant.")
            return tenant

        if user.is_super_admin:
            if not tenant_id:
                raise ValidationError({"tenant_id": "Super admins must specify a tenant_id."})
            tenant = Tenant.objects.filter(id=tenant_id).first()
            if not tenant:
                raise ValidationError({"tenant_id": "Invalid tenant_id."})
            return tenant

        if not user.tenant:
            raise ValidationError({"error": "User does not belong to a tenant."})
        return user.tenant

    def _create_scheduled_messages(self, campaign: Campaign):
        """
        Create ScheduledMessage rows (stats/tracking) and a SchedulerJob
        (actual delivery) for each targeted contact.
        """
        tenant = campaign.tenant
        if not campaign.template_name:
            return

        contacts = self._resolve_contacts(campaign, tenant)
        contacts_list = list(contacts)
        if not contacts_list:
            return

        scheduled_at = campaign.scheduled_at or timezone.now()
        ScheduledMessage.objects.bulk_create([
            ScheduledMessage(campaign=campaign, contact=c, scheduled_at=scheduled_at)
            for c in contacts_list
        ])

        template_id = self._resolve_template_id(campaign, tenant)
        if template_id is None:
            return

        recipients = [
            {
                "phone_number": c.phone,
                "contact_id": str(c.id),
                "contact_name": c.name or "",
                "custom_body_params": campaign.template_params or [],
            }
            for c in contacts_list
        ]
        try:
            SchedulerService().create_job(
                tenant=tenant,
                template_name=campaign.template_name,
                scheduled_time=scheduled_at,
                recipients=recipients,
                template_id=template_id,
                body_params=campaign.template_params or [],
                campaign=campaign,
                priority=5,
                max_retries=3,
                template_type=campaign.template_type or "standard",
                header_data=campaign.header_data or {},
                cards_json=campaign.cards_json or [],
            )
        except ValueError as exc:
            logger.warning("Campaign %s: no scheduler jobs created — %s", campaign.id, exc)

    @staticmethod
    def _resolve_contacts(campaign: Campaign, tenant):
        base = Contact.objects.filter(tenant=tenant, is_subscribed=True, is_blocked=False)
        if campaign.target_all:
            return base
        if campaign.target_tags:
            tag_q = Q()
            for tag in campaign.target_tags:
                tag_q |= Q(tags__contains=[tag])
            return base.filter(tag_q)
        return Contact.objects.none()

    @staticmethod
    def _resolve_template_id(campaign: Campaign, tenant):
        from templates.models import CachedMetaTemplate, WhatsAppTemplate

        tmpl = WhatsAppTemplate.objects.filter(
            assigned_clients=tenant,
            template_name=campaign.template_name,
            is_active=True,
        ).first()
        if tmpl:
            return tmpl.id

        cached = CachedMetaTemplate.objects.filter(
            tenant=tenant, name=campaign.template_name, status="APPROVED"
        ).first()
        if cached:
            logger.info("Campaign %s: using CachedMetaTemplate for '%s'",
                        campaign.id, campaign.template_name)
            return cached.id

        logger.error(
            "Campaign %s: template '%s' not found — messages will NOT be sent.",
            campaign.id, campaign.template_name,
        )
        campaign.status = CampaignStatus.DRAFT
        campaign.save(update_fields=["status"])
        ScheduledMessage.objects.filter(campaign=campaign).delete()
        return None
