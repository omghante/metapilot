"""
Admin configuration for Tenant models.
"""
from django.contrib import admin
from tenants.models import Agency, Tenant, TenantConfig, AuditLog


@admin.register(Agency)
class AgencyAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'contact_email', 'status', 'client_count', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['name', 'slug', 'contact_email']
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ['id', 'created_at', 'updated_at']
    
    def client_count(self, obj):
        return obj.tenants.count()
    client_count.short_description = 'Clients'


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'agency', 'status', 'plan_type', 'user_count', 'created_at']
    list_filter = ['status', 'plan_type', 'agency', 'whatsapp_enabled', 'created_at']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ['id', 'created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('id', 'name', 'slug', 'business_type', 'agency', 'status')
        }),
        ('Plan & Limits', {
            'fields': ('plan_type', 'monthly_message_limit', 'active_users_limit', 
                      'api_rate_limit', 'plan_expiry_date')
        }),
        ('Settings', {
            'fields': ('timezone', 'domain', 'logo')
        }),
        ('Feature Toggles', {
            'fields': ('whatsapp_enabled', 'campaigns_enabled', 
                      'webhooks_enabled', 'ai_features_enabled')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def user_count(self, obj):
        return obj.users.count()
    user_count.short_description = 'Users'


@admin.register(TenantConfig)
class TenantConfigAdmin(admin.ModelAdmin):
    list_display = ['tenant', 'provider', 'key_name', 'is_active', 'updated_at']
    list_filter = ['provider', 'is_active', 'tenant']
    search_fields = ['tenant__name', 'key_name']
    readonly_fields = ['id', 'created_at', 'updated_at']
    exclude = ['encrypted_value']  # Never show encrypted value


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['action', 'performed_by', 'tenant', 'agency', 'timestamp']
    list_filter = ['action', 'tenant', 'agency', 'timestamp']
    search_fields = ['action', 'performed_by__email']
    readonly_fields = ['id', 'action', 'performed_by', 'tenant', 'agency', 
                      'metadata', 'ip_address', 'user_agent', 'timestamp']
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
