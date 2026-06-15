"""
Notification models for multi-tenant SaaS platform.
Role-based notifications for Super Admin, Agency Admin, and Client Admin.
"""
import uuid
from django.db import models
from django.conf import settings


class NotificationType(models.TextChoices):
    """Notification type choices."""
    # Operational notifications (for agencies/tenants)
    USER_REGISTERED = 'USER_REGISTERED', 'User Registered'
    CAMPAIGN_COMPLETED = 'CAMPAIGN_COMPLETED', 'Campaign Completed'
    API_RATE_LIMIT = 'API_RATE_LIMIT', 'API Rate Limit Warning'
    QUOTA_WARNING = 'QUOTA_WARNING', 'Quota Warning'
    STATUS_CHANGED = 'STATUS_CHANGED', 'Status Changed'
    PLAN_EXPIRING = 'PLAN_EXPIRING', 'Plan Expiring'
    PAYMENT_FAILED = 'PAYMENT_FAILED', 'Payment Failed'
    NEW_CLIENT = 'NEW_CLIENT', 'New Client Created'
    NEW_AGENCY = 'NEW_AGENCY', 'New Agency Created'
    
    # System/Security notifications (for Super Admin)
    SYSTEM_ERROR = 'SYSTEM_ERROR', 'System Error'
    CAMPAIGN_FAILED = 'CAMPAIGN_FAILED', 'Campaign Failed'
    API_ERROR = 'API_ERROR', 'API Error'
    SECURITY_ALERT = 'SECURITY_ALERT', 'Security Alert'


class NotificationPriority(models.TextChoices):
    """Notification priority levels."""
    LOW = 'LOW', 'Low'
    MEDIUM = 'MEDIUM', 'Medium'
    HIGH = 'HIGH', 'High'
    URGENT = 'URGENT', 'Urgent'


class Notification(models.Model):
    """
    Notification model for user notifications.
    
    Role-based filtering uses indexed ForeignKey fields for fast queries:
    - Super Admin: Sees all SUPER_ADMIN notifications
    - Agency Admin: Sees notifications for their agency (via agency FK)
    - Client Admin: Sees notifications for their tenant (via tenant FK)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # User who receives this notification
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
        help_text='User who receives this notification'
    )
    
    # Direct ForeignKey for fast indexed queries (replaces slow JSON lookups)
    agency = models.ForeignKey(
        'tenants.Agency',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notifications',
        db_index=True,
        help_text='Agency this notification belongs to (for agency-level notifications)'
    )
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='notifications',
        db_index=True,
        help_text='Tenant this notification belongs to (for client-level notifications)'
    )
    
    # Notification details
    notification_type = models.CharField(
        max_length=50,
        choices=NotificationType.choices,
        db_index=True
    )
    priority = models.CharField(
        max_length=20,
        choices=NotificationPriority.choices,
        default=NotificationPriority.MEDIUM
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    
    # Flexible metadata for additional context (campaign_id, etc.)
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text='Additional data: campaign_id, etc.'
    )
    
    # Read status
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    
    # Optional action URL
    action_url = models.CharField(max_length=500, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'notifications'
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read'], name='notif_user_read_idx'),
            models.Index(fields=['user', 'created_at'], name='notif_user_created_idx'),
            models.Index(fields=['notification_type'], name='notif_type_idx'),
            models.Index(fields=['agency', 'is_read'], name='notif_agency_read_idx'),
            models.Index(fields=['tenant', 'is_read'], name='notif_tenant_read_idx'),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.user.email} ({'Read' if self.is_read else 'Unread'})"
    
    def mark_as_read(self):
        """Mark notification as read."""
        if not self.is_read:
            from django.utils import timezone
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])
