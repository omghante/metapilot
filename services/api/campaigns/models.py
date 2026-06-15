"""
Campaign models for WhatsApp marketing automation.
Tenant-scoped for multi-tenancy.
"""
import uuid
from django.db import models
from django.conf import settings


# ============================================
# CAMPAIGN STATUS
# ============================================

class CampaignStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    SCHEDULED = 'SCHEDULED', 'Scheduled'
    ACTIVE = 'ACTIVE', 'Active'
    PAUSED = 'PAUSED', 'Paused'
    COMPLETED = 'COMPLETED', 'Completed'
    CANCELLED = 'CANCELLED', 'Cancelled'


class ScheduledMessageStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    SENT = 'SENT', 'Sent'
    FAILED = 'FAILED', 'Failed'
    CANCELLED = 'CANCELLED', 'Cancelled'


class CampaignType(models.TextChoices):
    ANNOUNCEMENT = 'announcement', 'Announcement'
    PROMOTIONAL = 'promotional', 'Promotional'
    REMINDER = 'reminder', 'Reminder'
    FOLLOW_UP = 'follow_up', 'Follow-up'


# ============================================
# CAMPAIGN MODEL
# ============================================

class Campaign(models.Model):
    """
    Marketing campaign for a client (tenant).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Tenant (Client) scope
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='campaigns',
        help_text='Client this campaign belongs to'
    )
    
    # Creator
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_campaigns'
    )
    
    # Campaign details
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    
    # Campaign type
    campaign_type = models.CharField(
        max_length=20,
        choices=CampaignType.choices,
        default=CampaignType.ANNOUNCEMENT,
        help_text='Type of campaign'
    )
    
    # Message template content
    message_template = models.TextField(
        blank=True,
        help_text='Message template content'
    )
    
    # WhatsApp Template
    template_name = models.CharField(
        max_length=255,
        blank=True,
        help_text='WhatsApp message template name'
    )
    template_params = models.JSONField(
        default=list,
        blank=True,
        help_text='Default template parameters'
    )
    template_type = models.CharField(
        max_length=20,
        default='standard',
        blank=True,
        help_text='Template type: standard or carousel'
    )
    header_data = models.JSONField(
        null=True,
        blank=True,
        help_text='Header media: {"type": "image"|"video", "url": "..."}'
    )
    cards_json = models.JSONField(
        null=True,
        blank=True,
        help_text='Carousel cards: [{"header": {...}, "bodyParams": [...], "buttonParams": [...]}]'
    )

    # Status
    status = models.CharField(
        max_length=20,
        choices=CampaignStatus.choices,
        default=CampaignStatus.DRAFT
    )
    
    # Scheduling
    scheduled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the campaign should start'
    )
    start_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Campaign start date'
    )
    end_date = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Campaign end date'
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Target audience
    target_tags = models.JSONField(
        default=list,
        blank=True,
        help_text='Contact tags to target'
    )
    target_all = models.BooleanField(
        default=False,
        help_text='Target all contacts'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'campaigns'
        verbose_name = 'Campaign'
        verbose_name_plural = 'Campaigns'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', '-created_at'], name='campaigns_tenant__f1021b_idx'),
            models.Index(fields=['tenant', 'status'], name='campaigns_tenant__d8e2a0_idx'),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.tenant.name})"
    
    @property
    def recipient_count(self):
        return self.scheduled_messages.count()
    
    @property
    def sent_count(self):
        return self.scheduled_messages.filter(
            status=ScheduledMessageStatus.SENT
        ).count()


# ============================================
# CAMPAIGN MESSAGE MODEL (Individual Schedulable)
# ============================================

class CampaignMessageStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    PROCESSING = 'PROCESSING', 'Processing'
    SENT = 'SENT', 'Sent'
    FAILED = 'FAILED', 'Failed'
    CANCELLED = 'CANCELLED', 'Cancelled'


class CampaignMessage(models.Model):
    """
    Individual message within a campaign with independent scheduling.
    Each message can be scheduled at a different time.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Parent campaign
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name='campaign_messages'
    )
    
    # Link to scheduler job (for status sync)
    scheduler_job = models.ForeignKey(
        'scheduler.SchedulerJob',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='campaign_messages'
    )
    
    # Message details
    name = models.CharField(max_length=255)
    template_name = models.CharField(max_length=255, blank=True)
    template_params = models.JSONField(default=list, blank=True)
    content = models.TextField(blank=True, help_text='Custom message content')

    # Structured template data for carousel and variable templates
    template_type = models.CharField(
        max_length=20, default='standard', blank=True,
        help_text='standard or carousel'
    )
    header_data = models.JSONField(
        null=True, blank=True,
        help_text='Header media: {"type": "image"|"video", "url": "..."}'
    )
    cards_json = models.JSONField(
        null=True, blank=True,
        help_text='Carousel cards: [{"header": {...}, "bodyParams": [...], "buttonParams": []}]'
    )
    
    # Independent scheduling
    scheduled_at = models.DateTimeField(help_text='When this message should be sent')
    
    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=CampaignMessageStatus.choices,
        default=CampaignMessageStatus.PENDING
    )
    
    # Delivery stats (synced from scheduler job)
    sent_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)
    
    # Target audience (optional - defaults to campaign's targets)
    contact_group_id = models.UUIDField(null=True, blank=True)
    target_all = models.BooleanField(default=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'campaign_messages'
        verbose_name = 'Campaign Message'
        verbose_name_plural = 'Campaign Messages'
        ordering = ['scheduled_at']
        indexes = [
            models.Index(fields=['campaign', 'status']),
            models.Index(fields=['scheduled_at', 'status']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.campaign.name})"
    
    @property
    def is_editable(self):
        """Only pending messages can be edited."""
        return self.status == CampaignMessageStatus.PENDING


# ============================================
# SCHEDULED MESSAGE MODEL
# ============================================

class ScheduledMessage(models.Model):
    """
    Individual scheduled message for a campaign recipient.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Relations
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name='scheduled_messages'
    )
    contact = models.ForeignKey(
        'messaging.Contact',
        on_delete=models.CASCADE,
        related_name='scheduled_messages'
    )
    
    # Scheduling
    scheduled_at = models.DateTimeField()
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=ScheduledMessageStatus.choices,
        default=ScheduledMessageStatus.PENDING
    )
    
    # Personalized params (overrides campaign defaults)
    custom_params = models.JSONField(
        default=list,
        blank=True,
        help_text='Contact-specific template params'
    )
    
    # Timestamps
    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'scheduled_messages'
        verbose_name = 'Scheduled Message'
        verbose_name_plural = 'Scheduled Messages'
        ordering = ['scheduled_at']
        indexes = [
            models.Index(fields=['status', 'scheduled_at']),
        ]
    
    def __str__(self):
        return f"{self.campaign.name} → {self.contact.phone}"


# ============================================
# MESSAGE RESULT MODEL
# ============================================

class MessageResult(models.Model):
    """
    Result log for a scheduled message send attempt.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Relations
    scheduled_message = models.ForeignKey(
        ScheduledMessage,
        on_delete=models.CASCADE,
        related_name='results'
    )
    message = models.ForeignKey(
        'messaging.Message',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='campaign_results',
        help_text='Actual message sent (if successful)'
    )
    
    # Result
    success = models.BooleanField(default=False)
    error_code = models.CharField(max_length=50, blank=True)
    error_message = models.TextField(blank=True)
    
    # Timestamps
    attempted_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'message_results'
        verbose_name = 'Message Result'
        verbose_name_plural = 'Message Results'
        ordering = ['-attempted_at']
    
    def __str__(self):
        status = 'Success' if self.success else 'Failed'
        return f"{self.scheduled_message} - {status}"
