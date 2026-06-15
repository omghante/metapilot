"""
Serializers for campaign models.
"""
from rest_framework import serializers
from django.utils import timezone
from campaigns.models import Campaign, CampaignMessage, ScheduledMessage, MessageResult


class CampaignSerializer(serializers.ModelSerializer):
    """Serializer for campaign details."""
    recipient_count = serializers.IntegerField(read_only=True)
    sent_count = serializers.IntegerField(read_only=True)
    created_by_email = serializers.CharField(source='created_by.email', read_only=True)
    display_status = serializers.SerializerMethodField(read_only=True)
    message_count = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = Campaign
        fields = [
            'id', 'tenant', 'created_by', 'created_by_email',
            'name', 'description', 'campaign_type', 'message_template',
            'template_name', 'template_params',
            'status', 'display_status', 'scheduled_at', 'start_date', 'end_date',
            'started_at', 'completed_at',
            'target_tags', 'target_all', 'recipient_count', 'sent_count', 'message_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'started_at', 'completed_at']
    
    def get_display_status(self, obj):
        """User-friendly status based on campaign dates."""
        from django.utils import timezone
        from datetime import date
        import pytz
        # Use IST for consistent date comparison
        ist = pytz.timezone('Asia/Kolkata')
        today = timezone.now().astimezone(ist).date()
        
        # Convert dates to date type for consistent comparison
        start = obj.start_date.date() if hasattr(obj.start_date, 'date') else obj.start_date if obj.start_date else None
        end = obj.end_date.date() if hasattr(obj.end_date, 'date') else obj.end_date if obj.end_date else None
        
        # Use start_date and end_date for status
        if start and end:
            if today < start:
                return 'scheduled'
            elif today > end:
                return 'completed'
            else:
                return 'ongoing'
        elif start:
            if today < start:
                return 'scheduled'
            return 'ongoing'
        
        # Fallback to campaign status if no dates
        if obj.status == 'COMPLETED':
            return 'completed'
        elif obj.status in ['ACTIVE', 'SCHEDULED']:
            return 'scheduled'
        elif obj.status == 'DRAFT':
            return 'draft'
        return obj.status.lower() if obj.status else 'draft'
    
    def get_message_count(self, obj):
        """Count of campaign messages."""
        return obj.campaign_messages.count()


class CampaignCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating campaigns."""
    
    class Meta:
        model = Campaign
        fields = [
            'id', 'name', 'description', 'campaign_type', 'message_template',
            'template_name', 'template_params',
            'scheduled_at', 'start_date', 'end_date',
            'target_tags', 'target_all'
        ]
        read_only_fields = ['id']


class CampaignMessageSerializer(serializers.ModelSerializer):
    """Serializer for campaign messages with independent scheduling."""
    is_editable = serializers.BooleanField(read_only=True)
    display_status = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = CampaignMessage
        fields = [
            'id', 'campaign', 'name', 'template_name', 'template_params', 'content',
            'template_type', 'header_data', 'cards_json',
            'scheduled_at', 'status', 'display_status', 'sent_count', 'failed_count',
            'contact_group_id', 'target_all', 'is_editable',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'campaign', 'status', 'sent_count', 'failed_count', 'created_at', 'updated_at']
    
    def get_display_status(self, obj):
        """User-friendly status: delivered, upcoming, failed, processing"""
        if obj.status == 'SENT':
            return 'delivered'
        elif obj.status == 'FAILED':
            return 'failed'
        elif obj.status == 'PROCESSING':
            return 'processing'
        elif obj.status == 'PENDING':
            # Check if scheduled time is in the future
            if obj.scheduled_at > timezone.now():
                return 'upcoming'
            return 'pending'
        elif obj.status == 'CANCELLED':
            return 'cancelled'
        return obj.status.lower()
    
    def validate(self, attrs):
        """Block updates to non-pending messages."""
        if self.instance and not self.instance.is_editable:
            raise serializers.ValidationError(
                "Cannot modify a message that has already been sent or is processing."
            )
        return attrs


class ScheduledMessageSerializer(serializers.ModelSerializer):
    """Serializer for scheduled message details with error info."""
    contact_phone = serializers.CharField(source='contact.phone', read_only=True)
    contact_name = serializers.CharField(source='contact.name', read_only=True)
    error_code = serializers.SerializerMethodField(read_only=True)
    error_message = serializers.SerializerMethodField(read_only=True)
    display_status = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = ScheduledMessage
        fields = [
            'id', 'campaign', 'contact', 'contact_phone', 'contact_name',
            'scheduled_at', 'status', 'display_status', 'custom_params', 
            'sent_at', 'error_code', 'error_message', 'created_at'
        ]
        read_only_fields = ['id', 'created_at', 'sent_at']
    
    def get_error_code(self, obj):
        """Get error code from the latest result if failed."""
        if obj.status == 'FAILED':
            result = obj.results.order_by('-attempted_at').first()
            return result.error_code if result else None
        return None
    
    def get_error_message(self, obj):
        """Get generic error message if failed. Detailed errors are in internal logs only."""
        if obj.status == 'FAILED':
            result = obj.results.order_by('-attempted_at').first()
            if result and result.error_message:
                return 'Delivery failed. Contact support if the issue persists.'
        return None
    
    def get_display_status(self, obj):
        """User-friendly status label."""
        status_map = {
            'PENDING': 'Pending',
            'SENT': 'Sent',
            'FAILED': 'Failed',
            'CANCELLED': 'Cancelled'
        }
        return status_map.get(obj.status, obj.status)


class MessageResultSerializer(serializers.ModelSerializer):
    """Serializer for message result details."""
    
    class Meta:
        model = MessageResult
        fields = [
            'id', 'scheduled_message', 'message', 'success',
            'error_code', 'error_message', 'attempted_at'
        ]
        read_only_fields = '__all__'


class CampaignStatsSerializer(serializers.Serializer):
    """Serializer for campaign statistics."""
    campaign_id = serializers.UUIDField()
    campaign_name = serializers.CharField()
    total_recipients = serializers.IntegerField()
    pending = serializers.IntegerField()
    sent = serializers.IntegerField()
    failed = serializers.IntegerField()
    cancelled = serializers.IntegerField()

