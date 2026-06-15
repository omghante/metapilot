"""
Messaging models for WhatsApp contact and message management.
Tenant-scoped for multi-tenancy.
"""
import uuid
import secrets
from django.db import models
from django.conf import settings


# ============================================
# MESSAGE TYPES & STATUS
# ============================================

class MessageDirection(models.TextChoices):
    INBOUND = 'INBOUND', 'Inbound'
    OUTBOUND = 'OUTBOUND', 'Outbound'


class MessageStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    SENT = 'SENT', 'Sent'
    DELIVERED = 'DELIVERED', 'Delivered'
    READ = 'READ', 'Read'
    FAILED = 'FAILED', 'Failed'


class MessageType(models.TextChoices):
    TEXT = 'TEXT', 'Text'
    IMAGE = 'IMAGE', 'Image'
    DOCUMENT = 'DOCUMENT', 'Document'
    AUDIO = 'AUDIO', 'Audio'
    VIDEO = 'VIDEO', 'Video'
    STICKER = 'STICKER', 'Sticker'
    LOCATION = 'LOCATION', 'Location'
    CONTACTS = 'CONTACTS', 'Contacts'
    TEMPLATE = 'TEMPLATE', 'Template'
    INTERACTIVE = 'INTERACTIVE', 'Interactive'
    REACTION = 'REACTION', 'Reaction'


class ConversationStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    ARCHIVED = 'ARCHIVED', 'Archived'
    BLOCKED = 'BLOCKED', 'Blocked'


# ============================================
# CONTACT MODEL
# ============================================

class Contact(models.Model):
    """
    WhatsApp contact for a client (tenant).
    Phone number is unique per tenant.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Tenant (Client) scope
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='contacts',
        help_text='Client this contact belongs to'
    )
    
    # Contact info
    phone = models.CharField(max_length=20, db_index=True, help_text='WhatsApp phone number')
    name = models.CharField(max_length=255, blank=True, help_text='Contact name')
    email = models.EmailField(blank=True, null=True)
    
    # Tags and metadata
    tags = models.JSONField(default=list, blank=True, help_text='Contact tags for segmentation')
    metadata = models.JSONField(default=dict, blank=True, help_text='Additional contact data')
    
    # Status
    is_subscribed = models.BooleanField(default=True, help_text='Opted in to receive messages')
    is_blocked = models.BooleanField(default=False)
    
    # Import tracking
    import_source = models.ForeignKey(
        'messaging.ContactImport',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='contacts',
        help_text='The import batch this contact was created from'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'contacts'
        verbose_name = 'Contact'
        verbose_name_plural = 'Contacts'
        unique_together = ['tenant', 'phone']
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', '-created_at'], name='contacts_tenant__61cb55_idx'),
            models.Index(fields=['tenant', 'is_subscribed'], name='contacts_tenant__2cf449_idx'),
        ]
    
    def __str__(self):
        return f"{self.name or self.phone} ({self.tenant.name})"


# ============================================
# CONVERSATION MODEL
# ============================================

class Conversation(models.Model):
    """
    WhatsApp conversation thread with a contact.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Relations
    contact = models.ForeignKey(
        Contact,
        on_delete=models.CASCADE,
        related_name='conversations'
    )
    
    # WhatsApp identifiers
    wa_conversation_id = models.CharField(
        max_length=100, 
        blank=True, 
        db_index=True,
        help_text='WhatsApp conversation ID'
    )
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=ConversationStatus.choices,
        default=ConversationStatus.ACTIVE
    )
    
    # Assigned agent (optional)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_conversations'
    )
    
    # Timestamps
    last_message_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'conversations'
        verbose_name = 'Conversation'
        verbose_name_plural = 'Conversations'
        ordering = ['-last_message_at']
    
    def __str__(self):
        return f"Conversation with {self.contact.phone}"
    
    @property
    def tenant(self):
        """Get tenant from contact for easy access."""
        return self.contact.tenant


# ============================================
# MESSAGE MODEL
# ============================================

class Message(models.Model):
    """
    Individual WhatsApp message (inbound or outbound).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Relations
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='messages'
    )
    
    # WhatsApp identifiers
    wa_message_id = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text='WhatsApp message ID from Meta'
    )
    
    # Message details
    direction = models.CharField(
        max_length=10,
        choices=MessageDirection.choices
    )
    message_type = models.CharField(
        max_length=20,
        choices=MessageType.choices,
        default=MessageType.TEXT
    )
    status = models.CharField(
        max_length=20,
        choices=MessageStatus.choices,
        default=MessageStatus.PENDING
    )
    
    # Content
    content = models.TextField(blank=True, help_text='Text content of message')
    payload = models.JSONField(
        default=dict, 
        blank=True,
        help_text='Full message payload (media, template params, etc.)'
    )
    
    # Media (if applicable)
    media_url = models.URLField(blank=True, null=True)
    media_mime_type = models.CharField(max_length=100, blank=True)
    
    # Error info (if failed)
    error_code = models.CharField(max_length=50, blank=True)
    error_message = models.TextField(blank=True)
    
    # Timestamps
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'messages'
        verbose_name = 'Message'
        verbose_name_plural = 'Messages'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['conversation', '-created_at']),
            models.Index(fields=['wa_message_id']),
        ]
    
    def __str__(self):
        return f"{self.direction} - {self.message_type} ({self.status})"
    
    @property
    def tenant(self):
        """Get tenant for easy access."""
        return self.conversation.contact.tenant


# ============================================
# MEDIA ASSET MODEL (Templates/Banners)
# ============================================

class MediaAssetType(models.TextChoices):
    IMAGE = 'IMAGE', 'Image'
    VIDEO = 'VIDEO', 'Video'
    DOCUMENT = 'DOCUMENT', 'Document'
    TEMPLATE = 'TEMPLATE', 'Template Banner'


class MediaAsset(models.Model):
    """
    Media asset for a client (tenant).
    Used for campaign templates, banners, documents.
    File content is stored directly in PostgreSQL for durability.
    """
    MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5 MB
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Tenant (Client) scope
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='media_assets',
        help_text='Client this media belongs to'
    )
    
    # Uploaded by
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='uploaded_media'
    )
    
    # Media info
    name = models.CharField(max_length=255, help_text='Display name for the asset')
    asset_type = models.CharField(
        max_length=20,
        choices=MediaAssetType.choices,
        default=MediaAssetType.IMAGE
    )
    
    # File storage
    file_url = models.URLField(help_text='URL to the stored file')
    file_name = models.CharField(max_length=255, help_text='Original filename')
    file_size = models.IntegerField(default=0, help_text='File size in bytes')
    mime_type = models.CharField(max_length=100, blank=True)
    
    # Binary file storage in PostgreSQL
    file_data = models.BinaryField(null=True, blank=True, help_text='File content stored in DB')
    content_type = models.CharField(max_length=100, blank=True, default='', help_text='MIME type for serving')
    
    # Public access token for secure unauthenticated serving
    public_token = models.CharField(
        max_length=64, blank=True, default='',
        help_text='Random token required to access file without auth'
    )
    
    # Metadata
    description = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    
    # Status
    is_active = models.BooleanField(default=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'media_assets'
        verbose_name = 'Media Asset'
        verbose_name_plural = 'Media Assets'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} ({self.asset_type}) - {self.tenant.name}"
    
    def save(self, **kwargs):
        if not self.public_token:
            self.public_token = secrets.token_hex(16)
        super().save(**kwargs)


# ============================================
# CONTACT IMPORT MODEL
# ============================================

class ContactImportStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    PROCESSING = 'PROCESSING', 'Processing'
    COMPLETED = 'COMPLETED', 'Completed'
    FAILED = 'FAILED', 'Failed'


class ContactImport(models.Model):
    """
    Track contact import jobs from CSV/XLSX files.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Tenant (Client) scope
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='contact_imports'
    )
    
    # Uploaded by
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='contact_imports'
    )
    
    # File info
    name = models.CharField(max_length=255, blank=True, help_text='Custom name for this import')
    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=20)  # csv, xlsx
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=ContactImportStatus.choices,
        default=ContactImportStatus.PENDING
    )
    
    # Results
    total_rows = models.IntegerField(default=0)
    imported_count = models.IntegerField(default=0)
    duplicate_count = models.IntegerField(default=0)
    error_count = models.IntegerField(default=0)
    errors = models.JSONField(default=list, blank=True)
    
    # Tags to apply to imported contacts
    apply_tags = models.JSONField(default=list, blank=True)
    
    # Timestamps
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'contact_imports'
        verbose_name = 'Contact Import'
        verbose_name_plural = 'Contact Imports'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', '-created_at'], name='contact_imp_tenant__2f8aaa_idx'),
            models.Index(fields=['tenant', 'status'], name='contact_imp_tenant__6c83cc_idx'),
        ]
    
    def __str__(self):
        display_name = self.name or self.file_name
        return f"Import {display_name} ({self.status}) - {self.tenant.name}"

