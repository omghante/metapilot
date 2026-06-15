"""
Views for WhatsApp Template management.
Client read-only access + Meta Graph API integration.
"""
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from api.permissions import IsTenantMember, IsTenantMemberOrAgencyAdmin
from templates.models import WhatsAppTemplate, CachedMetaTemplate
from tenants.models import Tenant
from templates.serializers import (
    WhatsAppTemplateClientSerializer,
    ApprovedMetaTemplateSerializer,
)


class ClientTemplateListView(generics.ListAPIView):
    """
    List APPROVED Meta templates for the current tenant's campaign dropdown.

    TENANT MEMBERS (TENANT_ADMIN, TENANT_USER) or AGENCY ADMINS

    Endpoint: GET /api/templates/client/
    Query Params:
    - tenant: (optional) Tenant ID for agency admin to fetch templates for a specific client

    Returns only CachedMetaTemplate records that are:
    - Belonging to the user's tenant (or specified tenant for agency admins)
    - status = APPROVED (approved by Meta Graph API)

    Used for campaign 'Add Message' template dropdown.
    """
    permission_classes = [IsAuthenticated, IsTenantMemberOrAgencyAdmin]
    serializer_class = ApprovedMetaTemplateSerializer

    def _resolve_tenant(self):
        """Return the tenant to query, or None if not resolvable."""
        user = self.request.user
        tenant_id = self.request.query_params.get('tenant')

        if user.role == 'SUPER_ADMIN':
            if tenant_id:
                try:
                    return Tenant.objects.get(id=tenant_id)
                except (Tenant.DoesNotExist, ValueError):
                    return None
            return None  # SuperAdmin without tenant_id: return all

        if user.role == 'AGENCY_ADMIN' and user.agency:
            if tenant_id:
                try:
                    return Tenant.objects.get(id=tenant_id, agency=user.agency)
                except (Tenant.DoesNotExist, ValueError):
                    return None
            return None

        return getattr(user, 'tenant', None)

    def get_queryset(self):
        """Return APPROVED CachedMetaTemplate records for the resolved tenant."""
        user = self.request.user
        tenant_id = self.request.query_params.get('tenant')

        # SuperAdmin without tenant filter: return all APPROVED templates across all tenants
        if user.role == 'SUPER_ADMIN' and not tenant_id:
            return CachedMetaTemplate.objects.filter(
                status='APPROVED'
            ).order_by('name')

        tenant = self._resolve_tenant()
        if not tenant:
            return CachedMetaTemplate.objects.none()

        return CachedMetaTemplate.objects.filter(
            tenant=tenant,
            status='APPROVED'
        ).order_by('name')


class TemplateLibraryView(generics.GenericAPIView):
    """
    Template Library — cached Meta templates with filters & counts.
    
    GET /api/templates/meta/
    
    Query Params:
    - search: Search by template name (case-insensitive contains)
    - category: Filter by category (UTILITY, MARKETING, AUTHENTICATION)
    - status: Filter by status (APPROVED, PENDING, REJECTED)
    - industry: Filter by industry classification
    - feature_group: Filter by feature group
    - use_case: Filter by use case
    - language: Filter by language code
    - has_header: Filter templates with headers (true/false)
    - has_buttons: Filter templates with buttons (true/false)
    - page: Page number (default: 1)
    - page_size: Results per page (default: 50, max: 100)
    
    Response includes:
    - templates: List of cached templates
    - filters: Dynamic filter counts for sidebar
    - pagination: Page info
    """
    permission_classes = [IsAuthenticated]
    
    def _resolve_tenant(self, request):
        """Resolve tenant from user or query param."""
        user = request.user
        if user.tenant:
            return user.tenant, None
        if user.role == 'SUPER_ADMIN':
            tenant_id = request.query_params.get('tenant')
            if not tenant_id:
                return None, Response(
                    {'error': 'SuperAdmin must specify ?tenant=<tenant_id>'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            try:
                return Tenant.objects.get(id=tenant_id), None
            except Tenant.DoesNotExist:
                return None, Response(
                    {'error': 'Tenant not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
        return None, Response(
            {'error': 'No tenant associated with your account'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    def get(self, request):
        from templates.models import CachedMetaTemplate
        from templates.sync_service import get_filter_counts
        
        tenant, error_response = self._resolve_tenant(request)
        if error_response:
            return error_response
        
        # Base queryset
        qs = CachedMetaTemplate.objects.filter(tenant=tenant)
        
        # Auto-sync if no cached templates exist
        if not qs.exists():
            from templates.sync_service import sync_templates_for_tenant
            sync_result = sync_templates_for_tenant(tenant)
            if not sync_result.get('success'):
                return Response({
                    'templates': [],
                    'filters': {},
                    'pagination': {'page': 1, 'page_size': 50, 'total': 0, 'total_pages': 0},
                    'sync_error': sync_result.get('error', 'Failed to sync'),
                })
            # Refresh queryset after sync
            qs = CachedMetaTemplate.objects.filter(tenant=tenant)
        else:
            # Re-sync if any templates are still PENDING and cache is stale (> 30 min old)
            from django.utils import timezone
            from datetime import timedelta
            stale_threshold = timezone.now() - timedelta(minutes=30)
            has_pending = qs.filter(status='PENDING').exists()
            cache_is_stale = qs.filter(last_synced_at__lt=stale_threshold).exists()
            if has_pending and cache_is_stale:
                from templates.sync_service import sync_templates_for_tenant
                sync_templates_for_tenant(tenant)
                # Refresh queryset with updated statuses
                qs = CachedMetaTemplate.objects.filter(tenant=tenant)
        
        # Get filter counts BEFORE applying filters (for sidebar)
        filter_counts = get_filter_counts(tenant)
        
        # Apply filters
        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(name__icontains=search)
        
        category = request.query_params.get('category', '').strip()
        if category:
            qs = qs.filter(category=category)
        
        status_filter = request.query_params.get('status', '').strip()
        if status_filter:
            qs = qs.filter(status=status_filter)
        
        industry = request.query_params.get('industry', '').strip()
        if industry:
            qs = qs.filter(industry=industry)
        
        feature_group = request.query_params.get('feature_group', '').strip()
        if feature_group:
            qs = qs.filter(feature_group=feature_group)
        
        use_case = request.query_params.get('use_case', '').strip()
        if use_case:
            qs = qs.filter(use_case=use_case)
        
        language = request.query_params.get('language', '').strip()
        if language:
            qs = qs.filter(language=language)
        
        has_header = request.query_params.get('has_header', '').strip()
        if has_header:
            qs = qs.filter(has_header=has_header.lower() in ('true', '1'))
        
        has_buttons = request.query_params.get('has_buttons', '').strip()
        if has_buttons:
            qs = qs.filter(has_buttons=has_buttons.lower() in ('true', '1'))
        
        # Pagination
        page = max(1, int(request.query_params.get('page', 1)))
        page_size = min(100, max(1, int(request.query_params.get('page_size', 50))))
        total = qs.count()
        total_pages = max(1, (total + page_size - 1) // page_size)
        
        start = (page - 1) * page_size
        end = start + page_size
        templates = qs[start:end]
        
        # Serialize
        template_list = []
        for t in templates:
            template_list.append({
                'id': str(t.id),
                'meta_template_id': t.meta_template_id,
                'name': t.name,
                'status': t.status,
                'category': t.category,
                'language': t.language,
                'components': t.components,
                'quality_score': t.quality_score,
                'rejected_reason': t.rejected_reason,
                'industry': t.industry,
                'feature_group': t.feature_group,
                'use_case': t.use_case,
                'has_header': t.has_header,
                'header_format': t.header_format,
                'has_buttons': t.has_buttons,
                'button_count': t.button_count,
                'body_text': t.body_text,
                'last_synced_at': t.last_synced_at.isoformat() if t.last_synced_at else None,
            })
        
        return Response({
            'templates': template_list,
            'filters': filter_counts,
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total': total,
                'total_pages': total_pages,
            }
        })


class TemplateLibrarySyncView(generics.GenericAPIView):
    """
    Trigger a sync of templates from Meta Graph API.
    
    POST /api/templates/meta/sync/
    
    Fetches all templates, classifies, and caches in DB.
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        from templates.sync_service import sync_templates_for_tenant
        
        user = request.user
        if user.tenant:
            tenant = user.tenant
        elif user.role == 'SUPER_ADMIN':
            tenant_id = request.data.get('tenant') or request.query_params.get('tenant')
            if not tenant_id:
                return Response(
                    {'error': 'SuperAdmin must specify tenant'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            try:
                tenant = Tenant.objects.get(id=tenant_id)
            except Tenant.DoesNotExist:
                return Response(
                    {'error': 'Tenant not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
        else:
            return Response(
                {'error': 'No tenant associated'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        result = sync_templates_for_tenant(tenant)
        
        if result.get('success'):
            return Response(result)
        else:
            return Response(result, status=status.HTTP_502_BAD_GATEWAY)


class WhatsAppBusinessProfileView(generics.GenericAPIView):
    """
    Fetch WhatsApp Business Profile for the tenant.
    
    GET /api/templates/meta/business-profile/
    
    Returns the business profile including:
    - profile_picture_url
    - about
    - address
    - description
    - email
    - websites
    - vertical (business type)
    
    Uses tenant's phone_number_id and access_token from TenantConfig.
    """
    permission_classes = [IsAuthenticated]
    
    def _resolve_tenant(self, request):
        """Resolve tenant from user or query param."""
        user = request.user
        if user.tenant:
            return user.tenant, None
        if user.role == 'SUPER_ADMIN':
            tenant_id = request.query_params.get('tenant')
            if not tenant_id:
                return None, Response(
                    {'error': 'SuperAdmin must specify ?tenant=<tenant_id>'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            try:
                return Tenant.objects.get(id=tenant_id), None
            except Tenant.DoesNotExist:
                return None, Response(
                    {'error': 'Tenant not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
        return None, Response(
            {'error': 'No tenant associated with your account'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    def get(self, request):
        import requests as http_requests
        import logging
        from django.conf import settings
        from tenants.models import TenantConfig, ConfigProvider
        
        logger = logging.getLogger(__name__)
        
        tenant, error_response = self._resolve_tenant(request)
        if error_response:
            return error_response
        
        # Get WhatsApp credentials
        try:
            token_config = TenantConfig.objects.filter(
                tenant=tenant,
                provider=ConfigProvider.META_WHATSAPP,
                key_name='access_token',
                is_active=True
            ).first()
            
            phone_config = TenantConfig.objects.filter(
                tenant=tenant,
                provider=ConfigProvider.META_WHATSAPP,
                key_name='phone_number_id',
                is_active=True
            ).first()
            
            if not token_config or not phone_config:
                return Response(
                    {'error': 'WhatsApp API not configured for this tenant', 'profile': None},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            access_token = token_config.get_value()
            phone_number_id = phone_config.get_value()
            
        except Exception as e:
            logger.error(f"Failed to load WhatsApp credentials for {tenant.name}: {e}")
            return Response(
                {'error': 'Failed to load credentials'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        # Fetch business profile from Meta Graph API
        api_version = getattr(settings, 'META_GRAPH_API_VERSION', 'v18.0')
        url = f'https://graph.facebook.com/{api_version}/{phone_number_id}/whatsapp_business_profile'
        
        params = {
            'fields': 'about,address,description,email,profile_picture_url,websites,vertical'
        }
        
        headers = {
            'Authorization': f'Bearer {access_token}',
        }
        
        try:
            response = http_requests.get(url, params=params, headers=headers, timeout=15)
            
            if response.status_code == 200:
                data = response.json().get('data', [])
                profile = data[0] if data else {}
                
                return Response({
                    'success': True,
                    'profile': {
                        'profile_picture_url': profile.get('profile_picture_url', ''),
                        'about': profile.get('about', ''),
                        'address': profile.get('address', ''),
                        'description': profile.get('description', ''),
                        'email': profile.get('email', ''),
                        'websites': profile.get('websites', []),
                        'vertical': profile.get('vertical', ''),
                    },
                    'tenant_name': tenant.name,
                })
            else:
                error_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
                error_msg = error_data.get('error', {}).get('message', response.text)
                logger.error(f"Meta API error ({response.status_code}): {error_msg}")
                
                return Response({
                    'success': False,
                    'error': error_msg,
                    'profile': None,
                }, status=status.HTTP_502_BAD_GATEWAY)
                
        except http_requests.exceptions.Timeout:
            return Response({
                'success': False,
                'error': 'Request timed out',
                'profile': None,
            }, status=status.HTTP_504_GATEWAY_TIMEOUT)
        except http_requests.exceptions.RequestException as e:
            logger.error(f"Network error fetching business profile: {e}")
            return Response({
                'success': False,
                'error': f'Network error: {str(e)}',
                'profile': None,
            }, status=status.HTTP_502_BAD_GATEWAY)


class MetaTemplateCreateView(generics.GenericAPIView):
    """
    Create a WhatsApp message template on Meta Graph API.
    
    POST /api/templates/meta/create/
    
    Accepts JSON body with:
    - name: Template name (lowercase, underscores, starts with letter)
    - language: Language code (e.g., en_US)
    - category: UTILITY, MARKETING, or AUTHENTICATION
    - components: Template components array (HEADER, BODY, FOOTER, BUTTONS, CAROUSEL)
    
    For media-based templates, include media files as multipart form data:
    - header_media: File for HEADER component (image/video)
    - card_0_media, card_1_media, ...: Files for carousel card headers
    
    The endpoint handles:
    1. Validation of all fields
    2. Media upload to Meta (Resumable Upload API)
    3. Media handle injection into components
    4. Template submission to Meta for approval
    5. Auto-sync of template cache
    
    Response:
    {
        "success": true,
        "template_id": "123456789",
        "name": "my_template",
        "category": "MARKETING",
        "status": "PENDING",
        "language": "en_US"
    }
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    
    def _resolve_tenant(self, request):
        """Resolve tenant from user or query param."""
        user = request.user
        if user.tenant:
            return user.tenant, None
        if user.role == 'SUPER_ADMIN':
            tenant_id = request.data.get('tenant') or request.query_params.get('tenant')
            if not tenant_id:
                return None, Response(
                    {'success': False, 'error': 'SuperAdmin must specify tenant'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            try:
                return Tenant.objects.get(id=tenant_id), None
            except Tenant.DoesNotExist:
                return None, Response(
                    {'success': False, 'error': 'Tenant not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
        return None, Response(
            {'success': False, 'error': 'No tenant associated with your account'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    def post(self, request):
        import json as json_module
        import logging
        from templates.creation_service import TemplateCreationService
        
        logger = logging.getLogger(__name__)
        
        tenant, error_response = self._resolve_tenant(request)
        if error_response:
            return error_response
        
        # Parse request data
        data = request.data
        
        # Handle JSON string in multipart form
        if isinstance(data, dict):
            raw_components = data.get('components', '[]')
        else:
            raw_components = data.get('components', '[]')
        
        # Parse components if it's a string (from multipart form)
        if isinstance(raw_components, str):
            try:
                components = json_module.loads(raw_components)
            except (json_module.JSONDecodeError, TypeError):
                return Response(
                    {'success': False, 'error': 'Invalid components JSON'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            components = raw_components
        
        name = data.get('name', '').strip()
        language = data.get('language', 'en_US').strip()
        category = data.get('category', 'MARKETING').strip()
        
        # Collect media files from request
        media_files = {}
        
        # Header media
        if 'header_media' in request.FILES:
            header_file = request.FILES['header_media']
            media_files['header_media'] = {
                'data': header_file.read(),
                'content_type': header_file.content_type,
                'filename': header_file.name,
            }
        
        # Carousel card media (card_0_media, card_1_media, ...)
        for key in request.FILES:
            if key.startswith('card_') and key.endswith('_media'):
                card_file = request.FILES[key]
                media_files[key] = {
                    'data': card_file.read(),
                    'content_type': card_file.content_type,
                    'filename': card_file.name,
                }
        
        # Allow category change flag
        allow_category_change_raw = data.get('allow_category_change', 'true')
        if isinstance(allow_category_change_raw, str):
            allow_category_change = allow_category_change_raw.lower() in ('true', '1', 'yes')
        else:
            allow_category_change = bool(allow_category_change_raw)
        
        # Create template
        service = TemplateCreationService(tenant)
        
        result = service.create_template(
            name=name,
            language=language,
            category=category,
            components=components,
            media_files=media_files if media_files else None,
            allow_category_change=allow_category_change,
        )
        
        if result.get('success'):
            # Auto-sync template cache in background
            try:
                from templates.sync_service import sync_templates_for_tenant
                sync_templates_for_tenant(tenant)
            except Exception as sync_err:
                logger.warning(f"Auto-sync after template creation failed: {sync_err}")
            
            return Response(result, status=status.HTTP_201_CREATED)
        else:
            # Determine appropriate HTTP status
            code = result.get('code', '')
            if code == 'VALIDATION_FAILED':
                http_status = status.HTTP_400_BAD_REQUEST
            elif code == 'NOT_CONFIGURED':
                http_status = status.HTTP_400_BAD_REQUEST
            elif code == 'TIMEOUT':
                http_status = status.HTTP_504_GATEWAY_TIMEOUT
            else:
                http_status = status.HTTP_502_BAD_GATEWAY
            
            return Response(result, status=http_status)


class MetaTemplateStatusView(generics.GenericAPIView):
    """
    Check the approval status of a WhatsApp template.
    
    GET /api/templates/meta/status/<template_name>/
    
    Returns:
    {
        "success": true,
        "found": true,
        "templates": [
            {
                "template_id": "123",
                "name": "my_template",
                "status": "APPROVED",
                "category": "MARKETING",
                "language": "en_US",
                "quality_score": "GREEN",
                "rejected_reason": ""
            }
        ],
        "count": 1
    }
    """
    permission_classes = [IsAuthenticated]
    
    def _resolve_tenant(self, request):
        """Resolve tenant from user or query param."""
        user = request.user
        if user.tenant:
            return user.tenant, None
        if user.role == 'SUPER_ADMIN':
            tenant_id = request.query_params.get('tenant')
            if not tenant_id:
                return None, Response(
                    {'success': False, 'error': 'SuperAdmin must specify ?tenant=<tenant_id>'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            try:
                return Tenant.objects.get(id=tenant_id), None
            except Tenant.DoesNotExist:
                return None, Response(
                    {'success': False, 'error': 'Tenant not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
        return None, Response(
            {'success': False, 'error': 'No tenant associated'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    def get(self, request, template_name):
        from templates.creation_service import TemplateCreationService
        
        tenant, error_response = self._resolve_tenant(request)
        if error_response:
            return error_response
        
        service = TemplateCreationService(tenant)
        result = service.get_template_status(template_name)
        
        if result.get('success'):
            return Response(result)
        else:
            return Response(result, status=status.HTTP_502_BAD_GATEWAY)


class MetaTemplateDeleteView(generics.GenericAPIView):
    """
    Delete a WhatsApp message template from Meta.
    
    DELETE /api/templates/meta/delete/<template_name>/
    
    This permanently removes the template from your WABA.
    """
    permission_classes = [IsAuthenticated]
    
    def _resolve_tenant(self, request):
        """Resolve tenant from user or query param."""
        user = request.user
        if user.tenant:
            return user.tenant, None
        if user.role == 'SUPER_ADMIN':
            tenant_id = request.query_params.get('tenant')
            if not tenant_id:
                return None, Response(
                    {'success': False, 'error': 'SuperAdmin must specify ?tenant=<tenant_id>'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            try:
                return Tenant.objects.get(id=tenant_id), None
            except Tenant.DoesNotExist:
                return None, Response(
                    {'success': False, 'error': 'Tenant not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
        return None, Response(
            {'success': False, 'error': 'No tenant associated'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    def delete(self, request, template_name):
        import logging
        from templates.creation_service import TemplateCreationService
        
        logger = logging.getLogger(__name__)
        
        tenant, error_response = self._resolve_tenant(request)
        if error_response:
            return error_response
        
        service = TemplateCreationService(tenant)
        result = service.delete_template(template_name)
        
        if result.get('success'):
            # Sync cache to remove deleted template
            try:
                from templates.sync_service import sync_templates_for_tenant
                sync_templates_for_tenant(tenant)
            except Exception as sync_err:
                logger.warning(f"Auto-sync after template deletion failed: {sync_err}")
            
            return Response({
                'success': True,
                'message': f"Template '{template_name}' deleted successfully"
            })
        else:
            return Response(result, status=status.HTTP_502_BAD_GATEWAY)

