"""
Serializers for WhatsApp AI Chatbot.
"""
from rest_framework import serializers
from .models import TenantKnowledgeEntry


class KnowledgeEntrySerializer(serializers.ModelSerializer):
    """Serializer for TenantKnowledgeEntry model."""
    
    class Meta:
        model = TenantKnowledgeEntry
        fields = [
            'id', 
            'keywords', 
            'english_response', 
            'marathi_response', 
            'is_active',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate_keywords(self, value):
        """Ensure keywords is a list of strings."""
        if not isinstance(value, list):
            raise serializers.ValidationError("Keywords must be a list")
        if not all(isinstance(k, str) for k in value):
            raise serializers.ValidationError("All keywords must be strings")
        if len(value) == 0:
            raise serializers.ValidationError("At least one keyword is required")
        return value


class KnowledgeEntryCreateSerializer(KnowledgeEntrySerializer):
    """Serializer for creating knowledge entries (tenant auto-assigned)."""
    
    class Meta(KnowledgeEntrySerializer.Meta):
        fields = [
            'id',
            'keywords',
            'english_response',
            'marathi_response',
            'is_active',
            'created_at',
            'updated_at'
        ]
