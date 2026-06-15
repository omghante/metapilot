"""
CampaignMessageViewSet — Per-message scheduling within a campaign.

Each CampaignMessage has its own scheduled time and creates an
independent SchedulerJob, enabling fine-grained delivery control.

Endpoints (nested under /api/campaigns/{campaign_pk}/messages/):
    GET    /                          List messages for campaign
    POST   /                          Create + schedule a new message
    GET    /{id}/                     Get message details
    PUT    /{id}/                     Update message (reschedules if time changes)
    DELETE /{id}/                     Soft-cancel message
    GET    /{id}/recipients/          Delivery status per recipient (paginated)
"""
import logging

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.permissions import IsTenantMemberOrAgencyAdmin
from campaigns.models import Campaign, CampaignMessage, CampaignMessageStatus
from campaigns.serializers import CampaignMessageSerializer
from messaging.models import Contact
from scheduler.models import SchedulerJobRecipient, SchedulerJobStatus
from scheduler.services.scheduler_service import SchedulerService
from users.models import UserRole

logger = logging.getLogger(__name__)


class CampaignMessageViewSet(viewsets.ModelViewSet):
    """
    Manages individual messages within a campaign, each with independent scheduling.
    """

    serializer_class = CampaignMessageSerializer
    permission_classes = [IsTenantMemberOrAgencyAdmin]

    # ── Queryset ──────────────────────────────────────────────────────────────

    def get_queryset(self):
        campaign_id = self.kwargs.get("campaign_pk")
        user = self.request.user
        tenant = self._resolve_tenant(user)
        if not tenant:
            return CampaignMessage.objects.none()
        return CampaignMessage.objects.filter(
            campaign_id=campaign_id,
            campaign__tenant=tenant,
        ).select_related("campaign", "scheduler_job")

    # ── CRUD Hooks ────────────────────────────────────────────────────────────

    def perform_create(self, serializer):
        campaign_id = self.kwargs.get("campaign_pk")
        campaign = Campaign.objects.get(id=campaign_id)
        message = serializer.save(campaign=campaign)
        self._create_message_job(message)

    def perform_update(self, serializer):
        old_scheduled_at = serializer.instance.scheduled_at
        message = serializer.save()
        if message.scheduled_at != old_scheduled_at:
            self._reschedule_message_job(message)

    def perform_destroy(self, instance):
        """Soft-cancel: mark as cancelled without hard-deleting."""
        if (
            instance.scheduler_job
            and instance.scheduler_job.status == SchedulerJobStatus.PENDING
        ):
            instance.scheduler_job.status = SchedulerJobStatus.CANCELLED
            instance.scheduler_job.save()
        instance.status = CampaignMessageStatus.CANCELLED
        instance.save()

    # ── Recipients Action ─────────────────────────────────────────────────────

    @action(detail=True, methods=["get"])
    def recipients(self, request, campaign_pk=None, pk=None):
        """
        Paginated list of recipients with delivery status.
        Error details are generic to avoid leaking PII in API responses.
        """
        message = self.get_object()

        if not message.scheduler_job:
            return Response({
                "count": 0,
                "results": [],
                "message": "No scheduler job associated with this message",
            })

        recipients_qs = SchedulerJobRecipient.objects.filter(
            job=message.scheduler_job
        ).order_by("created_at")

        # Audit log (no PII logged)
        from tenants.models import AuditLog
        AuditLog.log(
            action="campaign.view_recipients",
            user=request.user,
            tenant=message.campaign.tenant,
            metadata={
                "campaign_id": str(message.campaign.id),
                "message_id": str(message.id),
                "total_recipients": recipients_qs.count(),
            },
            request=request,
        )

        page = self.paginate_queryset(recipients_qs)
        serialized = [self._serialize_recipient(r) for r in (page or recipients_qs)]

        if page is not None:
            return self.get_paginated_response(serialized)
        return Response({"count": len(serialized), "results": serialized})

    # ── Private Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _resolve_tenant(user):
        if user.role == UserRole.AGENCY_ADMIN and user.agency:
            from tenants.models import Tenant
            tenant_id = (
                user.request.query_params.get("tenant_id")
                if hasattr(user, "request")
                else None
            )
            if tenant_id:
                return Tenant.objects.filter(id=tenant_id, agency=user.agency).first()
        if hasattr(user, "tenant") and user.tenant:
            return user.tenant
        return None

    def _create_message_job(self, message: CampaignMessage):
        """Resolve contacts + template and create a SchedulerJob for this message."""
        campaign = message.campaign
        tenant = campaign.tenant
        contacts_list = list(Contact.objects.filter(tenant=tenant))

        if not contacts_list:
            logger.warning("CampaignMessage %s: no contacts found", message.id)
            return

        template_id, language_code = self._resolve_template(message, tenant)
        if template_id is None:
            return

        recipients = [
            {
                "phone_number": c.phone,
                "contact_id": str(c.id),
                "contact_name": c.name or "",
                "custom_body_params": message.template_params or [],
            }
            for c in contacts_list
        ]

        try:
            message.refresh_from_db()
            job = SchedulerService().create_job(
                tenant=tenant,
                template_name=message.template_name,
                scheduled_time=message.scheduled_at,
                recipients=recipients,
                template_id=template_id,
                language_code=language_code,
                body_params=message.template_params or [],
                campaign=campaign,
                priority=5,
                max_retries=3,
                template_type=message.template_type or "standard",
                header_data=message.header_data or {},
                cards_json=message.cards_json or [],
            )
            message.scheduler_job = job
            message.save(update_fields=["scheduler_job"])
            logger.info(
                "CampaignMessage %s: created job %s (type=%s, cards=%d)",
                message.id, job.id, message.template_type, len(message.cards_json or []),
            )
        except Exception as exc:
            logger.error(
                "CampaignMessage %s: failed to create scheduler job: %s",
                message.id, exc, exc_info=True,
            )

    def _reschedule_message_job(self, message: CampaignMessage):
        """Update existing pending job or create a new one."""
        if (
            message.scheduler_job
            and message.scheduler_job.status == SchedulerJobStatus.PENDING
        ):
            message.scheduler_job.scheduled_time = message.scheduled_at
            message.scheduler_job.save(update_fields=["scheduled_time"])
            logger.info("CampaignMessage %s: rescheduled to %s", message.id, message.scheduled_at)
        else:
            self._create_message_job(message)

    @staticmethod
    def _resolve_template(message: CampaignMessage, tenant):
        """Return (template_id, language_code) or (None, None) on failure."""
        from templates.models import CachedMetaTemplate, WhatsAppTemplate

        tmpl = WhatsAppTemplate.objects.filter(
            assigned_clients=tenant,
            template_name=message.template_name,
            is_active=True,
        ).first()
        if tmpl:
            return tmpl.id, tmpl.language

        cached = CachedMetaTemplate.objects.filter(
            tenant=tenant, name=message.template_name, status="APPROVED"
        ).first()
        if cached:
            logger.info(
                "CampaignMessage %s: using CachedMetaTemplate for '%s'",
                message.id, message.template_name,
            )
            return cached.id, cached.language or "en_US"

        logger.warning(
            "CampaignMessage %s: template '%s' not found",
            message.id, message.template_name,
        )
        return None, None

    @staticmethod
    def _serialize_recipient(r) -> dict:
        return {
            "id": str(r.id),
            "contact_name": r.contact_name,
            "contact_phone": r.phone_number,
            "status": r.status.upper(),
            "display_status": r.status.capitalize(),
            "error_code": r.error_code if r.status.upper() == "FAILED" else None,
            "error_message": (
                "Delivery failed. Contact support for details."
                if r.status.upper() == "FAILED" and r.error_message
                else None
            ),
            "sent_at": r.sent_at,
            "created_at": r.created_at,
        }
