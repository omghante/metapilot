"""
Meta Graph API - WhatsApp Message Templates Service.

Fetches approved templates from the WhatsApp Business Account
using the same credentials and API version as the rest of our system.
"""
import requests
import logging
from typing import Dict, Any, Optional, List
from django.conf import settings
from tenants.models import TenantConfig, ConfigProvider

logger = logging.getLogger(__name__)

# Use the same API version as the rest of the system
GRAPH_API_VERSION = getattr(settings, 'META_GRAPH_API_VERSION', 'v18.0')
GRAPH_API_URL = f'https://graph.facebook.com/{GRAPH_API_VERSION}'


class MetaTemplateService:
    """
    Service to interact with Meta Graph API for WhatsApp Message Templates.
    
    Uses tenant-specific credentials from TenantConfig:
    - access_token: System User / permanent token
    - business_account_id: WABA ID
    """
    
    def __init__(self, tenant):
        self.tenant = tenant
        self.access_token = None
        self.waba_id = None
        self._load_credentials()
    
    def _load_credentials(self):
        """Load encrypted WhatsApp credentials for tenant."""
        try:
            token_config = TenantConfig.objects.filter(
                tenant=self.tenant,
                provider=ConfigProvider.META_WHATSAPP,
                key_name='access_token',
                is_active=True
            ).first()
            
            waba_config = TenantConfig.objects.filter(
                tenant=self.tenant,
                provider=ConfigProvider.META_WHATSAPP,
                key_name='business_account_id',
                is_active=True
            ).first()
            
            if token_config:
                self.access_token = token_config.get_value()
            if waba_config:
                self.waba_id = waba_config.get_value()
                
        except Exception as e:
            logger.error(f"Failed to load Meta credentials for {self.tenant.name}: {e}")
    
    @property
    def is_configured(self) -> bool:
        """Check if Meta API is properly configured for this tenant."""
        return bool(self.access_token and self.waba_id)
    
    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with authorization."""
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
    
    def fetch_templates(
        self,
        limit: int = 100,
        after: Optional[str] = None,
        before: Optional[str] = None,
        status_filter: Optional[str] = None,
        name_search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Fetch message templates from Meta Graph API.
        
        GET /{WABA_ID}/message_templates
        
        Args:
            limit: Number of templates per page (max 100)
            after: Cursor for next page
            before: Cursor for previous page
            status_filter: Filter by status (APPROVED, PENDING, REJECTED)
            name_search: Filter by template name (partial match)
            
        Returns:
            Dict with 'templates' list and 'paging' info
        """
        if not self.is_configured:
            return {
                'success': False,
                'error': 'WhatsApp Business Account not configured. Please add access_token and business_account_id.',
                'templates': [],
                'paging': {}
            }
        
        url = f'{GRAPH_API_URL}/{self.waba_id}/message_templates'
        
        params = {
            'limit': min(limit, 100),
            'fields': ','.join([
                'id', 'name', 'status', 'category', 'language',
                'components', 'quality_score', 'rejected_reason',
            ]),
        }
        
        if after:
            params['after'] = after
        if before:
            params['before'] = before
        if status_filter:
            params['status'] = status_filter
        if name_search:
            params['name'] = name_search
        
        try:
            response = requests.get(
                url,
                params=params,
                headers=self._get_headers(),
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                templates = data.get('data', [])
                paging = data.get('paging', {})
                
                return {
                    'success': True,
                    'templates': templates,
                    'paging': {
                        'cursors': paging.get('cursors', {}),
                        'next': 'next' in paging,
                        'previous': 'previous' in paging,
                    },
                    'total_count': len(templates),
                }
            else:
                error_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
                error_msg = error_data.get('error', {}).get('message', response.text)
                logger.error(f"Meta API error ({response.status_code}): {error_msg}")
                
                return {
                    'success': False,
                    'error': error_msg,
                    'error_code': response.status_code,
                    'templates': [],
                    'paging': {}
                }
                
        except requests.exceptions.Timeout:
            logger.error("Meta API timeout while fetching templates")
            return {
                'success': False,
                'error': 'Request timed out. Please try again.',
                'templates': [],
                'paging': {}
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Meta API request error: {e}")
            return {
                'success': False,
                'error': f'Network error: {str(e)}',
                'templates': [],
                'paging': {}
            }
    
    def fetch_single_template(self, template_id: str) -> Dict[str, Any]:
        """
        Fetch a single template by its Meta template ID.
        
        GET /{template_id}
        """
        if not self.is_configured:
            return {'success': False, 'error': 'Not configured'}
        
        url = f'{GRAPH_API_URL}/{template_id}'
        params = {
            'fields': 'id,name,status,category,language,components,quality_score,rejected_reason'
        }
        
        try:
            response = requests.get(
                url,
                params=params,
                headers=self._get_headers(),
                timeout=15
            )
            
            if response.status_code == 200:
                return {'success': True, 'template': response.json()}
            else:
                error_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
                return {
                    'success': False,
                    'error': error_data.get('error', {}).get('message', response.text)
                }
        except Exception as e:
            logger.error(f"Error fetching template {template_id}: {e}")
            return {'success': False, 'error': str(e)}
