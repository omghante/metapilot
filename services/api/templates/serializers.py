"""
Serializers for WhatsApp Template management.
"""
from rest_framework import serializers
from templates.models import WhatsAppTemplate, CachedMetaTemplate, VariableType, ButtonType, HeaderMediaType
from tenants.models import Tenant


class VariableSerializer(serializers.Serializer):
    """Serializer for template variables."""
    name = serializers.CharField(max_length=100)
    type = serializers.ChoiceField(choices=VariableType.choices)


class ButtonSerializer(serializers.Serializer):
    """Serializer for template buttons."""
    text = serializers.CharField(max_length=100)
    type = serializers.ChoiceField(choices=ButtonType.choices)
    value = serializers.CharField(max_length=500)


# ========================================
# UNIVERSAL TEMPLATE METADATA SERIALIZERS
# ========================================

class TemplateMediaConfigSerializer(serializers.Serializer):
    """Serializer for template media configuration."""
    enabled = serializers.BooleanField(default=False)
    allowed_types = serializers.ListField(
        child=serializers.ChoiceField(choices=['image', 'video']),
        default=list
    )
    multiple = serializers.BooleanField(default=False)


class VariableItemSerializer(serializers.Serializer):
    """Serializer for individual variable item."""
    key = serializers.CharField(max_length=100)
    order = serializers.IntegerField(min_value=1)
    type = serializers.ChoiceField(choices=['text', 'number'])
    description = serializers.CharField(max_length=255, required=False, allow_blank=True)


class VariablesConfigSerializer(serializers.Serializer):
    """Serializer for variables configuration."""
    enabled = serializers.BooleanField(default=False)
    variable_type = serializers.ChoiceField(
        choices=['text', 'number', 'mixed'],
        default='text'
    )
    variables = serializers.ListField(
        child=VariableItemSerializer(),
        default=list
    )


class ButtonItemSerializer(serializers.Serializer):
    """Serializer for individual button item."""
    type = serializers.ChoiceField(choices=['URL', 'PHONE', 'QUICK_REPLY'])
    label = serializers.CharField(max_length=100)
    value = serializers.CharField(max_length=500)


class ButtonsConfigSerializer(serializers.Serializer):
    """Serializer for buttons configuration."""
    enabled = serializers.BooleanField(default=False)
    buttons = serializers.ListField(
        child=ButtonItemSerializer(),
        default=list
    )


class PreviewAssetsSerializer(serializers.Serializer):
    """Serializer for preview assets."""
    with_variables = serializers.CharField(required=False, allow_blank=True)
    without_variables = serializers.CharField(required=False, allow_blank=True)


class TemplateAssignSerializer(serializers.Serializer):
    """Serializer for assigning templates to clients."""
    client_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1
    )


class WhatsAppTemplateSerializer(serializers.ModelSerializer):
    """
    Full template serializer for SuperAdmin.
    Includes all fields and computed properties.
    """
    assigned_client_count = serializers.IntegerField(read_only=True)
    variable_count = serializers.IntegerField(read_only=True)
    button_count = serializers.IntegerField(read_only=True)
    created_by_email = serializers.CharField(source='created_by.email', read_only=True)
    assigned_client_names = serializers.SerializerMethodField()
    
    class Meta:
        model = WhatsAppTemplate
        fields = [
            'id', 'template_id', 'language', 'template_name',
            'header_image',
            'header_media_type', 'header_media_image', 'header_media_video',
            'has_variables', 'variables', 'variable_count',
            'has_buttons', 'buttons', 'button_count',
            'preview_image_with_vars', 'preview_image_without_vars',
            'assigned_clients', 'assigned_client_count', 'assigned_client_names',
            'is_active', 'created_by', 'created_by_email',
            'created_at', 'updated_at',
            # Universal template metadata fields
            'template_type', 'template_media', 'variables_config',
            'buttons_config', 'preview_assets'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by']
    
    def get_assigned_client_names(self, obj):
        """Return list of assigned client names."""
        return list(obj.assigned_clients.values_list('name', flat=True))


class WhatsAppTemplateCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating/updating templates.
    Includes validation for variables and buttons.
    """
    variables = serializers.ListField(
        child=VariableSerializer(),
        required=False,
        default=list
    )
    buttons = serializers.ListField(
        child=ButtonSerializer(),
        required=False,
        default=list
    )
    assigned_clients = serializers.PrimaryKeyRelatedField(
        queryset=Tenant.objects.all(),
        many=True,
        required=False
    )
    
    class Meta:
        model = WhatsAppTemplate
        fields = [
            'template_id', 'language', 'template_name',
            'header_image',
            'header_media_type', 'header_media_image', 'header_media_video',
            'has_variables', 'variables',
            'has_buttons', 'buttons',
            'preview_image_with_vars', 'preview_image_without_vars',
            'assigned_clients',
            'is_active',
            # Universal template metadata fields
            'template_type', 'template_media', 'variables_config',
            'buttons_config', 'preview_assets'
        ]
    
    def validate_template_name(self, value):
        """Ensure template name is unique (case-insensitive)."""
        qs = WhatsAppTemplate.objects.filter(
            template_name__iexact=value,
            is_active=True
        )
        # Exclude current instance on update
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                'A template with this name already exists.'
            )
        return value
    
    def validate(self, attrs):
        """Cross-field validation."""
        # Note: has_variables and has_buttons are now just boolean flags
        # The actual variables/buttons are defined in Meta WhatsApp templates
        # So we don't require variables/buttons arrays to be filled
        
        # Validate assigned clients exist
        assigned_clients = attrs.get('assigned_clients', [])
        for client in assigned_clients:
            if not Tenant.objects.filter(pk=client.pk).exists():
                raise serializers.ValidationError({
                    'assigned_clients': f'Client with ID {client.pk} does not exist.'
                })
        
        return attrs


class ApprovedMetaTemplateSerializer(serializers.ModelSerializer):
    """
    Serializer for CachedMetaTemplate records shaped to match the Template interface.
    Used for the campaign 'Add Message' template dropdown.
    Only returns APPROVED templates from the Meta Graph API cache.
    """
    # Map CachedMetaTemplate fields → frontend Template interface shape
    template_name = serializers.CharField(source='name')
    template_id = serializers.CharField(source='meta_template_id')
    template_type = serializers.SerializerMethodField()
    header_media_type = serializers.SerializerMethodField()
    has_variables = serializers.SerializerMethodField()

    class Meta:
        model = CachedMetaTemplate
        fields = [
            'id', 'template_id', 'template_name', 'language',
            'template_type', 'header_media_type',
            'has_variables', 'has_buttons',
            'body_text', 'status', 'category',
            'components',
        ]

    def get_template_type(self, obj) -> str:
        """Lowercase Meta category → template_type."""
        return (obj.category or 'marketing').lower()

    def get_header_media_type(self, obj) -> str:
        """Map header_format to frontend header_media_type."""
        fmt = (obj.header_format or '').lower()
        if fmt in ('image',):
            return 'image'
        if fmt in ('video',):
            return 'video'
        return 'none'

    def get_has_variables(self, obj) -> bool:
        """Detect variables by scanning components body text."""
        if obj.body_text and '{{' in obj.body_text:
            return True
        return False


class WhatsAppTemplateClientSerializer(serializers.ModelSerializer):
    """
    Minimal template serializer for clients (tenants).
    Used for legacy WhatsAppTemplate access.
    """
    class Meta:
        model = WhatsAppTemplate
        fields = [
            'id', 'template_id', 'language', 'template_name',
            'header_image',
            'header_media_type', 'header_media_image', 'header_media_video',
            'has_variables', 'variables',
            'has_buttons', 'buttons',
            'preview_image_with_vars', 'preview_image_without_vars',
            # Universal template metadata fields
            'template_type', 'template_media', 'variables_config',
            'buttons_config', 'preview_assets'
        ]
        read_only_fields = [
            'id', 'template_id', 'language', 'template_name',
            'header_image',
            'header_media_type', 'header_media_image', 'header_media_video',
            'has_variables', 'variables',
            'has_buttons', 'buttons',
            'preview_image_with_vars', 'preview_image_without_vars',
            # Universal template metadata fields
            'template_type', 'template_media', 'variables_config',
            'buttons_config', 'preview_assets'
        ]
