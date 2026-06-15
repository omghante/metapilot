"""
Inbox Models.

New tables for the real-time chat inbox extension layer.
These are SEPARATE from existing messaging.Conversation and messaging.Message tables.
They are specifically designed for the inbox UI with:
  - Denormalized last_message / unread_count for fast list rendering
  - meta_message_id tracking for deduplication
  - tenant-scoped indexing for multi-tenancy
  - content_json for full rich-message storage
"""
import uuid
from django.db import models


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------

class InboxMessageDirection(models.TextChoices):
    INBOUND = 'INBOUND', 'Inbound'
    OUTBOUND = 'OUTBOUND', 'Outbound'


class InboxMessageType(models.TextChoices):
    TEXT = 'TEXT', 'Text'
    IMAGE = 'IMAGE', 'Image'
    DOCUMENT = 'DOCUMENT', 'Document'
    AUDIO = 'AUDIO', 'Audio'
    VIDEO = 'VIDEO', 'Video'
    STICKER = 'STICKER', 'Sticker'
    LOCATION = 'LOCATION', 'Location'
    CONTACTS = 'CONTACTS', 'Contacts'
    INTERACTIVE = 'INTERACTIVE', 'Interactive'
    REACTION = 'REACTION', 'Reaction'
    TEMPLATE = 'TEMPLATE', 'Template'
    UNSUPPORTED = 'UNSUPPORTED', 'Unsupported'


class InboxMessageStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    SENT = 'SENT', 'Sent'
    DELIVERED = 'DELIVERED', 'Delivered'
    READ = 'READ', 'Read'
    FAILED = 'FAILED', 'Failed'


# ---------------------------------------------------------------------------
# InboxConversation
# ---------------------------------------------------------------------------

class InboxConversation(models.Model):
    """
    Inbox-specific conversation record.

    Stores a denormalized snapshot of the latest message state to avoid
    expensive joins when rendering the inbox list.  One per (tenant, customer_phone).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Tenant FK – read-only after creation
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='inbox_conversations',
        db_index=True,
    )

    # Customer identity
    customer_phone = models.CharField(
        max_length=30,
        help_text='Customer WhatsApp phone in E.164 format (e.g. +919876543210)',
    )
    customer_name = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Resolved display name; updated from profile or contact book',
    )

    # Denormalized last-message snapshot for cheap list rendering
    last_message = models.TextField(
        blank=True,
        default='',
        help_text='Preview text of the most recent message',
    )
    last_message_time = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text='Timestamp of the most recent message',
    )

    # Unread counter (incremented on inbound, reset on agent open)
    unread_count = models.PositiveIntegerField(default=0)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'inbox_conversations'
        verbose_name = 'Inbox Conversation'
        verbose_name_plural = 'Inbox Conversations'
        # One conversation thread per tenant + phone
        unique_together = [('tenant', 'customer_phone')]
        ordering = ['-last_message_time']
        indexes = [
            # Fast ordered list fetch per tenant
            models.Index(
                fields=['tenant', '-last_message_time'],
                name='idx_inbox_conv_tenant_time',
            ),
            # Customer lookup within tenant
            models.Index(
                fields=['tenant', 'customer_phone'],
                name='idx_inbox_conv_tenant_phone',
            ),
        ]

    def __str__(self):
        return f"[{self.tenant.name}] {self.customer_name or self.customer_phone}"


# ---------------------------------------------------------------------------
# InboxMessage
# ---------------------------------------------------------------------------

class InboxMessage(models.Model):
    """
    Individual message stored in the chat inbox.

    Stores the complete content_json payload from Meta alongside a
    normalised text preview for quick rendering.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Tenant FK for direct tenant-scoped queries without conversation join
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='inbox_messages',
        db_index=True,
    )

    # Parent conversation
    conversation = models.ForeignKey(
        InboxConversation,
        on_delete=models.CASCADE,
        related_name='messages',
    )

    # Meta/WhatsApp message identifier (for deduplication and status tracking)
    meta_message_id = models.CharField(
        max_length=200,
        blank=True,
        db_index=True,
        help_text='WhatsApp message ID from Meta Graph API',
    )

    # Direction and classification
    direction = models.CharField(
        max_length=10,
        choices=InboxMessageDirection.choices,
        db_index=True,
    )
    type = models.CharField(
        max_length=20,
        choices=InboxMessageType.choices,
        default=InboxMessageType.TEXT,
    )

    # Rich content – full Meta payload stored as JSON
    content_json = models.JSONField(
        default=dict,
        blank=True,
        help_text='Full message payload as received from / sent to Meta',
    )

    # Delivery status
    status = models.CharField(
        max_length=20,
        choices=InboxMessageStatus.choices,
        default=InboxMessageStatus.PENDING,
        db_index=True,
    )

    # Original Meta timestamp (epoch integer sent in webhook)
    timestamp = models.BigIntegerField(
        null=True,
        blank=True,
        help_text='Epoch timestamp from Meta webhook payload',
    )

    # Error details (outbound failures)
    error_code = models.CharField(max_length=50, blank=True)
    error_message = models.TextField(blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'inbox_messages'
        verbose_name = 'Inbox Message'
        verbose_name_plural = 'Inbox Messages'
        # Ordered chronologically per conversation
        ordering = ['created_at']
        indexes = [
            # Paginated message fetch per conversation
            models.Index(
                fields=['conversation', 'created_at'],
                name='idx_inbox_msg_conv_created',
            ),
            # Tenant-level message search
            models.Index(
                fields=['tenant', '-created_at'],
                name='idx_inbox_msg_tenant_created',
            ),
            # Deduplication and status update by meta_message_id
            models.Index(
                fields=['meta_message_id'],
                name='idx_inbox_msg_meta_id',
            ),
        ]

    def __str__(self):
        return (
            f"[{self.direction}] {self.meta_message_id or self.id} "
            f"({self.status})"
        )
