"""
Celery tasks for scheduler operations.
Implements the core scheduler loop and job processing.

NOTE: This module sets DJANGO_ALLOW_ASYNC_UNSAFE=true to allow Django ORM 
operations in Celery workers using async pools (gevent/eventlet). This is
safe because Celery tasks are designed to be synchronous and the ORM operations
are properly isolated per-request.
"""
import os
import logging
from celery import shared_task
from django.utils import timezone

# Allow Django ORM in async context for Celery workers with gevent/eventlet pools
# This is safe because each Celery task runs in isolation
os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from .services.scheduler_service import SchedulerService
from .services.sync_whatsapp import SyncWhatsAppClient
from .models import SchedulerJob, SchedulerJobRecipient, SchedulerJobStatus, RecipientStatus

logger = logging.getLogger(__name__)


@shared_task(name='scheduler.tasks.scheduler_heartbeat')
def scheduler_heartbeat():
    """
    Main scheduler heartbeat task - runs every 30 seconds via Celery Beat.

    Fetches due jobs and dispatches them for processing.
    Uses distributed locking to prevent race conditions.

    Returns:
        Dict with dispatch count
    """
    service = SchedulerService()
    job_ids = service.fetch_due_jobs()

    if not job_ids:
        logger.debug('No due jobs found')
        return {'dispatched': 0, 'timestamp': timezone.now().isoformat()}

    # Dispatch each job to separate task for parallel processing
    # Use task_id based on job_id to prevent duplicate tasks
    for job_id in job_ids:
        task_id = f'scheduler-job-{job_id}'
        process_scheduler_job.apply_async(
            args=[job_id], 
            queue='jobs',
            task_id=task_id  # Prevents duplicate tasks for same job
        )

    logger.info(f'Dispatched {len(job_ids)} jobs for processing')
    return {'dispatched': len(job_ids), 'timestamp': timezone.now().isoformat()}


@shared_task(name='scheduler.tasks.process_scheduler_job', bind=True, max_retries=0)
def process_scheduler_job(self, job_id: str):
    """
    Process a single scheduler job with all its recipients.

    Features:
    - Error isolation per recipient
    - Async message sending
    - Progress tracking

    Args:
        job_id: UUID string of the job to process

    Returns:
        Dict with processing results
    """
    try:
        job = SchedulerJob.objects.select_related('tenant').get(id=job_id)
    except SchedulerJob.DoesNotExist:
        logger.error(f'Job {job_id} not found')
        return {'status': 'error', 'error': 'Job not found'}

    # Prevent duplicate processing - only process if status is PROCESSING
    if job.status != SchedulerJobStatus.PROCESSING:
        logger.warning(f'Job {job_id} already processed or not ready (status: {job.status})')
        return {'status': 'skipped', 'reason': f'Job status is {job.status}'}

    # Store Celery task ID
    job.celery_task_id = self.request.id or ''
    job.save(update_fields=['celery_task_id'])

    # Get WhatsApp client for tenant
    client = SyncWhatsAppClient.from_tenant(job.tenant)
    if not client:
        service = SchedulerService()
        service.update_job_completion(job_id, error_message='WhatsApp not configured for tenant')
        return {'status': 'error', 'error': 'WhatsApp not configured'}

    # Get pending recipients
    service = SchedulerService()
    recipients = service.get_job_pending_recipients(job_id)

    if not recipients:
        service.update_job_completion(job_id)
        return {'status': 'completed', 'sent': 0, 'failed': 0, 'message': 'No pending recipients'}

    # Prepare recipient data
    recipient_data = [
        {
            'phone_number': r.phone_number,
            'custom_body_params': r.custom_body_params or job.body_params
        }
        for r in recipients
    ]

    def _mask_phone(phone):
        """Mask phone number for logging, showing only last 4 digits."""
        return f'***{phone[-4:]}' if len(phone) >= 4 else '***'

    logger.info(
        f'Job {job_id}: Sending to {len(recipient_data)} recipients '
        f'(e.g. {_mask_phone(recipient_data[0]["phone_number"])}), '
        f'template_type={job.template_type}, '
        f'language={job.language_code}, '
        f'cards_json_count={len(job.cards_json) if job.cards_json else 0}'
    )

    # Resolve template name for WhatsApp API
    # The API expects the template NAME (e.g. "hello_world"), NOT the numeric Meta ID.
    # job.template_name already stores the correct name; template_id is only for
    # internal lookups (metadata, language fallback, etc.).
    api_template_name = job.template_name
    if job.template_id:
        try:
            from templates.models import WhatsAppTemplate, CachedMetaTemplate
            try:
                tmpl = WhatsAppTemplate.objects.get(id=job.template_id)
                # Use the WhatsAppTemplate's template_name (not template_id which is numeric)
                api_template_name = tmpl.template_name
                logger.info(f"Resolved WhatsAppTemplate '{api_template_name}' for job {job_id}")
            except WhatsAppTemplate.DoesNotExist:
                # Might be a CachedMetaTemplate UUID
                try:
                    cached = CachedMetaTemplate.objects.get(id=job.template_id)
                    api_template_name = cached.name
                    logger.info(f"Resolved CachedMetaTemplate '{api_template_name}' for job {job_id}")
                except CachedMetaTemplate.DoesNotExist:
                    logger.warning(
                        f"Template ID {job.template_id} not found in WhatsAppTemplate or "
                        f"CachedMetaTemplate — falling back to job.template_name='{job.template_name}'"
                    )
        except Exception as e:
            logger.warning(f"Failed to resolve template ID {job.template_id}: {e}")

    # Check if this is a v2 job (carousel, or has meaningful header_data/cards)
    # NOTE: empty dict {} and empty list [] are falsy but stored as defaults,
    # so we check for non-empty content, not just truthiness.
    has_header_data = bool(job.header_data and job.header_data.get('type'))
    has_cards = bool(job.cards_json and len(job.cards_json) > 0)
    is_v2_job = bool(
        job.template_type != 'standard'
        or has_header_data
        or has_cards
    )

    if is_v2_job:
        # === V2 PATH: Use ComponentsBuilder for universal component generation ===
        from messaging.whatsapp_service import ComponentsBuilder

        # Resolve relative media URLs to absolute URLs.
        # Meta API requires fully-qualified https:// URLs for image/video links.
        # Media stored in PostgreSQL has URLs like /api/media/{id}/file/ which
        # need to be prefixed with the public base URL.
        from django.conf import settings as django_settings
        base_url = getattr(django_settings, 'WEBHOOK_BASE_URL', '').rstrip('/')

        def _resolve_url(url):
            """Convert relative URL to absolute using WEBHOOK_BASE_URL."""
            if not url:
                return url
            if url.startswith('http://') or url.startswith('https://'):
                return url
            return f'{base_url}{url}' if base_url else url

        # Resolve header_data URL
        resolved_header = job.header_data or None
        if resolved_header and resolved_header.get('url'):
            resolved_header = {**resolved_header, 'url': _resolve_url(resolved_header['url'])}

        # Resolve cards_json URLs (carousel card headers)
        resolved_cards = job.cards_json or None
        if resolved_cards:
            resolved_cards = []
            for card in job.cards_json:
                card_copy = {**card}
                if card_copy.get('header', {}).get('url'):
                    card_copy['header'] = {
                        **card_copy['header'],
                        'url': _resolve_url(card_copy['header']['url'])
                    }
                resolved_cards.append(card_copy)

        logger.info(
            f'Job {job_id}: Resolved URLs — '
            f'header={resolved_header}, '
            f'cards_count={len(resolved_cards) if resolved_cards else 0}'
        )

        components = ComponentsBuilder.for_template_type(
            template_type=job.template_type,
            header=resolved_header,
            body_params=job.body_params or None,
            button_params=job.button_params or None,
            cards=resolved_cards
        )

        results = client.send_batch_with_components(
            recipients=recipient_data,
            template_name=api_template_name,
            language_code=job.language_code,
            components=components,
            delay_between=0.2
        )
    else:
        # === LEGACY V1 PATH: flat parameters (backward compatible) ===
        results = client.send_batch(
            recipients=recipient_data,
            template_name=api_template_name,
            language_code=job.language_code,
            header_image=job.header_image_url or None,
            body_params=job.body_params,
            button_params=job.button_params,
            delay_between=0.2  # 200ms between messages
        )

    # Map results back to recipients
    phone_to_recipient = {r.phone_number: r for r in recipients}
    sent_count = 0
    failed_count = 0

    for result in results:
        recipient = phone_to_recipient.get(result.phone)
        if not recipient:
            continue

        service.update_recipient_result(
            recipient=recipient,
            success=result.success,
            message_id=result.message_id,
            error_code=result.error_code,
            error_message=result.error_message
        )

        if result.success:
            sent_count += 1
        else:
            failed_count += 1
            logger.warning(f'Failed to send to {result.phone}: {result.error_message}')

    # Log summary with message IDs for debugging delivery
    msg_ids = [r.message_id for r in results if r.success and r.message_id]
    logger.info(
        f'Job {job_id}: {sent_count} sent, {failed_count} failed. '
        f'Message IDs: {msg_ids}'
    )

    # Update job completion status
    service.update_job_completion(job_id)

    # Sync statuses with campaign models
    if job.campaign:
        # --- Sync CampaignMessage (new model) ---
        try:
            from campaigns.models import CampaignMessage, CampaignMessageStatus
            campaign_msgs = list(CampaignMessage.objects.filter(scheduler_job=job))

            # Fallback: if no messages found via FK (link may not have been saved),
            # match by campaign + template_name + scheduled_at window (±2 min)
            if not campaign_msgs:
                from django.utils import timezone as tz
                from datetime import timedelta
                window_start = job.scheduled_time - timedelta(minutes=2)
                window_end = job.scheduled_time + timedelta(minutes=2)
                campaign_msgs = list(CampaignMessage.objects.filter(
                    campaign=job.campaign,
                    template_name=job.template_name,
                    scheduled_at__gte=window_start,
                    scheduled_at__lte=window_end,
                    status=CampaignMessageStatus.PENDING,
                ))
                if campaign_msgs:
                    logger.info(
                        f'Job {job_id}: Found {len(campaign_msgs)} CampaignMessage(s) '
                        f'via fallback lookup (campaign+template+time window)'
                    )
                    # Also save the FK link so future syncs are faster
                    for cm in campaign_msgs:
                        cm.scheduler_job = job

            for cm in campaign_msgs:
                cm.sent_count = sent_count
                cm.failed_count = failed_count
                if failed_count > 0 and sent_count == 0:
                    cm.status = CampaignMessageStatus.FAILED
                elif sent_count > 0:
                    cm.status = CampaignMessageStatus.SENT
                cm.save(update_fields=['status', 'sent_count', 'failed_count', 'scheduler_job'])
            logger.info(f'Synced {len(campaign_msgs)} CampaignMessage(s) for job {job_id}')
        except Exception as e:
            logger.warning(f'Failed to sync CampaignMessage statuses: {e}')

        # --- Sync ScheduledMessage (legacy model) ---
        try:
            from campaigns.models import ScheduledMessage, ScheduledMessageStatus, CampaignStatus
            from messaging.models import Contact
            
            # Get phone to result mapping
            phone_results = {r.phone: r for r in results}
            
            # Get contacts by phone number for this campaign
            scheduled_messages = ScheduledMessage.objects.filter(
                campaign=job.campaign
            ).select_related('contact')
            
            for scheduled_msg in scheduled_messages:
                result = phone_results.get(scheduled_msg.contact.phone)
                if result:
                    if result.success:
                        scheduled_msg.status = ScheduledMessageStatus.SENT
                        scheduled_msg.sent_at = timezone.now()
                    else:
                        scheduled_msg.status = ScheduledMessageStatus.FAILED
                    scheduled_msg.save(update_fields=['status', 'sent_at'])
            
            # Check if all messages are processed (no pending) and update campaign status
            pending_count = ScheduledMessage.objects.filter(
                campaign=job.campaign,
                status=ScheduledMessageStatus.PENDING
            ).count()
            
            if pending_count == 0 and job.campaign.status in [CampaignStatus.ACTIVE, CampaignStatus.SCHEDULED]:
                job.campaign.status = CampaignStatus.COMPLETED
                job.campaign.completed_at = timezone.now()
                job.campaign.save(update_fields=['status', 'completed_at'])
                logger.info(f'Campaign {job.campaign.id} marked as COMPLETED')
            
            logger.info(f'Synced ScheduledMessage statuses for campaign {job.campaign.id}')
        except Exception as e:
            logger.warning(f'Failed to sync ScheduledMessage statuses: {e}')

    logger.info(f'Job {job_id}: Processed {len(results)} recipients - {sent_count} sent, {failed_count} failed')

    return {
        'status': 'completed',
        'job_id': job_id,
        'total': len(results),
        'sent': sent_count,
        'failed': failed_count
    }


@shared_task(name='scheduler.tasks.cleanup_stale_jobs')
def cleanup_stale_jobs():
    """
    Periodic task to reset jobs stuck in processing.
    Runs every 5 minutes.

    Returns:
        Dict with cleanup count
    """
    service = SchedulerService()
    reset_count = service.cleanup_stale_jobs(stale_minutes=10)

    return {
        'reset_count': reset_count,
        'timestamp': timezone.now().isoformat()
    }


@shared_task(name='scheduler.tasks.retry_failed_recipients')
def retry_failed_recipients(job_id: str):
    """
    Retry failed recipients for a specific job.

    Args:
        job_id: UUID string of the job

    Returns:
        Dict with retry results
    """
    try:
        job = SchedulerJob.objects.select_related('tenant').get(id=job_id)
    except SchedulerJob.DoesNotExist:
        logger.error(f'Job {job_id} not found for retry')
        return {'status': 'error', 'error': 'Job not found'}

    # Reset failed recipients to pending
    failed_recipients = SchedulerJobRecipient.objects.filter(
        job_id=job_id,
        status=RecipientStatus.FAILED
    )

    reset_count = failed_recipients.update(
        status=RecipientStatus.PENDING,
        error_code='',
        error_message=''
    )

    if reset_count == 0:
        return {'status': 'skipped', 'message': 'No failed recipients to retry'}

    # Reset job status
    job.status = SchedulerJobStatus.PENDING
    job.processing_started_at = None
    job.completed_at = None
    job.claimed_by = ''
    job.claimed_at = None
    job.scheduled_time = timezone.now()
    job.save()

    logger.info(f'Reset {reset_count} failed recipients for job {job_id}')

    return {
        'status': 'scheduled',
        'job_id': job_id,
        'reset_count': reset_count
    }


@shared_task(name='scheduler.tasks.debug_celery_ping')
def debug_celery_ping():
    """
    Simple task to verify Celery worker is alive.
    Used by HealthCheck API.
    """
    return "pong"
