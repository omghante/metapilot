"""
Tenant models for Multi-Tenant SaaS.
Includes Agency, Tenant (Client), TenantConfig, Plan, and AuditLog.

Hierarchy:
Super Admin → Agency (optional) → Client (Tenant) → Users
"""
import uuid
from django.db import models
from django.conf import settings
from cryptography.fernet import Fernet


# ============================================
# AGENCY MODEL (Optional Reseller Layer)
# ============================================

class AgencyStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    SUSPENDED = 'SUSPENDED', 'Suspended'


class Agency(models.Model):
    """
    Agency model representing a reseller/partner.
    Agencies can manage multiple clients.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Basic Info
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, db_index=True)
    
    # Contact
    contact_email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    
    # Status & Billing
    status = models.CharField(
        max_length=20,
        choices=AgencyStatus.choices,
        default=AgencyStatus.ACTIVE
    )
    commission_percent = models.DecimalField(
        max_digits=5, decimal_places=2, 
        default=0, 
        help_text='Commission percentage for billing'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'agencies'
        verbose_name = 'Agency'
        verbose_name_plural = 'Agencies'
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name
    
    @property
    def client_count(self):
        return self.tenants.count()


# ============================================
# PLAN MODEL
# ============================================

class PlanType(models.TextChoices):
    FREE = 'FREE', 'Free'
    STARTER = 'STARTER', 'Starter'
    PRO = 'PRO', 'Pro'
    ENTERPRISE = 'ENTERPRISE', 'Enterprise'


# ============================================
# TENANT (CLIENT) MODEL
# ============================================

class TenantStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    SUSPENDED = 'SUSPENDED', 'Suspended'
    PENDING = 'PENDING', 'Pending'


class BusinessType(models.TextChoices):
    ECOMMERCE = 'ECOMMERCE', 'E-Commerce'
    SERVICE = 'SERVICE', 'Service'
    SAAS = 'SAAS', 'SaaS'
    RETAIL = 'RETAIL', 'Retail'
    HEALTHCARE = 'HEALTHCARE', 'Healthcare'
    EDUCATION = 'EDUCATION', 'Education'
    OTHER = 'OTHER', 'Other'


class Tenant(models.Model):
    """
    Tenant (Client) model representing a business.
    This is the core multi-tenant entity.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Basic Info
    name = models.CharField(max_length=255, help_text='Business name')
    slug = models.SlugField(unique=True, db_index=True)
    business_type = models.CharField(
        max_length=20,
        choices=BusinessType.choices,
        default=BusinessType.OTHER,
        blank=True
    )
    
    # Agency (Optional Parent)
    agency = models.ForeignKey(
        Agency,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tenants',
        help_text='Parent agency (if applicable)'
    )
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=TenantStatus.choices,
        default=TenantStatus.ACTIVE
    )
    
    # Plan & Limits
    plan_type = models.CharField(
        max_length=20,
        choices=PlanType.choices,
        default=PlanType.FREE
    )
    monthly_message_limit = models.IntegerField(default=1000, help_text='Monthly message limit')
    active_users_limit = models.IntegerField(default=5, help_text='Maximum active users')
    api_rate_limit = models.IntegerField(default=60, help_text='API calls per minute')
    plan_expiry_date = models.DateField(null=True, blank=True)
    
    # Settings
    timezone = models.CharField(max_length=50, default='UTC')
    domain = models.CharField(max_length=255, blank=True, null=True)
    logo = models.URLField(blank=True, null=True)
    
    # Webhook Configuration (Auto-generated)
    webhook_token = models.CharField(
        max_length=64,
        unique=True,
        blank=True,
        help_text='Auto-generated webhook verification token for Meta WhatsApp'
    )
    
    # Feature Toggles
    whatsapp_enabled = models.BooleanField(default=True)
    campaigns_enabled = models.BooleanField(default=True)
    webhooks_enabled = models.BooleanField(default=True)
    ai_features_enabled = models.BooleanField(default=False)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'tenants'
        verbose_name = 'Tenant'
        verbose_name_plural = 'Tenants'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status'], name='tenants_status_80d9b6_idx'),
            models.Index(fields=['agency'], name='tenants_agency__1c6eb1_idx'),
            models.Index(fields=['created_at'], name='tenants_created_fc84fe_idx'),
            models.Index(fields=['agency', 'status'], name='tenants_agency__a333b5_idx'),
        ]
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        # Auto-generate webhook token if not set
        if not self.webhook_token:
            import secrets
            self.webhook_token = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)
    
    @property
    def is_active(self):
        return self.status == TenantStatus.ACTIVE
    
    @property
    def user_count(self):
        return self.users.count()
    
    @property
    def webhook_url(self):
        """Return the unique webhook URL for this tenant."""
        return f"{settings.WEBHOOK_BASE_URL.rstrip('/')}/api/wa-chatbot/webhook/{self.id}/"



# ============================================
# TENANT CONFIG (ENCRYPTED API KEYS)
# ============================================

class ConfigProvider(models.TextChoices):
    META_WHATSAPP = 'META_WHATSAPP', 'Meta WhatsApp Business API'
    TWILIO = 'TWILIO', 'Twilio'
    SENDGRID = 'SENDGRID', 'SendGrid'
    CUSTOM = 'CUSTOM', 'Custom'


class TenantConfig(models.Model):
    """
    Encrypted configuration storage for tenant API keys and secrets.
    
    🔐 SECURITY:
    - All values are encrypted using Fernet (AES-256)
    - Never expose decrypted values to frontend
    - Decrypt only when needed for API calls
    
    Common WhatsApp Keys:
    - access_token (WA_TOKEN)
    - phone_number_id (PHONE_ID)
    - business_account_id
    - webhook_verify_token
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name='configs'
    )
    
    # Provider & Key
    provider = models.CharField(
        max_length=50,
        choices=ConfigProvider.choices,
        default=ConfigProvider.META_WHATSAPP
    )
    key_name = models.CharField(
        max_length=100,
        help_text='Key identifier: access_token, phone_number_id, etc.'
    )
    encrypted_value = models.TextField()
    
    # Status
    is_active = models.BooleanField(default=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'tenant_configs'
        verbose_name = 'Tenant Config'
        verbose_name_plural = 'Tenant Configs'
        unique_together = ['tenant', 'provider', 'key_name']
        ordering = ['provider', 'key_name']
    
    def __str__(self):
        return f"{self.tenant.name} - {self.provider} - {self.key_name}"
    
    @staticmethod
    def get_fernet():
        """Get Fernet instance for encryption/decryption."""
        key = settings.FERNET_KEY
        if isinstance(key, str):
            key = key.encode()
        return Fernet(key)
    
    def set_value(self, plain_value: str):
        """Encrypt and store a value."""
        fernet = self.get_fernet()
        self.encrypted_value = fernet.encrypt(plain_value.encode()).decode()
    
    def get_value(self) -> str:
        """Decrypt and return the stored value."""
        fernet = self.get_fernet()
        return fernet.decrypt(self.encrypted_value.encode()).decode()
    
    @classmethod
    def get_config(cls, tenant, provider: str, key_name: str) -> str | None:
        """Retrieve and decrypt a config value for a tenant."""
        try:
            config = cls.objects.get(
                tenant=tenant,
                provider=provider,
                key_name=key_name,
                is_active=True
            )
            return config.get_value()
        except cls.DoesNotExist:
            return None
    
    @classmethod
    def get_whatsapp_config(cls, tenant) -> dict:
        """Get all WhatsApp config for a tenant."""
        configs = cls.objects.filter(
            tenant=tenant,
            provider=ConfigProvider.META_WHATSAPP,
            is_active=True
        )
        return {c.key_name: c.get_value() for c in configs}


# ============================================
# AUDIT LOG
# ============================================

class AuditLog(models.Model):
    """
    Audit log for tracking important actions.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Relations (optional)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs'
    )
    agency = models.ForeignKey(
        Agency,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs'
    )
    
    # Action details
    action = models.CharField(max_length=100, db_index=True)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='audit_logs'
    )
    
    # Additional data
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    
    # Timestamp
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        db_table = 'audit_logs'
        verbose_name = 'Audit Log'
        verbose_name_plural = 'Audit Logs'
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.action} by {self.performed_by} at {self.timestamp}"
    
    @classmethod
    def log(cls, action: str, user=None, tenant=None, agency=None, metadata=None, request=None):
        """Create an audit log entry."""
        ip_address = None
        user_agent = ''
        
        if request:
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip_address = x_forwarded_for.split(',')[0].strip()
            else:
                ip_address = request.META.get('REMOTE_ADDR')
            user_agent = request.META.get('HTTP_USER_AGENT', '')
        
        return cls.objects.create(
            action=action,
            performed_by=user,
            tenant=tenant,
            agency=agency,
            metadata=metadata or {},
            ip_address=ip_address,
            user_agent=user_agent
        )


# ============================================
# FEATURE FLAG MODEL
# ============================================

class FeatureFlag(models.Model):
    """
    Per-tenant feature toggles for enterprise features.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name='feature_flags'
    )
    
    feature_name = models.CharField(max_length=100, db_index=True)
    enabled = models.BooleanField(default=False)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'feature_flags'
        verbose_name = 'Feature Flag'
        verbose_name_plural = 'Feature Flags'
        unique_together = ['tenant', 'feature_name']
    
    def __str__(self):
        status = 'ON' if self.enabled else 'OFF'
        return f"{self.feature_name} ({status}) - {self.tenant.name}"
    
    @classmethod
    def is_enabled(cls, tenant, feature_name: str) -> bool:
        """Check if a feature is enabled for a tenant."""
        try:
            flag = cls.objects.get(tenant=tenant, feature_name=feature_name)
            return flag.enabled
        except cls.DoesNotExist:
            return False


# ============================================
# DATA DELETION REQUEST (GDPR)
# ============================================

class DataDeletionStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    PROCESSING = 'PROCESSING', 'Processing'
    COMPLETED = 'COMPLETED', 'Completed'
    FAILED = 'FAILED', 'Failed'


class DataDeletionRequest(models.Model):
    """
    GDPR data deletion request for a tenant.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name='deletion_requests'
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='deletion_requests'
    )
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=DataDeletionStatus.choices,
        default=DataDeletionStatus.PENDING
    )
    
    # Details
    reason = models.TextField(blank=True)
    data_types = models.JSONField(
        default=list,
        help_text='Types of data to delete: contacts, messages, campaigns, etc.'
    )
    
    # Timestamps
    requested_at = models.DateTimeField(auto_now_add=True)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'data_deletion_requests'
        verbose_name = 'Data Deletion Request'
        verbose_name_plural = 'Data Deletion Requests'
        ordering = ['-requested_at']
    
    def __str__(self):
        return f"Deletion request for {self.tenant.name} ({self.status})"

