"""
WhatsApp Template models for campaign management.
SuperAdmin can create templates and assign them to clients.
"""
import uuid
from django.db import models
from django.conf import settings


class VariableType(models.TextChoices):
    """Variable type choices."""
    TEXT = 'text', 'Text'
    NUMBER = 'number', 'Number'


class ButtonType(models.TextChoices):
    """Button type choices."""
    URL = 'URL', 'URL'
    QUICK_REPLY = 'QUICK_REPLY', 'Quick Reply'


class HeaderMediaType(models.TextChoices):
    """Header media type choices."""
    NONE = 'none', 'None'
    IMAGE = 'image', 'Image'
    VIDEO = 'video', 'Video'
    BOTH = 'both', 'Both'


class WhatsAppTemplate(models.Model):
    """
    WhatsApp message template for campaigns.
    
    SuperAdmin creates templates and assigns them to clients (tenants).
    Clients can use assigned templates in their campaigns.
    
    Access Control:
    - SUPER_ADMIN: Full CRUD + assignment
    - TENANT_ADMIN/USER: Read-only for assigned templates
    - AGENCY_ADMIN: No access
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Meta WhatsApp Template ID (required)
    template_id = models.CharField(
        max_length=100,
        help_text='Meta WhatsApp template ID'
    )
    
    # Language code
    language = models.CharField(
        max_length=10,
        default='en_US',
        help_text='Template language code (e.g. en_US, hi_IN, mr_IN)'
    )
    
    # Template details
    template_name = models.CharField(
        max_length=255,
        help_text='Unique template name'
    )
    
    # Legacy header image (kept for backward compatibility)
    header_image = models.ImageField(
        upload_to='templates/headers/',
        blank=True,
        null=True,
        help_text='Template header image for WhatsApp (legacy)'
    )
    
    # New header media support
    header_media_type = models.CharField(
        max_length=10,
        choices=HeaderMediaType.choices,
        default=HeaderMediaType.NONE,
        help_text='Type of header media: none, image, video, or both'
    )
    header_media_image = models.ImageField(
        upload_to='templates/headers/images/',
        blank=True,
        null=True,
        help_text='Header image file'
    )
    header_media_video = models.FileField(
        upload_to='templates/headers/videos/',
        blank=True,
        null=True,
        help_text='Header video file'
    )
    
    # Variables configuration
    has_variables = models.BooleanField(
        default=False,
        help_text='Whether this template uses variables'
    )
    variables = models.JSONField(
        default=list,
        blank=True,
        help_text='List of variables: [{"name": "username", "type": "text"}, ...]'
    )
    
    # Buttons configuration
    has_buttons = models.BooleanField(
        default=False,
        help_text='Whether this template has action buttons'
    )
    buttons = models.JSONField(
        default=list,
        blank=True,
        help_text='List of buttons: [{"text": "Visit", "type": "URL", "value": "https://..."}, ...]'
    )
    
    # Preview images
    preview_image_with_vars = models.ImageField(
        upload_to='templates/previews/',
        blank=True,
        null=True,
        help_text='Preview showing template with sample variable data'
    )
    preview_image_without_vars = models.ImageField(
        upload_to='templates/previews/',
        blank=True,
        null=True,
        help_text='Preview showing template without variables'
    )
    
    # Client assignment (Many-to-Many)
    assigned_clients = models.ManyToManyField(
        'tenants.Tenant',
        related_name='whatsapp_templates',
        blank=True,
        help_text='Clients that can use this template'
    )
    
    # Audit fields
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_templates',
        help_text='SuperAdmin who created this template'
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Soft delete flag'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # ========================================
    # UNIVERSAL TEMPLATE METADATA FIELDS
    # Added for Meta-approved template setup
    # ========================================
    
    # Template type (marketing, utility, authentication)
    template_type = models.CharField(
        max_length=20,
        choices=[
            ('marketing', 'Marketing'),
            ('utility', 'Utility'),
            ('authentication', 'Authentication'),
        ],
        default='marketing',
        help_text='Meta template type'
    )
    
    # Universal media configuration (JSON)
    template_media = models.JSONField(
        default=dict,
        blank=True,
        help_text='Media config: {"enabled": bool, "allowed_types": ["image","video"], "multiple": bool}'
    )
    
    # Enhanced variables configuration (JSON)
    variables_config = models.JSONField(
        default=dict,
        blank=True,
        help_text='Variables config: {"enabled": bool, "variable_type": "text|number|mixed", "variables": [...]}'
    )
    
    # Enhanced buttons configuration (JSON)
    buttons_config = models.JSONField(
        default=dict,
        blank=True,
        help_text='Buttons config: {"enabled": bool, "buttons": [{"type": "URL|PHONE|QUICK_REPLY", "label": "", "value": ""}]}'
    )
    
    # Preview assets URLs (JSON)
    preview_assets = models.JSONField(
        default=dict,
        blank=True,
        help_text='Preview URLs: {"with_variables": "url", "without_variables": "url"}'
    )
    
    class Meta:
        db_table = 'whatsapp_templates'
        verbose_name = 'WhatsApp Template'
        verbose_name_plural = 'WhatsApp Templates'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at'], name='whatsapp_te_created_ca7962_idx'),
            models.Index(fields=['is_active', 'created_at'], name='whatsapp_te_is_acti_af2aeb_idx'),
        ]
    
    def __str__(self):
        return self.template_name
    
    @property
    def assigned_client_count(self):
        """Return the number of assigned clients."""
        return self.assigned_clients.count()
    
    @property
    def variable_count(self):
        """Return the number of variables."""
        return len(self.variables) if self.has_variables else 0
    
    @property
    def button_count(self):
        """Return the number of buttons."""
        return len(self.buttons) if self.has_buttons else 0


# ========================================
# CACHED META TEMPLATE
# For Template Library (fetched from Graph API)
# ========================================

class TemplateStatus(models.TextChoices):
    APPROVED = 'APPROVED', 'Approved'
    PENDING = 'PENDING', 'Pending'
    REJECTED = 'REJECTED', 'Rejected'
    PAUSED = 'PAUSED', 'Paused'
    DISABLED = 'DISABLED', 'Disabled'
    IN_APPEAL = 'IN_APPEAL', 'In Appeal'


class TemplateCategory(models.TextChoices):
    UTILITY = 'UTILITY', 'Utility'
    MARKETING = 'MARKETING', 'Marketing'
    AUTHENTICATION = 'AUTHENTICATION', 'Authentication'


class CachedMetaTemplate(models.Model):
    """
    Cached WhatsApp message template from Meta Graph API.
    
    Periodically synced from the WABA via Graph API.
    Includes internal classification fields for filtering
    (industry, feature_group, use_case) that Meta does not provide.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Tenant this template belongs to
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='cached_meta_templates',
        help_text='Tenant whose WABA this template was fetched from'
    )
    
    # Meta Graph API fields
    meta_template_id = models.CharField(
        max_length=100,
        help_text='Meta Graph API template ID (numeric string)'
    )
    name = models.CharField(max_length=512, help_text='Template name')
    status = models.CharField(
        max_length=20,
        choices=TemplateStatus.choices,
        default=TemplateStatus.PENDING,
        db_index=True,
    )
    category = models.CharField(
        max_length=20,
        choices=TemplateCategory.choices,
        default=TemplateCategory.UTILITY,
        db_index=True,
    )
    language = models.CharField(max_length=20, default='en_US', db_index=True)
    
    # Full components JSON from Meta
    components = models.JSONField(default=list, blank=True)
    
    # Quality & rejection
    quality_score = models.CharField(max_length=50, blank=True, default='')
    rejected_reason = models.TextField(blank=True, default='')
    
    # ============================
    # INTERNAL CLASSIFICATION
    # ============================
    industry = models.CharField(
        max_length=100, blank=True, default='',
        db_index=True,
        help_text='E-commerce, Financial Services, Telecommunication, Healthcare, etc.'
    )
    feature_group = models.CharField(
        max_length=100, blank=True, default='',
        db_index=True,
        help_text='Account Updates, Order Management, Payments, Event Reminder, etc.'
    )
    use_case = models.CharField(
        max_length=200, blank=True, default='',
        db_index=True,
        help_text='Delivery update, Payment reminder, Appointment confirmation, etc.'
    )
    
    # Extracted metadata for fast filtering
    has_header = models.BooleanField(default=False)
    header_format = models.CharField(max_length=20, blank=True, default='')
    has_buttons = models.BooleanField(default=False)
    button_count = models.IntegerField(default=0)
    body_text = models.TextField(blank=True, default='', help_text='Extracted body text for search')
    
    # Sync metadata
    last_synced_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'cached_meta_templates'
        verbose_name = 'Cached Meta Template'
        verbose_name_plural = 'Cached Meta Templates'
        ordering = ['name']
        unique_together = [('tenant', 'meta_template_id', 'language')]
        indexes = [
            models.Index(fields=['tenant', 'status'], name='cached_mt_tenant_status_idx'),
            models.Index(fields=['tenant', 'category'], name='cached_mt_tenant_cat_idx'),
            models.Index(fields=['tenant', 'industry'], name='cached_mt_tenant_ind_idx'),
            models.Index(fields=['tenant', 'feature_group'], name='cached_mt_tenant_feat_idx'),
            models.Index(fields=['name'], name='cached_mt_name_idx'),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.language}) - {self.status}"
