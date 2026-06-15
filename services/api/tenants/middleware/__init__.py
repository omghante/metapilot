"""
Tenant resolution middleware.
Extracts tenant from JWT and attaches to request.
"""
from django.http import JsonResponse
from tenants.models import Tenant, TenantStatus


class TenantMiddleware:
    """
    Middleware to resolve tenant from authenticated user.
    
    Flow:
    1. Check if user is authenticated
    2. If super admin, tenant = None (has access to all)
    3. If tenant user, resolve tenant from user.tenant
    4. Validate tenant is active
    5. Attach tenant to request
    
    Skips:
    - Unauthenticated requests (handled by auth)
    - Admin URLs
    - Auth URLs (login, register, etc.)
    """
    
    EXEMPT_PATHS = [
        '/admin/',
        '/api/auth/',
        '/api/docs/',
        '/api/schema/',
        '/health/',
    ]
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Initialize tenant as None
        request.tenant = None
        
        # Skip exempt paths
        if any(request.path.startswith(path) for path in self.EXEMPT_PATHS):
            return self.get_response(request)
        
        # Skip if not authenticated
        if not hasattr(request, 'user') or not request.user.is_authenticated:
            return self.get_response(request)
        
        user = request.user
        
        # Super admin has no tenant restriction
        if user.is_super_admin:
            # Check for X-Tenant-ID header for super admin to act on specific tenant
            tenant_id = request.headers.get('X-Tenant-ID')
            if tenant_id:
                try:
                    request.tenant = Tenant.objects.get(id=tenant_id)
                except Tenant.DoesNotExist:
                    return JsonResponse(
                        {'error': 'Tenant not found'},
                        status=404
                    )
            return self.get_response(request)
        
        # Regular users must have a tenant
        if not user.tenant:
            return JsonResponse(
                {'error': 'User has no tenant assigned'},
                status=403
            )
        
        # Validate tenant is active
        if user.tenant.status != TenantStatus.ACTIVE:
            return JsonResponse(
                {'error': 'Tenant is suspended'},
                status=403
            )
        
        # Attach tenant to request
        request.tenant = user.tenant
        
        return self.get_response(request)
