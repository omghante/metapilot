"""
Custom permissions for Multi-Tenant SaaS.
Enforces role-based and tenant-based access control.
"""
from rest_framework import permissions
from users.models import UserRole


class IsSuperAdmin(permissions.BasePermission):
    """
    Allow access only to Super Admins.
    """
    message = 'Super Admin access required.'
    
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.role == UserRole.SUPER_ADMIN
        )


class IsAgencyAdmin(permissions.BasePermission):
    """
    Allow access to Agency Admins and Super Admins.
    """
    message = 'Agency Admin access required.'
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        # Super admin always has access
        if request.user.role == UserRole.SUPER_ADMIN:
            return True
        # Agency admin must have agency
        return (
            request.user.role == UserRole.AGENCY_ADMIN and
            request.user.agency is not None
        )


class IsSuperAdminOrAgencyAdmin(permissions.BasePermission):
    """
    Allow access to Super Admins OR Agency Admins.
    Use this instead of IsSuperAdmin() | IsAgencyAdmin() which doesn't work.
    """
    message = 'Super Admin or Agency Admin access required.'
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        # Super admin always has access
        if request.user.role == UserRole.SUPER_ADMIN:
            return True
        # Agency admin must have agency
        return (
            request.user.role == UserRole.AGENCY_ADMIN and
            request.user.agency is not None
        )


class IsTenantAdmin(permissions.BasePermission):
    """
    Allow access to Tenant Admins and Super Admins.
    """
    message = 'Tenant Admin access required.'
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.role in [UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN]


class IsTenantMember(permissions.BasePermission):
    """
    Allow access to any authenticated tenant member.
    """
    message = 'Tenant membership required.'
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        # Super admin always has access
        if request.user.role == UserRole.SUPER_ADMIN:
            return True
        # Tenant users must have a tenant
        return request.user.tenant is not None


class TenantAccessPermission(permissions.BasePermission):
    """
    Ensure user can only access resources within their tenant.
    
    For object-level permissions, checks if object belongs to user's tenant.
    Super Admins bypass this check.
    """
    message = 'You do not have permission to access this resource.'
    
    def has_permission(self, request, view):
        # Must be authenticated
        if not request.user or not request.user.is_authenticated:
            return False
        # Super admin always has access
        if request.user.role == UserRole.SUPER_ADMIN:
            return True
        # Must have tenant
        return request.user.tenant is not None
    
    def has_object_permission(self, request, view, obj):
        # Super admin always has access
        if request.user.role == UserRole.SUPER_ADMIN:
            return True
        
        # Check if object has tenant_id or tenant attribute
        obj_tenant = getattr(obj, 'tenant', None) or getattr(obj, 'tenant_id', None)
        
        if obj_tenant is None:
            return True  # Object not tenant-scoped
        
        # Compare tenant IDs
        user_tenant_id = request.user.tenant_id
        if hasattr(obj_tenant, 'id'):
            return obj_tenant.id == user_tenant_id
        return obj_tenant == user_tenant_id


class CanManageAPIKeys(permissions.BasePermission):
    """
    Permission for API key management.
    - Super Admin: Can manage all tenants' keys
    - Tenant Admin: Can manage own tenant's keys
    - Tenant User: No access
    """
    message = 'You do not have permission to manage API keys.'
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.role in [UserRole.SUPER_ADMIN, UserRole.TENANT_ADMIN]
    
    def has_object_permission(self, request, view, obj):
        # Super admin can manage any
        if request.user.role == UserRole.SUPER_ADMIN:
            return True
        
        # Tenant admin can only manage own tenant's keys
        if request.user.role == UserRole.TENANT_ADMIN:
            return obj.tenant_id == request.user.tenant_id
        
        return False


class IsTenantMemberOrAgencyAdmin(permissions.BasePermission):
    """
    Allow access to tenant members OR agency admins managing their clients.
    Supports ?tenant_id= query parameter for agency context.
    """
    message = 'Tenant membership or Agency Admin access required.'
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Super admin always has access
        if request.user.role == UserRole.SUPER_ADMIN:
            return True
        
        # Agency admin can access if they have an agency
        if request.user.role == UserRole.AGENCY_ADMIN and request.user.agency:
            return True
        
        # Tenant members can access their own resources
        if request.user.tenant is not None:
            return True
        
        return False


class AgencyTenantAccessPermission(permissions.BasePermission):
    """
    Ensure user can only access resources within their tenant OR
    agency admin can access resources for tenants under their agency.
    
    For object-level permissions, checks if object belongs to user's tenant
    or to a tenant under the agency admin's agency.
    Super Admins bypass this check.
    """
    message = 'You do not have permission to access this resource.'
    
    def has_permission(self, request, view):
        # Must be authenticated
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Super admin always has access
        if request.user.role == UserRole.SUPER_ADMIN:
            return True
        
        # Agency admin can access tenants under their agency
        if request.user.role == UserRole.AGENCY_ADMIN and request.user.agency:
            return True
        
        # Must have tenant
        return request.user.tenant is not None
    
    def has_object_permission(self, request, view, obj):
        # Super admin always has access
        if request.user.role == UserRole.SUPER_ADMIN:
            return True
        
        # Check if object has tenant_id or tenant attribute
        obj_tenant = getattr(obj, 'tenant', None) or getattr(obj, 'tenant_id', None)
        
        if obj_tenant is None:
            return True  # Object not tenant-scoped
        
        # Get the actual tenant object
        if hasattr(obj_tenant, 'id'):
            obj_tenant_id = obj_tenant.id
            obj_tenant_agency = getattr(obj_tenant, 'agency_id', None)
        else:
            obj_tenant_id = obj_tenant
            obj_tenant_agency = None
        
        # Agency admin can access if tenant belongs to their agency
        if request.user.role == UserRole.AGENCY_ADMIN and request.user.agency:
            if obj_tenant_agency == request.user.agency_id:
                return True
            # Need to look up the tenant's agency
            from tenants.models import Tenant
            try:
                tenant = Tenant.objects.get(id=obj_tenant_id)
                if tenant.agency_id == request.user.agency_id:
                    return True
            except Tenant.DoesNotExist:
                pass
        
        # Compare tenant IDs for regular tenant users
        user_tenant_id = request.user.tenant_id
        return obj_tenant_id == user_tenant_id

