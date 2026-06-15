"""
Serializers for Tenant models including Agency.
"""
from rest_framework import serializers
from django.contrib.auth import get_user_model
from tenants.models import (
    Agency, Tenant, TenantConfig, AuditLog, 
    ConfigProvider, TenantStatus, PlanType
)

User = get_user_model()


# ============================================
# AGENCY SERIALIZERS
# ============================================

class AgencySerializer(serializers.ModelSerializer):
    """Serializer for agency details."""
    client_count = serializers.IntegerField(read_only=True)
    
    class Meta:
        model = Agency
        fields = [
            'id', 'name', 'slug', 'contact_email', 'phone',
            'status', 'commission_percent', 'client_count',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class AgencyCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating agency with admin user."""
    admin_email = serializers.EmailField(write_only=True, required=True)
    admin_first_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    admin_last_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    admin_password = serializers.CharField(write_only=True, required=True, min_length=8)
    
    class Meta:
        model = Agency
        fields = [
            'id', 'name', 'slug', 'contact_email', 'phone',
            'commission_percent',
            'admin_email', 'admin_first_name', 'admin_last_name', 'admin_password'
        ]
        read_only_fields = ['id']
    
    def create(self, validated_data):
        # Extract admin user data
        admin_email = validated_data.pop('admin_email')
        admin_first_name = validated_data.pop('admin_first_name', '')
        admin_last_name = validated_data.pop('admin_last_name', '')
        admin_password = validated_data.pop('admin_password')
        
        # Create agency
        agency = Agency.objects.create(**validated_data)
        
        # Create agency admin user
        from users.models import UserRole
        User.objects.create_user(
            email=admin_email,
            password=admin_password,
            first_name=admin_first_name,
            last_name=admin_last_name,
            role=UserRole.AGENCY_ADMIN,
            agency=agency
        )
        
        return agency


# ============================================
# TENANT SERIALIZERS
# ============================================

class TenantSerializer(serializers.ModelSerializer):
    """Serializer for tenant details."""
    # Use annotated _user_count from viewset's get_queryset to avoid N+1
    user_count = serializers.IntegerField(source='_user_count', read_only=True, default=0)
    campaigns_count = serializers.IntegerField(source='_campaign_count', read_only=True, default=0)
    agency_name = serializers.CharField(source='agency.name', read_only=True)
    webhook_url = serializers.CharField(read_only=True)
    webhook_token = serializers.CharField(read_only=True)
    
    class Meta:
        model = Tenant
        fields = [
            'id', 'name', 'slug', 'business_type', 
            'agency', 'agency_name', 'status',
            # Plan & Limits
            'plan_type', 'monthly_message_limit', 'active_users_limit',
            'api_rate_limit', 'plan_expiry_date',
            # Settings
            'timezone', 'domain', 'logo',
            # Webhook Configuration
            'webhook_url', 'webhook_token',
            # Feature Toggles
            'whatsapp_enabled', 'campaigns_enabled', 
            'webhooks_enabled', 'ai_features_enabled',
            # Meta
            'user_count', 'campaigns_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'webhook_url', 'webhook_token', 'created_at', 'updated_at']


class TenantBasicSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for tenant members to view their own tenant details.
    Exposes only safe, non-sensitive fields.
    """
    agency_name = serializers.CharField(source='agency.name', read_only=True)
    
    class Meta:
        model = Tenant
        fields = [
            'id', 'name', 'slug', 'business_type',
            'agency_name', 'status',
            # Plan Info
            'plan_type', 'plan_expiry_date',
            # Settings
            'timezone', 'domain',
            # Feature Toggles
            'whatsapp_enabled', 'campaigns_enabled',
            'webhooks_enabled', 'ai_features_enabled',
            # Meta
            'created_at'
        ]
        read_only_fields = [
            'id', 'name', 'slug', 'business_type',
            'agency_name', 'status', 'plan_type', 'plan_expiry_date',
            'timezone', 'domain', 'whatsapp_enabled', 'campaigns_enabled',
            'webhooks_enabled', 'ai_features_enabled', 'created_at'
        ]


class TenantCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating tenant with admin user and optional API keys.
    
    This is the main endpoint for Super Admin client creation.
    """
    # Admin User (auto-created)
    admin_email = serializers.EmailField(write_only=True, required=True)
    admin_first_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    admin_last_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    admin_phone = serializers.CharField(write_only=True, required=False, allow_blank=True)
    admin_password = serializers.CharField(write_only=True, required=True, min_length=8)
    
    # WhatsApp API Keys (required for client creation, encrypted)
    wa_access_token = serializers.CharField(write_only=True, required=True)
    wa_phone_number_id = serializers.CharField(write_only=True, required=True)
    wa_business_account_id = serializers.CharField(write_only=True, required=True)
    wa_webhook_verify_token = serializers.CharField(write_only=True, required=False, allow_blank=True)
    wa_app_id = serializers.CharField(write_only=True, required=False, allow_blank=True)
    
    # Webhook config (auto-generated, read-only for response)
    webhook_url = serializers.CharField(read_only=True)
    webhook_token = serializers.CharField(read_only=True)
    
    class Meta:
        model = Tenant
        fields = [
            'id', 'name', 'slug', 'business_type', 'agency', 'status',
            # Plan & Limits
            'plan_type', 'monthly_message_limit', 'active_users_limit',
            'api_rate_limit', 'plan_expiry_date',
            # Settings
            'timezone', 'domain', 'logo',
            # Webhook (auto-generated, read-only)
            'webhook_url', 'webhook_token',
            # Feature Toggles
            'whatsapp_enabled', 'campaigns_enabled', 
            'webhooks_enabled', 'ai_features_enabled',
            # Admin User (write-only)
            'admin_email', 'admin_first_name', 'admin_last_name', 
            'admin_phone', 'admin_password',
            # WhatsApp Keys (write-only)
            'wa_access_token', 'wa_phone_number_id',
            'wa_business_account_id', 'wa_webhook_verify_token',
            'wa_app_id'
        ]
        read_only_fields = ['id', 'webhook_url', 'webhook_token']
    
    def validate_admin_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('User with this email already exists')
        return value
    
    def create(self, validated_data):
        # Extract admin user data
        admin_email = validated_data.pop('admin_email')
        admin_first_name = validated_data.pop('admin_first_name', '')
        admin_last_name = validated_data.pop('admin_last_name', '')
        admin_phone = validated_data.pop('admin_phone', '')
        admin_password = validated_data.pop('admin_password')
        
        # Extract WhatsApp API keys
        wa_access_token = validated_data.pop('wa_access_token', '')
        wa_phone_number_id = validated_data.pop('wa_phone_number_id', '')
        wa_business_account_id = validated_data.pop('wa_business_account_id', '')
        wa_webhook_verify_token = validated_data.pop('wa_webhook_verify_token', '')
        wa_app_id = validated_data.pop('wa_app_id', '')
        
        # Create tenant
        tenant = Tenant.objects.create(**validated_data)
        
        # Create tenant admin user
        from users.models import UserRole
        User.objects.create_user(
            email=admin_email,
            password=admin_password,
            first_name=admin_first_name,
            last_name=admin_last_name,
            phone=admin_phone,
            role=UserRole.TENANT_ADMIN,
            tenant=tenant
        )
        
        # Create WhatsApp API configs (encrypted)
        if wa_access_token:
            config = TenantConfig(
                tenant=tenant,
                provider=ConfigProvider.META_WHATSAPP,
                key_name='access_token'
            )
            config.set_value(wa_access_token)
            config.save()
        
        if wa_phone_number_id:
            config = TenantConfig(
                tenant=tenant,
                provider=ConfigProvider.META_WHATSAPP,
                key_name='phone_number_id'
            )
            config.set_value(wa_phone_number_id)
            config.save()
        
        if wa_business_account_id:
            config = TenantConfig(
                tenant=tenant,
                provider=ConfigProvider.META_WHATSAPP,
                key_name='business_account_id'
            )
            config.set_value(wa_business_account_id)
            config.save()
        
        if wa_webhook_verify_token:
            config = TenantConfig(
                tenant=tenant,
                provider=ConfigProvider.META_WHATSAPP,
                key_name='webhook_verify_token'
            )
            config.set_value(wa_webhook_verify_token)
            config.save()
        
        if wa_app_id:
            config = TenantConfig(
                tenant=tenant,
                provider=ConfigProvider.META_WHATSAPP,
                key_name='app_id'
            )
            config.set_value(wa_app_id)
            config.save()
        
        return tenant


class TenantUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating tenant (no admin/key creation)."""
    
    class Meta:
        model = Tenant
        fields = [
            'name', 'business_type', 'agency', 'status',
            'plan_type', 'monthly_message_limit', 'active_users_limit',
            'api_rate_limit', 'plan_expiry_date',
            'timezone', 'domain', 'logo',
            'whatsapp_enabled', 'campaigns_enabled', 
            'webhooks_enabled', 'ai_features_enabled'
        ]


# ============================================
# TENANT CONFIG SERIALIZERS
# ============================================

class TenantConfigSerializer(serializers.ModelSerializer):
    """
    Serializer for tenant config.
    🔐 Never exposes decrypted values - shows masked value only.
    """
    # Class-level constant set for O(1) lookup performance
    PLAINTEXT_SAFE_KEYS = {'phone_number_id', 'business_account_id', 'app_id'}
    
    provider_display = serializers.CharField(source='get_provider_display', read_only=True)
    masked_value = serializers.SerializerMethodField()
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)
    
    class Meta:
        model = TenantConfig
        fields = [
            'id', 'tenant', 'tenant_name', 'provider', 'provider_display',
            'key_name', 'masked_value', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_masked_value(self, obj):
        """
        Return value based on security allow-list (secure by default).
        - SuperAdmin: always return full plaintext value (for management)
        - Safe fields (phone_number_id, business_account_id): actual value
        - All other fields: masked by default
        """
        try:
            value = obj.get_value()
            
            # SuperAdmin can see all values in plaintext for management
            request = self.context.get('request')
            if request and hasattr(request, 'user') and request.user.is_authenticated:
                if request.user.role == 'SUPER_ADMIN':
                    return value
            
            # If a key is on the safe list, return its actual value
            if obj.key_name in self.PLAINTEXT_SAFE_KEYS:
                return value
            
            # By default, mask all other values
            if len(value) <= 8:
                return '●' * len(value)
            return '●' * (len(value) - 4) + value[-4:]
        except Exception:
            return '●●●●●●●●'


class TenantConfigCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating/updating tenant config.
    Accepts plain value and encrypts it.
    """
    value = serializers.CharField(write_only=True, required=True)
    
    class Meta:
        model = TenantConfig
        fields = ['id', 'tenant', 'provider', 'key_name', 'value', 'is_active']
        read_only_fields = ['id']
    
    def create(self, validated_data):
        plain_value = validated_data.pop('value')
        config = TenantConfig(**validated_data)
        config.set_value(plain_value)
        config.save()
        return config
    
    def update(self, instance, validated_data):
        if 'value' in validated_data:
            plain_value = validated_data.pop('value')
            instance.set_value(plain_value)
        
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        instance.save()
        return instance


# ============================================
# AUDIT LOG SERIALIZERS
# ============================================

class AuditLogSerializer(serializers.ModelSerializer):
    """Serializer for audit log entries."""
    performed_by_email = serializers.CharField(source='performed_by.email', read_only=True)
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)
    agency_name = serializers.CharField(source='agency.name', read_only=True)
    
    class Meta:
        model = AuditLog
        fields = [
            'id', 'tenant', 'tenant_name', 'agency', 'agency_name',
            'action', 'performed_by', 'performed_by_email',
            'metadata', 'ip_address', 'timestamp'
        ]
        read_only_fields = '__all__'
