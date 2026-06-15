"""
Scheduler models for high-performance WhatsApp message scheduling.
Supports distributed execution, exact-time delivery, and fault isolation.
"""
import uuid
import hashlib
from django.db import models


class SchedulerJobStatus(models.TextChoices):
    """Status choices for scheduler jobs."""
    PENDING = 'pending', 'Pending'
    PROCESSING = 'processing', 'Processing'
    COMPLETED = 'completed', 'Completed'
    PARTIAL_FAILURE = 'partial_failure', 'Partial Failure'
    FAILED = 'failed', 'Failed'
    CANCELLED = 'cancelled', 'Cancelled'


class RecipientStatus(models.TextChoices):
    """Status choices for individual recipients."""
    PENDING = 'pending', 'Pending'
    SENT = 'sent', 'Sent'
    FAILED = 'failed', 'Failed'


class SchedulerJob(models.Model):
    """
    Central scheduling entity that groups recipients by execution time.

    Supports:
    - Exact-time execution (no intentional delay)
    - Distributed locking via SELECT FOR UPDATE SKIP LOCKED
    - Multi-tenant isolation
    - Retry with exponential backoff
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Tenant scope (multi-client system)
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='scheduler_jobs',
        help_text='Client this job belongs to'
    )

    # Optional campaign reference (scheduler is campaign-dependent, but logic is external)
    campaign = models.ForeignKey(
        'campaigns.Campaign',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='scheduler_jobs',
        help_text='Associated campaign (optional)'
    )

    # Template data (references Template API - not modified)
    template_id = models.UUIDField(
        null=True,
        blank=True,
        help_text='Reference to WhatsAppTemplate.id'
    )
    template_name = models.CharField(
        max_length=255,
        help_text='WhatsApp template name'
    )
    language_code = models.CharField(
        max_length=10,
        default='en_US',
        help_text='Template language code'
    )
    header_image_url = models.URLField(
        max_length=2048,
        blank=True,
        help_text='Header image URL for template'
    )
    body_params = models.JSONField(
        default=list,
        blank=True,
        help_text='Default body parameters for template'
    )
    button_params = models.JSONField(
        default=list,
        blank=True,
        help_text='Button parameters for template'
    )

    # === Universal Send v2 Fields (Carousel + Standard) ===
    template_type = models.CharField(
        max_length=20,
        default='standard',
        help_text='Template type: standard or carousel'
    )
    header_data = models.JSONField(
        default=dict,
        blank=True,
        help_text='Full header component data (type, url, text, etc.)'
    )
    cards_json = models.JSONField(
        default=list,
        blank=True,
        help_text='Carousel cards array. Each card: {header, bodyParams, buttonParams}'
    )

    # Scheduling - exact time execution
    scheduled_time = models.DateTimeField(
        db_index=True,
        help_text='Exact time to send messages (UTC)'
    )

    # Deduplication
    job_hash = models.CharField(
        max_length=64,
        unique=True,
        help_text='Hash for deduplication'
    )

    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=SchedulerJobStatus.choices,
        default=SchedulerJobStatus.PENDING,
        db_index=True
    )
    processing_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When processing started'
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When processing completed'
    )
    error_message = models.TextField(
        blank=True,
        help_text='Error message if job failed'
    )

    # Distributed locking
    claimed_by = models.CharField(
        max_length=100,
        blank=True,
        help_text='Server ID that claimed this job'
    )
    claimed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When job was claimed'
    )

    # Retry handling
    retry_count = models.PositiveSmallIntegerField(
        default=0,
        help_text='Number of retry attempts'
    )
    max_retries = models.PositiveSmallIntegerField(
        default=3,
        help_text='Maximum retry attempts'
    )
    next_retry_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text='Next retry time'
    )

    # Celery tracking
    celery_task_id = models.CharField(
        max_length=255,
        blank=True,
        help_text='Celery task ID'
    )

    # Statistics
    total_recipients = models.PositiveIntegerField(
        default=0,
        help_text='Total number of recipients'
    )
    sent_count = models.PositiveIntegerField(
        default=0,
        help_text='Successfully sent count'
    )
    failed_count = models.PositiveIntegerField(
        default=0,
        help_text='Failed send count'
    )

    # Priority for ordering
    priority = models.PositiveSmallIntegerField(
        default=5,
        help_text='Priority (1=highest, 10=lowest)'
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'scheduler_jobs'
        verbose_name = 'Scheduler Job'
        verbose_name_plural = 'Scheduler Jobs'
        ordering = ['scheduled_time', 'priority']
        indexes = [
            models.Index(fields=['status', 'scheduled_time']),
            models.Index(fields=['tenant', 'scheduled_time']),
            models.Index(fields=['status', 'next_retry_at']),
            models.Index(fields=['status', 'claimed_by']),
        ]

    def __str__(self):
        return f"Job {self.id} - {self.template_name} @ {self.scheduled_time}"

    def save(self, *args, **kwargs):
        # Generate job hash if not set
        if not self.job_hash:
            self.job_hash = self._generate_hash()
        super().save(*args, **kwargs)

    def _generate_hash(self):
        """Generate unique hash for deduplication."""
        # Include campaign_id, template_type, and a random UUID suffix to ensure uniqueness
        # for multiple messages with the same template at the same time
        import uuid as uuid_module
        unique_suffix = str(uuid_module.uuid4())[:8]
        hash_source = (
            f"{self.tenant_id}-{self.campaign_id}-{self.template_name}-"
            f"{self.template_type}-{self.scheduled_time.isoformat()}-{unique_suffix}"
        )
        return hashlib.md5(hash_source.encode()).hexdigest()

    @property
    def success_rate(self):
        """Calculate success rate percentage."""
        if self.total_recipients == 0:
            return 0.0
        return (self.sent_count / self.total_recipients) * 100


class SchedulerJobRecipient(models.Model):
    """
    Individual recipient tracking for each scheduler job.

    Supports:
    - Error isolation per recipient (one failure does not block others)
    - Custom parameters per recipient
    - Full result tracking
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    job = models.ForeignKey(
        SchedulerJob,
        on_delete=models.CASCADE,
        related_name='recipients',
        help_text='Parent scheduler job'
    )

    # Contact reference (from Contact API - not modified)
    contact_id = models.UUIDField(
        null=True,
        blank=True,
        help_text='Reference to messaging.Contact.id'
    )
    phone_number = models.CharField(
        max_length=20,
        help_text='Recipient phone number'
    )
    contact_name = models.CharField(
        max_length=255,
        blank=True,
        help_text='Contact name for reference'
    )

    # Personalized params (override job defaults)
    custom_body_params = models.JSONField(
        default=list,
        blank=True,
        help_text='Custom body parameters for this recipient'
    )

    # Status
    status = models.CharField(
        max_length=20,
        choices=RecipientStatus.choices,
        default=RecipientStatus.PENDING,
        db_index=True
    )

    # Result
    whatsapp_message_id = models.CharField(
        max_length=255,
        blank=True,
        help_text='WhatsApp message ID if sent'
    )
    error_code = models.CharField(
        max_length=50,
        blank=True,
        help_text='Error code if failed'
    )
    error_message = models.TextField(
        blank=True,
        help_text='Error message if failed'
    )

    # Retry tracking
    retry_count = models.PositiveSmallIntegerField(
        default=0,
        help_text='Number of retry attempts for this recipient'
    )

    # Timing
    sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When message was sent'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'scheduler_job_recipients'
        verbose_name = 'Scheduler Job Recipient'
        verbose_name_plural = 'Scheduler Job Recipients'
        ordering = ['created_at']
        unique_together = ['job', 'phone_number']
        indexes = [
            models.Index(fields=['job', 'status']),
            models.Index(fields=['phone_number']),
        ]

    def __str__(self):
        return f"{self.phone_number} - {self.status}"
