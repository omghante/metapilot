"""
DRF serializers for scheduler models.
"""
from rest_framework import serializers
from django.utils import timezone
from .models import SchedulerJob, SchedulerJobRecipient


class SchedulerJobRecipientSerializer(serializers.ModelSerializer):
    """Serializer for recipient details."""

    class Meta:
        model = SchedulerJobRecipient
        fields = [
            'id', 'contact_id', 'phone_number', 'contact_name',
            'custom_body_params', 'status', 'whatsapp_message_id',
            'error_code', 'error_message', 'retry_count', 'sent_at', 'created_at'
        ]
        read_only_fields = [
            'id', 'status', 'whatsapp_message_id', 'error_code',
            'error_message', 'retry_count', 'sent_at', 'created_at'
        ]


class SchedulerJobRecipientCreateSerializer(serializers.Serializer):
    """Serializer for creating recipients."""
    contact_id = serializers.UUIDField(required=False, allow_null=True)
    phone_number = serializers.CharField(max_length=20)
    contact_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    custom_body_params = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list
    )


class SchedulerJobSerializer(serializers.ModelSerializer):
    """Serializer for job details."""
    recipients = SchedulerJobRecipientSerializer(many=True, read_only=True)
    success_rate = serializers.FloatField(read_only=True)
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)
    campaign_name = serializers.CharField(source='campaign.name', read_only=True)

    class Meta:
        model = SchedulerJob
        fields = [
            'id', 'tenant', 'tenant_name', 'campaign', 'campaign_name',
            'template_id', 'template_name', 'language_code',
            'header_image_url', 'body_params', 'button_params',
            'template_type', 'header_data', 'cards_json',
            'scheduled_time', 'job_hash', 'status', 'priority',
            'processing_started_at', 'completed_at', 'error_message',
            'claimed_by', 'claimed_at', 'retry_count', 'max_retries',
            'next_retry_at', 'celery_task_id',
            'total_recipients', 'sent_count', 'failed_count', 'success_rate',
            'created_at', 'updated_at', 'recipients'
        ]
        read_only_fields = [
            'id', 'job_hash', 'status', 'processing_started_at', 'completed_at',
            'claimed_by', 'claimed_at', 'retry_count', 'celery_task_id',
            'total_recipients', 'sent_count', 'failed_count',
            'created_at', 'updated_at'
        ]


class SchedulerJobListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for job list (no recipients)."""
    success_rate = serializers.FloatField(read_only=True)
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)

    class Meta:
        model = SchedulerJob
        fields = [
            'id', 'tenant', 'tenant_name', 'template_name', 'scheduled_time',
            'status', 'priority', 'total_recipients', 'sent_count',
            'failed_count', 'success_rate', 'created_at'
        ]


class SchedulerJobCreateSerializer(serializers.Serializer):
    """Serializer for creating a scheduler job with recipients."""

    # Template info
    template_id = serializers.UUIDField(required=False, allow_null=True)
    template_name = serializers.CharField(max_length=255)
    language_code = serializers.CharField(max_length=10, default='en_US')
    header_image_url = serializers.URLField(max_length=2048, required=False, allow_blank=True)
    body_params = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        default=list
    )
    button_params = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list
    )

    # Scheduling
    scheduled_time = serializers.DateTimeField()
    priority = serializers.IntegerField(min_value=1, max_value=10, default=5)
    max_retries = serializers.IntegerField(min_value=0, max_value=10, default=3)

    # Optional campaign
    campaign_id = serializers.UUIDField(required=False, allow_null=True)

    # Recipients
    recipients = serializers.ListField(
        child=SchedulerJobRecipientCreateSerializer(),
        min_length=1,
        max_length=10000
    )

    def validate_scheduled_time(self, value):
        """Ensure scheduled time is in the future."""
        if value <= timezone.now():
            raise serializers.ValidationError('Scheduled time must be in the future.')
        return value

    def validate_recipients(self, value):
        """Validate recipient list."""
        phones = [r['phone_number'] for r in value]
        if len(phones) != len(set(phones)):
            raise serializers.ValidationError('Duplicate phone numbers found.')
        return value


class SchedulerJobStatusSerializer(serializers.ModelSerializer):
    """Minimal serializer for status polling."""
    pending_count = serializers.SerializerMethodField()

    class Meta:
        model = SchedulerJob
        fields = [
            'id', 'status', 'total_recipients', 'sent_count', 'failed_count',
            'pending_count', 'processing_started_at', 'completed_at', 'error_message'
        ]

    def get_pending_count(self, obj):
        return obj.total_recipients - obj.sent_count - obj.failed_count


class SchedulerStatsSerializer(serializers.Serializer):
    """Serializer for scheduler statistics."""
    pending_jobs = serializers.IntegerField()
    processing_jobs = serializers.IntegerField()
    completed_today = serializers.IntegerField()
    failed_today = serializers.IntegerField()
    total_recipients_today = serializers.IntegerField()
    total_sent_today = serializers.IntegerField()
    success_rate_today = serializers.FloatField()
