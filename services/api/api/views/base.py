"""
Base views and mixins for tenant-aware API endpoints.
All tenant-scoped ViewSets should inherit from TenantViewSet.
"""
from rest_framework import viewsets, status
from rest_framework.response import Response
from api.permissions import TenantAccessPermission
from users.models import UserRole


class TenantQuerysetMixin:
    """
    Mixin that filters queryset by tenant.
    
    Usage:
        class MyViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
            queryset = MyModel.objects.all()
            tenant_field = 'tenant'  # or 'tenant_id'
    """
    tenant_field = 'tenant'
    
    def get_queryset(self):
        """
        Filter queryset by tenant.
        Super admins see all unless X-Tenant-ID header is set.
        """
        queryset = super().get_queryset()
        user = self.request.user
        
        # Super admin with no tenant filter sees all
        if user.role == UserRole.SUPER_ADMIN and not self.request.tenant:
            return queryset
        
        # Filter by tenant
        if self.request.tenant:
            filter_kwargs = {self.tenant_field: self.request.tenant}
            return queryset.filter(**filter_kwargs)
        
        return queryset.none()


class TenantCreateMixin:
    """
    Mixin that automatically sets tenant on create.
    """
    tenant_field = 'tenant'
    
    def perform_create(self, serializer):
        """Set tenant from request on create."""
        tenant = self.request.tenant or getattr(self.request.user, 'tenant', None)
        if tenant:
            serializer.save(**{self.tenant_field: tenant})
        else:
            serializer.save()


class TenantViewSet(TenantQuerysetMixin, TenantCreateMixin, viewsets.ModelViewSet):
    """
    Base ViewSet for tenant-scoped resources.
    
    Features:
    - Automatic tenant filtering on queryset
    - Automatic tenant assignment on create
    - Tenant access permission enforcement
    
    Usage:
        class ContactViewSet(TenantViewSet):
            queryset = Contact.objects.all()
            serializer_class = ContactSerializer
    """
    permission_classes = [TenantAccessPermission]


class TenantReadOnlyViewSet(TenantQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    """
    Read-only ViewSet for tenant-scoped resources.
    """
    permission_classes = [TenantAccessPermission]
