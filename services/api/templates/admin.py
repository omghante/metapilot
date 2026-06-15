from django.contrib import admin
from templates.models import WhatsAppTemplate


@admin.register(WhatsAppTemplate)
class WhatsAppTemplateAdmin(admin.ModelAdmin):
    """Admin configuration for WhatsApp templates."""
    list_display = [
        'template_name', 'has_variables', 'has_buttons',
        'assigned_client_count', 'is_active', 'created_at'
    ]
    list_filter = ['is_active', 'has_variables', 'has_buttons', 'created_at']
    search_fields = ['template_name']
    filter_horizontal = ['assigned_clients']
    readonly_fields = ['id', 'created_at', 'updated_at', 'created_by']
    
    fieldsets = (
        ('Template Details', {
            'fields': ('id', 'template_name', 'header_image')
        }),
        ('Variables', {
            'fields': ('has_variables', 'variables')
        }),
        ('Buttons', {
            'fields': ('has_buttons', 'buttons')
        }),
        ('Preview Images', {
            'fields': ('preview_image_with_vars', 'preview_image_without_vars')
        }),
        ('Assignment', {
            'fields': ('assigned_clients',)
        }),
        ('Status', {
            'fields': ('is_active', 'created_by', 'created_at', 'updated_at')
        }),
    )
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
