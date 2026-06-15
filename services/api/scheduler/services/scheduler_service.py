"""
Core scheduler service for distributed message processing.
Implements exact-time execution, distributed locking, and job management.
"""
import logging
from typing import List
from django.db import transaction
from django.db.models import Q, F
from django.utils import timezone
from django.conf import settings

from scheduler.models import SchedulerJob, SchedulerJobRecipient, SchedulerJobStatus, RecipientStatus

logger = logging.getLogger(__name__)


class SchedulerService:
    """
    Core scheduler service for distributed job processing.

    Features:
    - Distributed locking via SELECT FOR UPDATE SKIP LOCKED
    - Exact-time execution
    - Retry handling with exponential backoff
    - Multi-tenant isolation
    """

    # Retry delays in seconds (1min, 5min, 15min)
    RETRY_DELAYS = getattr(settings, 'SCHEDULER_RETRY_DELAYS', [60, 300, 900])

    # Default batch size
    BATCH_SIZE = getattr(settings, 'SCHEDULER_BATCH_SIZE', 20)

    # Server ID for distributed locking
    SERVER_ID = getattr(settings, 'SERVER_ID', 'server_01')

    def fetch_due_jobs(self, limit: int = None) -> List[str]:
        """
        Fetch due jobs with distributed locking.

        Uses SELECT FOR UPDATE SKIP LOCKED to prevent race conditions
        when multiple schedulers are running.

        Args:
            limit: Maximum jobs to fetch

        Returns:
            List of job IDs that were claimed
        """
        limit = limit or self.BATCH_SIZE
        now = timezone.now()

        with transaction.atomic():
            # Query for due jobs with row locking
            # Skip locked rows to prevent blocking other schedulers
            due_jobs = SchedulerJob.objects.select_for_update(
                skip_locked=True
            ).filter(
                Q(status=SchedulerJobStatus.PENDING, scheduled_time__lte=now) |
                Q(
                    status=SchedulerJobStatus.FAILED,
                    next_retry_at__lte=now,
                    retry_count__lt=F('max_retries')
                )
            ).order_by('priority', 'scheduled_time')[:limit]

            job_ids = list(due_jobs.values_list('id', flat=True))

            if not job_ids:
                return []

            # Mark as processing
            SchedulerJob.objects.filter(id__in=job_ids).update(
                status=SchedulerJobStatus.PROCESSING,
                processing_started_at=now,
                claimed_by=self.SERVER_ID,
                claimed_at=now
            )

        logger.info(f'Claimed {len(job_ids)} jobs for processing')
        return [str(jid) for jid in job_ids]

    def get_job_pending_recipients(self, job_id: str) -> List[SchedulerJobRecipient]:
        """
        Get pending recipients for a job.

        Args:
            job_id: Job UUID string

        Returns:
            List of pending recipients
        """
        return list(SchedulerJobRecipient.objects.filter(
            job_id=job_id,
            status=RecipientStatus.PENDING
        ))

    def update_recipient_result(
        self,
        recipient: SchedulerJobRecipient,
        success: bool,
        message_id: str = None,
        error_code: str = None,
        error_message: str = None
    ):
        """
        Update recipient with send result.

        Args:
            recipient: Recipient model instance
            success: Whether send was successful
            message_id: WhatsApp message ID if successful
            error_code: Error code if failed
            error_message: Error message if failed
        """
        if success:
            recipient.status = RecipientStatus.SENT
            recipient.whatsapp_message_id = message_id or ''
            recipient.sent_at = timezone.now()
        else:
            recipient.status = RecipientStatus.FAILED
            recipient.error_code = error_code or ''
            recipient.error_message = error_message or ''
            recipient.retry_count += 1

        recipient.save()

    def update_job_completion(self, job_id: str, error_message: str = None):
        """
        Update job status based on recipient results.

        Args:
            job_id: Job UUID string
            error_message: Optional error message for the job
        """
        try:
            job = SchedulerJob.objects.get(id=job_id)
        except SchedulerJob.DoesNotExist:
            logger.error(f'Job {job_id} not found')
            return

        # Count results
        sent = job.recipients.filter(status=RecipientStatus.SENT).count()
        failed = job.recipients.filter(status=RecipientStatus.FAILED).count()
        total = job.total_recipients

        # Update counts
        job.sent_count = sent
        job.failed_count = failed
        job.completed_at = timezone.now()

        # Determine final status
        if sent == total:
            job.status = SchedulerJobStatus.COMPLETED
            logger.info(f'Job {job_id}: Completed - {sent}/{total} sent')
        elif sent > 0:
            job.status = SchedulerJobStatus.PARTIAL_FAILURE
            logger.warning(f'Job {job_id}: Partial failure - {sent}/{total} sent, {failed} failed')
        else:
            # All failed
            if job.retry_count < job.max_retries:
                # Schedule retry
                job.retry_count += 1
                delay = self._get_retry_delay(job.retry_count)
                job.next_retry_at = timezone.now() + timezone.timedelta(seconds=delay)
                job.status = SchedulerJobStatus.FAILED
                job.error_message = error_message or 'All recipients failed'
                logger.warning(f'Job {job_id}: Failed - scheduling retry #{job.retry_count}')
            else:
                job.status = SchedulerJobStatus.FAILED
                job.error_message = error_message or 'Max retries exceeded'
                logger.error(f'Job {job_id}: Failed - max retries exceeded')

        job.save()
        
        # Update linked CampaignMessage status if exists
        self._update_campaign_message_status(job)

    def _get_retry_delay(self, retry_count: int) -> int:
        """Get retry delay for given retry count."""
        if retry_count <= 0:
            return self.RETRY_DELAYS[0]
        index = min(retry_count - 1, len(self.RETRY_DELAYS) - 1)
        return self.RETRY_DELAYS[index]
    
    def _update_campaign_message_status(self, job: SchedulerJob):
        """Update the linked CampaignMessage status based on job status."""
        try:
            from campaigns.models import CampaignMessage, CampaignMessageStatus
            
            # Find CampaignMessage linked to this job
            campaign_message = CampaignMessage.objects.filter(scheduler_job=job).first()
            if not campaign_message:
                return
            
            # Map job status to message status
            if job.status == SchedulerJobStatus.COMPLETED:
                campaign_message.status = CampaignMessageStatus.SENT
                campaign_message.sent_count = job.sent_count
                campaign_message.failed_count = job.failed_count
            elif job.status == SchedulerJobStatus.PARTIAL_FAILURE:
                campaign_message.status = CampaignMessageStatus.SENT  # Partially sent is still sent
                campaign_message.sent_count = job.sent_count
                campaign_message.failed_count = job.failed_count
            elif job.status == SchedulerJobStatus.FAILED:
                campaign_message.status = CampaignMessageStatus.FAILED
                campaign_message.failed_count = job.failed_count
            elif job.status == SchedulerJobStatus.PROCESSING:
                campaign_message.status = CampaignMessageStatus.PROCESSING
            
            campaign_message.save()
            logger.info(f'CampaignMessage {campaign_message.id}: Updated status to {campaign_message.status}')
        except Exception as e:
            logger.warning(f'Failed to update CampaignMessage status: {e}')

    def cleanup_stale_jobs(self, stale_minutes: int = 10):
        """
        Reset jobs stuck in processing for too long.

        Args:
            stale_minutes: Minutes after which a processing job is considered stale

        Returns:
            Number of jobs reset
        """
        threshold = timezone.now() - timezone.timedelta(minutes=stale_minutes)

        stale_jobs = SchedulerJob.objects.filter(
            status=SchedulerJobStatus.PROCESSING,
            processing_started_at__lt=threshold
        )

        reset_count = 0
        for job in stale_jobs:
            if job.retry_count < job.max_retries:
                job.retry_count += 1
                delay = self._get_retry_delay(job.retry_count)
                job.next_retry_at = timezone.now() + timezone.timedelta(seconds=delay)
                job.status = SchedulerJobStatus.FAILED
                job.error_message = 'Processing timeout - reset for retry'
            else:
                job.status = SchedulerJobStatus.FAILED
                job.error_message = 'Processing timeout - max retries exceeded'

            job.processing_started_at = None
            job.claimed_by = ''
            job.claimed_at = None
            job.save()
            reset_count += 1

        if reset_count > 0:
            logger.info(f'Reset {reset_count} stale jobs')

        return reset_count

    def get_stats(self, tenant_id: str = None):
        """
        Get scheduler statistics.

        Args:
            tenant_id: Optional tenant filter

        Returns:
            Dict with scheduler stats
        """
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        queryset = SchedulerJob.objects.all()
        if tenant_id:
            queryset = queryset.filter(tenant_id=tenant_id)

        pending = queryset.filter(status=SchedulerJobStatus.PENDING).count()
        processing = queryset.filter(status=SchedulerJobStatus.PROCESSING).count()

        today_queryset = queryset.filter(created_at__gte=today_start)
        completed_today = today_queryset.filter(status=SchedulerJobStatus.COMPLETED).count()
        failed_today = today_queryset.filter(status=SchedulerJobStatus.FAILED).count()

        # Aggregate recipient stats
        from django.db.models import Sum
        today_stats = today_queryset.aggregate(
            total_recipients=Sum('total_recipients'),
            total_sent=Sum('sent_count')
        )

        total_recipients = today_stats['total_recipients'] or 0
        total_sent = today_stats['total_sent'] or 0
        success_rate = (total_sent / total_recipients * 100) if total_recipients > 0 else 0.0

        return {
            'pending_jobs': pending,
            'processing_jobs': processing,
            'completed_today': completed_today,
            'failed_today': failed_today,
            'total_recipients_today': total_recipients,
            'total_sent_today': total_sent,
            'success_rate_today': round(success_rate, 2)
        }

    def create_job(
        self,
        tenant,
        template_name: str,
        scheduled_time,
        recipients: List[dict],
        template_id: str = None,
        language_code: str = 'en_US',
        header_image_url: str = None,
        body_params: List[str] = None,
        button_params: List[dict] = None,
        campaign=None,
        priority: int = 5,
        max_retries: int = 3,
        template_type: str = 'standard',
        header_data: dict = None,
        cards_json: list = None,
    ) -> SchedulerJob:
        """
        Create a new scheduler job with recipients.

        Args:
            tenant: Tenant model instance
            template_name: WhatsApp template name
            scheduled_time: When to send
            recipients: List of recipient dicts with phone_number
            template_id: Optional template UUID
            language_code: Template language
            header_image_url: Optional header image
            body_params: Default body parameters
            button_params: Button parameters
            campaign: Optional campaign reference
            priority: Job priority (1-10)
            max_retries: Maximum retry attempts

        Returns:
            Created SchedulerJob instance
        
        Raises:
            ValueError: If no valid recipients after validation
        """
        # Validate and normalize phone numbers
        from .phone_validation import validate_recipients
        valid_recipients, invalid_recipients = validate_recipients(recipients)
        
        if not valid_recipients:
            raise ValueError(f'No valid recipients. {len(invalid_recipients)} invalid phone numbers.')
        
        if invalid_recipients:
            logger.warning(f'Skipping {len(invalid_recipients)} invalid phone numbers during job creation')
        
        with transaction.atomic():
            job = SchedulerJob.objects.create(
                tenant=tenant,
                campaign=campaign,
                template_id=template_id,
                template_name=template_name,
                language_code=language_code,
                header_image_url=header_image_url or '',
                body_params=body_params or [],
                button_params=button_params or [],
                template_type=template_type or 'standard',
                header_data=header_data or {},
                cards_json=cards_json or [],
                scheduled_time=scheduled_time,
                priority=priority,
                max_retries=max_retries,
                total_recipients=len(valid_recipients)  # Use validated count
            )

            # Create recipients with validated phone numbers
            recipient_objects = [
                SchedulerJobRecipient(
                    job=job,
                    contact_id=r.get('contact_id'),
                    phone_number=r['phone_number'],  # Already normalized
                    contact_name=r.get('contact_name', ''),
                    custom_body_params=r.get('custom_body_params', [])
                )
                for r in valid_recipients  # Use validated recipients
            ]
            SchedulerJobRecipient.objects.bulk_create(recipient_objects)

        logger.info(f'Created job {job.id} with {len(valid_recipients)} recipients (skipped {len(invalid_recipients)} invalid)')
        return job

    def create_campaign_jobs(
        self,
        tenant,
        template_name: str,
        scheduled_time,
        recipients: List[dict],
        template_id: str = None,
        language_code: str = 'en_US',
        header_image_url: str = None,
        body_params: List[str] = None,
        button_params: List[dict] = None,
        campaign=None,
        priority: int = 5,
        max_retries: int = 3,
        template_type: str = 'standard',
        header_data: dict = None,
        cards_json: list = None,
        batch_size: int = 1000
    ) -> List[SchedulerJob]:
        """
        Create multiple scheduler jobs by splitting recipients into batches.
        
        For high-volume campaigns (1000+ recipients), this method splits
        the recipient list into smaller batches that can be processed
        in parallel by multiple Celery workers.

        Args:
            tenant: Tenant model instance
            template_name: WhatsApp template name
            scheduled_time: When to send
            recipients: List of recipient dicts with phone_number
            template_id: Optional template UUID
            language_code: Template language
            header_image_url: Optional header image
            body_params: Default body parameters
            button_params: Button parameters
            campaign: Optional campaign reference
            priority: Job priority (1-10)
            max_retries: Maximum retry attempts
            batch_size: Recipients per job (default 1000)

        Returns:
            List of created SchedulerJob instances
        
        Example:
            1,000,000 recipients with batch_size=1000 → 1000 parallel jobs
            Each job processed by a separate Celery worker
        """
        total_recipients = len(recipients)
        
        # Shared keyword args for both single-job and batch paths
        job_kwargs = dict(
            tenant=tenant,
            template_name=template_name,
            scheduled_time=scheduled_time,
            template_id=template_id,
            language_code=language_code,
            header_image_url=header_image_url,
            body_params=body_params,
            button_params=button_params,
            campaign=campaign,
            priority=priority,
            max_retries=max_retries,
            template_type=template_type or 'standard',
            header_data=header_data,
            cards_json=cards_json,
        )

        # If small enough, create single job
        if total_recipients <= batch_size:
            job = self.create_job(recipients=recipients, **job_kwargs)
            return [job]
        
        # Split into batches
        jobs = []
        num_batches = (total_recipients + batch_size - 1) // batch_size  # Ceiling division
        
        logger.info(f'Splitting {total_recipients} recipients into {num_batches} jobs (batch_size={batch_size})')
        
        for i in range(num_batches):
            start_idx = i * batch_size
            end_idx = min(start_idx + batch_size, total_recipients)
            batch_recipients = recipients[start_idx:end_idx]
            
            job = self.create_job(recipients=batch_recipients, **job_kwargs)
            jobs.append(job)
        
        logger.info(f'Created {len(jobs)} parallel jobs for campaign')
        return jobs
