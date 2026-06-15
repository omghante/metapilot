from django.contrib import admin
from campaigns.models import Campaign, ScheduledMessage, MessageResult


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ['name', 'tenant', 'status', 'scheduled_at', 'created_by', 'created_at']
    list_filter = ['status', 'tenant']
    search_fields = ['name', 'description', 'template_name']
    readonly_fields = ['id', 'created_at', 'updated_at', 'started_at', 'completed_at']


@admin.register(ScheduledMessage)
class ScheduledMessageAdmin(admin.ModelAdmin):
    list_display = ['campaign', 'contact', 'scheduled_at', 'status', 'sent_at']
    list_filter = ['status', 'campaign']
    search_fields = ['contact__phone', 'contact__name']
    readonly_fields = ['id', 'created_at']


@admin.register(MessageResult)
class MessageResultAdmin(admin.ModelAdmin):
    list_display = ['scheduled_message', 'success', 'error_code', 'attempted_at']
    list_filter = ['success']
    readonly_fields = ['id', 'attempted_at']
