from django.contrib import admin
from messaging.models import Contact, Conversation, Message


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ['phone', 'name', 'tenant', 'is_subscribed', 'is_blocked', 'created_at']
    list_filter = ['is_subscribed', 'is_blocked', 'tenant']
    search_fields = ['phone', 'name', 'email']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ['contact', 'status', 'assigned_to', 'last_message_at', 'created_at']
    list_filter = ['status']
    search_fields = ['contact__phone', 'contact__name']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['conversation', 'direction', 'message_type', 'status', 'created_at']
    list_filter = ['direction', 'message_type', 'status']
    search_fields = ['content', 'wa_message_id']
    readonly_fields = ['id', 'created_at']
