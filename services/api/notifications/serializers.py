"""
Notification serializers for API endpoints.
"""
from rest_framework import serializers
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    """Full notification serializer with all fields."""
    
    class Meta:
        model = Notification
        fields = [
            'id',
            'user',
            'notification_type',
            'priority',
            'title',
            'message',
            'metadata',
            'is_read',
            'read_at',
            'action_url',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'user', 'created_at', 'updated_at', 'read_at']


class NotificationListSerializer(serializers.ModelSerializer):
    """Optimized serializer for list view (excludes metadata for performance)."""
    
    class Meta:
        model = Notification
        fields = [
            'id',
            'notification_type',
            'priority',
            'title',
            'message',
            'is_read',
            'action_url',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class MarkReadSerializer(serializers.Serializer):
    """Serializer for marking notifications as read."""
    notification_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        help_text='List of notification IDs to mark as read. If empty, marks all as read.'
    )
