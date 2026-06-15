"""
Inbox Admin Registration.
Read-only views of inbox conversations/messages for debugging in Django admin.
"""
from django.contrib import admin
from .models import InboxConversation, InboxMessage


@admin.register(InboxConversation)
class InboxConversationAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'tenant', 'customer_phone', 'customer_name',
        'last_message', 'last_message_time', 'unread_count', 'updated_at',
    ]
    list_filter = ['tenant']
    search_fields = ['customer_phone', 'customer_name']
    readonly_fields = [
        'id', 'tenant', 'customer_phone', 'customer_name',
        'last_message', 'last_message_time', 'unread_count',
        'created_at', 'updated_at',
    ]
    ordering = ['-last_message_time']


@admin.register(InboxMessage)
class InboxMessageAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'tenant', 'conversation', 'direction',
        'type', 'status', 'meta_message_id', 'created_at',
    ]
    list_filter = ['tenant', 'direction', 'type', 'status']
    search_fields = ['meta_message_id', 'conversation__customer_phone']
    readonly_fields = [
        'id', 'tenant', 'conversation', 'meta_message_id',
        'direction', 'type', 'content_json', 'status',
        'timestamp', 'error_code', 'error_message', 'created_at',
    ]
    ordering = ['-created_at']
