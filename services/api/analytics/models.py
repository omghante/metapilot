"""
Analytics models for campaign and message tracking.
"""
import uuid
from django.db import models


class CampaignStats(models.Model):
    """
    Aggregated statistics for a campaign.
    Updated as messages are sent/delivered/read.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    campaign = models.OneToOneField(
        'campaigns.Campaign',
        on_delete=models.CASCADE,
        related_name='stats'
    )
    
    # Counts
    total_sent = models.IntegerField(default=0)
    delivered = models.IntegerField(default=0)
    read = models.IntegerField(default=0)
    failed = models.IntegerField(default=0)
    
    # Rates
    delivery_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    read_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    # Timestamps
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'campaign_stats'
        verbose_name = 'Campaign Stats'
        verbose_name_plural = 'Campaign Stats'
    
    def __str__(self):
        return f"Stats for {self.campaign.name}"
    
    def update_rates(self):
        if self.total_sent > 0:
            self.delivery_rate = (self.delivered / self.total_sent) * 100
            self.read_rate = (self.read / self.total_sent) * 100
        self.save()


class MessageAnalytics(models.Model):
    """
    Per-message analytics tracking.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    message = models.OneToOneField(
        'messaging.Message',
        on_delete=models.CASCADE,
        related_name='analytics'
    )
    
    # Timestamps
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    
    # Latencies (in seconds)
    delivery_latency = models.IntegerField(null=True, blank=True)
    read_latency = models.IntegerField(null=True, blank=True)
    
    class Meta:
        db_table = 'message_analytics'
        verbose_name = 'Message Analytics'
        verbose_name_plural = 'Message Analytics'
    
    def __str__(self):
        return f"Analytics for message {self.message_id}"


class ClientQuota(models.Model):
    """
    Rate limiting and quota tracking per client.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    tenant = models.OneToOneField(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='quota'
    )
    
    # Limits (from plan)
    daily_message_limit = models.IntegerField(default=100)
    monthly_message_limit = models.IntegerField(default=1000)
    
    # Usage
    messages_sent_today = models.IntegerField(default=0)
    messages_sent_this_month = models.IntegerField(default=0)
    
    # Reset tracking
    last_daily_reset = models.DateField(null=True, blank=True)
    last_monthly_reset = models.DateField(null=True, blank=True)
    
    # Timestamps
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'client_quotas'
        verbose_name = 'Client Quota'
        verbose_name_plural = 'Client Quotas'
    
    def __str__(self):
        return f"Quota for {self.tenant.name}"
    
    def can_send_message(self):
        """Check if client can send more messages."""
        return (
            self.messages_sent_today < self.daily_message_limit and
            self.messages_sent_this_month < self.monthly_message_limit
        )
    
    def increment_usage(self):
        """Increment message usage counters."""
        from django.utils import timezone
        today = timezone.now().date()
        
        # Reset daily if new day
        if self.last_daily_reset != today:
            self.messages_sent_today = 0
            self.last_daily_reset = today
        
        # Reset monthly if new month
        if self.last_monthly_reset is None or self.last_monthly_reset.month != today.month:
            self.messages_sent_this_month = 0
            self.last_monthly_reset = today
        
        self.messages_sent_today += 1
        self.messages_sent_this_month += 1
        self.save()


class RateLimitLog(models.Model):
    """
    Rate limit tracking for API calls.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='rate_limit_logs'
    )
    
    endpoint = models.CharField(max_length=255)
    count = models.IntegerField(default=0)
    time_window = models.DateTimeField()
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'rate_limit_logs'
        verbose_name = 'Rate Limit Log'
        verbose_name_plural = 'Rate Limit Logs'
        indexes = [
            models.Index(fields=['tenant', 'endpoint', 'time_window']),
        ]
    
    def __str__(self):
        return f"{self.tenant.name} - {self.endpoint} ({self.count})"
