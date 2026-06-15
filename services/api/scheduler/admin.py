"""
Django admin configuration for scheduler models.
"""
from django.contrib import admin
from django.utils.html import format_html
from .models import SchedulerJob, SchedulerJobRecipient


class SchedulerJobRecipientInline(admin.TabularInline):
    """Inline for viewing recipients in job admin."""
    model = SchedulerJobRecipient
    extra = 0
    readonly_fields = [
        'phone_number', 'status', 'whatsapp_message_id',
        'error_code', 'error_message', 'sent_at'
    ]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(SchedulerJob)
class SchedulerJobAdmin(admin.ModelAdmin):
    """Admin for scheduler jobs."""
    list_display = [
        'id', 'tenant', 'template_name', 'scheduled_time',
        'status_badge', 'recipient_stats', 'created_at'
    ]
    list_filter = ['status', 'tenant', 'scheduled_time']
    search_fields = ['template_name', 'job_hash', 'tenant__name']
    readonly_fields = [
        'id', 'job_hash', 'processing_started_at', 'completed_at',
        'claimed_by', 'claimed_at', 'celery_task_id',
        'sent_count', 'failed_count', 'created_at', 'updated_at'
    ]
    ordering = ['-scheduled_time']
    inlines = [SchedulerJobRecipientInline]

    fieldsets = (
        ('Job Info', {
            'fields': ('id', 'tenant', 'campaign', 'status', 'priority')
        }),
        ('Template', {
            'fields': (
                'template_id', 'template_name', 'language_code',
                'header_image_url', 'body_params', 'button_params'
            )
        }),
        ('Scheduling', {
            'fields': ('scheduled_time', 'job_hash')
        }),
        ('Processing', {
            'fields': (
                'processing_started_at', 'completed_at',
                'claimed_by', 'claimed_at', 'celery_task_id'
            )
        }),
        ('Retry', {
            'fields': ('retry_count', 'max_retries', 'next_retry_at', 'error_message')
        }),
        ('Statistics', {
            'fields': ('total_recipients', 'sent_count', 'failed_count')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )

    def status_badge(self, obj):
        """Display status with color badge."""
        colors = {
            'pending': '#6c757d',
            'processing': '#007bff',
            'completed': '#28a745',
            'partial_failure': '#ffc107',
            'failed': '#dc3545',
            'cancelled': '#6c757d',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px; font-size: 11px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'

    def recipient_stats(self, obj):
        """Display recipient statistics."""
        return format_html(
            '{} / {} / {}',
            obj.sent_count, obj.failed_count, obj.total_recipients
        )
    recipient_stats.short_description = 'Sent/Failed/Total'


@admin.register(SchedulerJobRecipient)
class SchedulerJobRecipientAdmin(admin.ModelAdmin):
    """Admin for scheduler job recipients."""
    list_display = [
        'id', 'job', 'phone_number', 'status', 'whatsapp_message_id', 'sent_at'
    ]
    list_filter = ['status', 'job__tenant']
    search_fields = ['phone_number', 'whatsapp_message_id', 'job__template_name']
    readonly_fields = [
        'id', 'whatsapp_message_id', 'error_code', 'error_message',
        'sent_at', 'created_at'
    ]
    ordering = ['-created_at']

    fieldsets = (
        ('Recipient Info', {
            'fields': ('id', 'job', 'contact_id', 'phone_number', 'contact_name')
        }),
        ('Parameters', {
            'fields': ('custom_body_params',)
        }),
        ('Status', {
            'fields': ('status', 'retry_count')
        }),
        ('Result', {
            'fields': ('whatsapp_message_id', 'error_code', 'error_message', 'sent_at')
        }),
        ('Timestamps', {
            'fields': ('created_at',)
        }),
    )
