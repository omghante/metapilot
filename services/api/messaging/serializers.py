"""
Serializers for messaging models.
"""
from rest_framework import serializers
from messaging.models import Contact, Conversation, Message


class ContactSerializer(serializers.ModelSerializer):
    """Serializer for contact details."""
    conversation_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Contact
        fields = [
            'id', 'tenant', 'phone', 'name', 'email',
            'tags', 'metadata', 'is_subscribed', 'is_blocked',
            'conversation_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_conversation_count(self, obj):
        return obj.conversations.count()


class ContactCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating contacts."""
    
    class Meta:
        model = Contact
        fields = [
            'phone', 'name', 'email', 'tags', 'metadata', 'is_subscribed'
        ]
    
    def validate_phone(self, value):
        """Normalize phone number to digits only and check for duplicates."""
        import re
        # Strip all non-digit characters (including +, spaces, dashes)
        cleaned = re.sub(r'[^\d]', '', value.strip())

        # Normalize: 10-digit Indian number → prepend 91
        if len(cleaned) == 10 and cleaned.isdigit():
            normalized = '91' + cleaned
        # Leading 0 → replace with 91
        elif cleaned.startswith('0') and len(cleaned) == 11:
            normalized = '91' + cleaned[1:]
        else:
            normalized = cleaned  # already has country code as digits

        if not normalized:
            raise serializers.ValidationError("Invalid phone number.")

        # Check for duplicate within same tenant
        request = self.context.get('request')
        tenant = None
        if request:
            if hasattr(request, 'user') and request.user and hasattr(request.user, 'tenant'):
                tenant = request.user.tenant
        if tenant:
            existing = Contact.objects.filter(tenant=tenant, phone=normalized).first()
            if existing:
                raise serializers.ValidationError(
                    f"A contact with this phone number already exists: {existing.name or normalized}"
                )

        return normalized


class MessageSerializer(serializers.ModelSerializer):
    """Serializer for message details."""
    
    class Meta:
        model = Message
        fields = [
            'id', 'conversation', 'wa_message_id', 'direction',
            'message_type', 'status', 'content', 'payload',
            'media_url', 'media_mime_type', 'error_code', 'error_message',
            'sent_at', 'delivered_at', 'read_at', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class MessageSendSerializer(serializers.Serializer):
    """Serializer for sending a new message."""
    contact_id = serializers.UUIDField(required=False)
    phone = serializers.CharField(required=False, max_length=20)
    message_type = serializers.ChoiceField(
        choices=['TEXT', 'TEMPLATE', 'IMAGE', 'DOCUMENT'],
        default='TEXT'
    )
    content = serializers.CharField(required=False, allow_blank=True)
    template_name = serializers.CharField(required=False, allow_blank=True)
    template_params = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list
    )
    media_url = serializers.URLField(required=False, allow_blank=True)
    
    def validate(self, data):
        if not data.get('contact_id') and not data.get('phone'):
            raise serializers.ValidationError(
                'Either contact_id or phone is required'
            )
        if data.get('message_type') == 'TEXT' and not data.get('content'):
            raise serializers.ValidationError(
                'Content is required for text messages'
            )
        if data.get('message_type') == 'TEMPLATE' and not data.get('template_name'):
            raise serializers.ValidationError(
                'Template name is required for template messages'
            )
        return data


class ConversationSerializer(serializers.ModelSerializer):
    """Serializer for conversation details."""
    contact = ContactSerializer(read_only=True)
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Conversation
        fields = [
            'id', 'contact', 'wa_conversation_id', 'status',
            'assigned_to', 'last_message_at', 'last_message',
            'unread_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_last_message(self, obj):
        last = obj.messages.first()
        if last:
            return {
                'id': str(last.id),
                'content': last.content[:100] if last.content else '',
                'direction': last.direction,
                'status': last.status,
                'created_at': last.created_at.isoformat()
            }
        return None
    
    def get_unread_count(self, obj):
        from messaging.models import MessageDirection, MessageStatus
        return obj.messages.filter(
            direction=MessageDirection.INBOUND,
            status__in=[MessageStatus.DELIVERED, MessageStatus.SENT]
        ).count()


class ConversationDetailSerializer(ConversationSerializer):
    """Detailed conversation with messages."""
    messages = MessageSerializer(many=True, read_only=True)
    
    class Meta(ConversationSerializer.Meta):
        fields = ConversationSerializer.Meta.fields + ['messages']


# ============================================
# MEDIA ASSET SERIALIZERS
# ============================================

class MediaAssetSerializer(serializers.ModelSerializer):
    """Serializer for media asset details."""
    uploaded_by_email = serializers.CharField(source='uploaded_by.email', read_only=True)
    file_url = serializers.SerializerMethodField()
    
    class Meta:
        from messaging.models import MediaAsset
        model = MediaAsset
        fields = [
            'id', 'tenant', 'uploaded_by', 'uploaded_by_email',
            'name', 'asset_type', 'file_url', 'file_name',
            'file_size', 'mime_type', 'description', 'tags',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_file_url(self, obj):
        """Return absolute URL for the file."""
        request = self.context.get('request')
        
        # If file is stored in DB, return the serve endpoint URL with token
        if obj.file_data:
            path = f'/api/media/{obj.id}/file/?token={obj.public_token}'
            if request:
                return request.build_absolute_uri(path)
            return f'http://localhost:8000{path}'
        
        # Fallback for legacy filesystem-based entries
        file_url = obj.file_url
        if file_url:
            if file_url.startswith('http://') or file_url.startswith('https://'):
                return file_url
            if request:
                return request.build_absolute_uri(file_url)
            return f'http://localhost:8000{file_url}'
        
        return None


class MediaAssetCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating media assets with file upload support."""
    file = serializers.FileField(write_only=True, required=False)
    
    class Meta:
        from messaging.models import MediaAsset
        model = MediaAsset
        fields = [
            'name', 'asset_type', 'file_url', 'file_name', 'file',
            'file_size', 'mime_type', 'description', 'tags'
        ]
        extra_kwargs = {
            'file_url': {'required': False},
            'file_name': {'required': False},
            'file_size': {'required': False},
            'mime_type': {'required': False},
        }
    
    def validate(self, data):
        """Validate that either file or file_url is provided, and enforce size limit."""
        from messaging.models import MediaAsset
        
        file = data.get('file')
        file_url = data.get('file_url')
        
        if not file and not file_url:
            raise serializers.ValidationError("Either 'file' or 'file_url' must be provided.")
        
        if file and file.size > MediaAsset.MAX_UPLOAD_SIZE:
            max_mb = MediaAsset.MAX_UPLOAD_SIZE / (1024 * 1024)
            raise serializers.ValidationError(
                f"File size ({file.size / (1024*1024):.1f}MB) exceeds the {max_mb:.0f}MB limit."
            )
        
        return data
    
    def create(self, validated_data):
        """Handle file upload and store in PostgreSQL."""
        from messaging.models import MediaAsset, MediaAssetType
        import os
        import uuid
        
        file = validated_data.pop('file', None)
        
        if file:
            # Determine asset type from mime type
            mime_type = file.content_type
            if mime_type.startswith('image/'):
                asset_type = MediaAssetType.IMAGE
            elif mime_type.startswith('video/'):
                asset_type = MediaAssetType.VIDEO
            else:
                asset_type = MediaAssetType.DOCUMENT
            
            # Read file bytes into memory
            file_bytes = file.read()
            
            # Generate a placeholder file_url (will be overwritten after save)
            ext = os.path.splitext(file.name)[1]
            unique_id = uuid.uuid4()
            
            # Store file data in PostgreSQL
            validated_data['file_data'] = file_bytes
            validated_data['content_type'] = mime_type
            validated_data['file_url'] = f'/api/media/{unique_id}/file/'  # placeholder
            validated_data['file_name'] = file.name
            validated_data['file_size'] = len(file_bytes)
            validated_data['mime_type'] = mime_type
            validated_data['asset_type'] = validated_data.get('asset_type', asset_type)
        
        instance = super().create(validated_data)
        
        # Update file_url with the actual ID and token now that we have it
        if file:
            instance.file_url = f'/api/media/{instance.id}/file/?token={instance.public_token}'
            instance.save(update_fields=['file_url'])
        
        return instance


# ============================================
# CONTACT IMPORT SERIALIZERS
# ============================================

class ContactImportSerializer(serializers.ModelSerializer):
    """Serializer for contact import details."""
    uploaded_by_email = serializers.CharField(source='uploaded_by.email', read_only=True)
    
    class Meta:
        from messaging.models import ContactImport
        model = ContactImport
        fields = [
            'id', 'tenant', 'uploaded_by', 'uploaded_by_email',
            'name', 'file_name', 'file_type', 'status',
            'total_rows', 'imported_count', 'duplicate_count', 'error_count',
            'errors', 'apply_tags', 'started_at', 'completed_at', 'created_at'
        ]
        read_only_fields = [
            'id', 'tenant', 'uploaded_by', 'uploaded_by_email',
            'name', 'file_name', 'file_type', 'status',
            'total_rows', 'imported_count', 'duplicate_count', 'error_count',
            'errors', 'apply_tags', 'started_at', 'completed_at', 'created_at'
        ]

