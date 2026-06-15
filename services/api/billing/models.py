"""
Billing models for subscription and invoice management.
"""
import uuid
from django.db import models


# ============================================
# PLAN MODEL
# ============================================

class Plan(models.Model):
    """
    Subscription plan with pricing and limits.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    
    # Pricing
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    billing_cycle = models.CharField(
        max_length=20,
        choices=[
            ('MONTHLY', 'Monthly'),
            ('YEARLY', 'Yearly'),
        ],
        default='MONTHLY'
    )
    
    # Limits
    message_limit = models.IntegerField(help_text='Monthly message limit')
    campaign_limit = models.IntegerField(help_text='Max campaigns per month')
    user_limit = models.IntegerField(default=5, help_text='Max users per tenant')
    
    # Features
    features = models.JSONField(default=list, blank=True, help_text='List of included features')
    
    # Status
    is_active = models.BooleanField(default=True)
    is_popular = models.BooleanField(default=False, help_text='Highlight as popular plan')
    
    # Order
    display_order = models.IntegerField(default=0)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'plans'
        verbose_name = 'Plan'
        verbose_name_plural = 'Plans'
        ordering = ['display_order', 'price']
    
    def __str__(self):
        return f"{self.name} - {self.price} {self.currency}/{self.billing_cycle}"


# ============================================
# SUBSCRIPTION MODEL
# ============================================

class SubscriptionStatus(models.TextChoices):
    TRIAL = 'TRIAL', 'Trial'
    ACTIVE = 'ACTIVE', 'Active'
    CANCELLED = 'CANCELLED', 'Cancelled'
    EXPIRED = 'EXPIRED', 'Expired'
    PAST_DUE = 'PAST_DUE', 'Past Due'


class Subscription(models.Model):
    """
    Client subscription to a plan.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Relations
    tenant = models.OneToOneField(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='subscription'
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name='subscriptions'
    )
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.TRIAL
    )
    
    # Dates
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    trial_ends_at = models.DateField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    
    # Payment
    payment_method = models.CharField(max_length=50, blank=True)
    external_subscription_id = models.CharField(
        max_length=255, blank=True,
        help_text='Stripe/Payment provider subscription ID'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'subscriptions'
        verbose_name = 'Subscription'
        verbose_name_plural = 'Subscriptions'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.tenant.name} - {self.plan.name} ({self.status})"


# ============================================
# INVOICE MODEL
# ============================================

class InvoiceStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    PAID = 'PAID', 'Paid'
    FAILED = 'FAILED', 'Failed'
    REFUNDED = 'REFUNDED', 'Refunded'
    VOID = 'VOID', 'Void'


class Invoice(models.Model):
    """
    Invoice for subscription payment.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Relations
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='invoices'
    )
    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invoices'
    )
    
    # Invoice details
    invoice_number = models.CharField(max_length=50, unique=True)
    
    # Amount
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=InvoiceStatus.choices,
        default=InvoiceStatus.PENDING
    )
    
    # Dates
    due_date = models.DateField()
    paid_at = models.DateTimeField(null=True, blank=True)
    
    # Payment
    payment_method = models.CharField(max_length=50, blank=True)
    external_invoice_id = models.CharField(
        max_length=255, blank=True,
        help_text='Stripe/Payment provider invoice ID'
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'invoices'
        verbose_name = 'Invoice'
        verbose_name_plural = 'Invoices'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Invoice {self.invoice_number} - {self.tenant.name}"
    
    def save(self, *args, **kwargs):
        if not self.invoice_number:
            # Generate invoice number
            from django.utils import timezone
            count = Invoice.objects.filter(
                created_at__year=timezone.now().year
            ).count() + 1
            self.invoice_number = f"INV-{timezone.now().year}-{count:06d}"
        if not self.total_amount:
            self.total_amount = self.amount + self.tax_amount
        super().save(*args, **kwargs)
