"""
Chat Inbox Serializers.
Read/write serializers for InboxConversation and InboxMessage.
"""
from rest_framework import serializers
from .models import InboxConversation, InboxMessage


class InboxConversationSerializer(serializers.ModelSerializer):
    """
    Full read serializer for a single inbox conversation.
    Includes a nested preview of recent messages when requested.
    """
    tenant_id = serializers.UUIDField(source='tenant.id', read_only=True)
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)

    class Meta:
        model = InboxConversation
        fields = [
            'id',
            'tenant_id',
            'tenant_name',
            'customer_phone',
            'customer_name',
            'last_message',
            'last_message_time',
            'unread_count',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'tenant_id',
            'tenant_name',
            'last_message',
            'last_message_time',
            'unread_count',
            'created_at',
            'updated_at',
        ]


class InboxConversationListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for the conversation list endpoint.
    Omits heavy fields to keep payload small.
    """
    tenant_id = serializers.UUIDField(source='tenant.id', read_only=True)

    class Meta:
        model = InboxConversation
        fields = [
            'id',
            'tenant_id',
            'customer_phone',
            'customer_name',
            'last_message',
            'last_message_time',
            'unread_count',
            'updated_at',
        ]


class InboxMessageSerializer(serializers.ModelSerializer):
    """
    Full serializer for a single inbox message.
    """
    conversation_id = serializers.UUIDField(source='conversation.id', read_only=True)
    tenant_id = serializers.UUIDField(source='tenant.id', read_only=True)

    class Meta:
        model = InboxMessage
        fields = [
            'id',
            'tenant_id',
            'conversation_id',
            'meta_message_id',
            'direction',
            'type',
            'content_json',
            'status',
            'timestamp',
            'error_code',
            'error_message',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'tenant_id',
            'conversation_id',
            'meta_message_id',
            'direction',
            'status',
            'error_code',
            'error_message',
            'created_at',
        ]


class SendMessageSerializer(serializers.Serializer):
    """
    Input serializer for POST /chat-inbox/messages (outbound send).

    The agent provides:
      - conversation_id : UUID of the existing InboxConversation
      - type            : message type (default TEXT)
      - text            : plain text body (required when type=TEXT)
      - content_json    : rich payload for non-text types (optional)

    The backend resolves the tenant, access_token, and phone_number_id from
    the conversation's tenant configuration.
    """
    conversation_id = serializers.UUIDField()
    type = serializers.ChoiceField(
        choices=['TEXT', 'IMAGE', 'DOCUMENT', 'AUDIO', 'VIDEO', 'TEMPLATE'],
        default='TEXT',
    )
    text = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text='Plain text body (required when type=TEXT)',
    )
    content_json = serializers.JSONField(
        required=False,
        default=dict,
        help_text='Full Meta-format payload for non-text message types',
    )

    def validate(self, data):
        msg_type = data.get('type', 'TEXT')
        text = data.get('text', '').strip()
        content = data.get('content_json', {})

        if msg_type == 'TEXT' and not text and not content:
            raise serializers.ValidationError(
                "Field 'text' is required when type is TEXT."
            )
        return data
