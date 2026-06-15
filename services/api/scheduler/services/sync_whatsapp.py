"""
Production-grade synchronous WhatsApp client for Celery workers.

Optimized for high-load scenarios (1000+ campaigns, 100000+ messages):
- Connection pooling with requests.Session
- Automatic retries with exponential backoff
- Configurable timeouts
- Rate limiting integration
- Comprehensive error handling
- Thread-safe design for Celery workers
"""
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Any, Dict
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Meta Graph API configuration
GRAPH_API_VERSION = getattr(settings, 'META_GRAPH_API_VERSION', 'v18.0')
GRAPH_API_URL = f'https://graph.facebook.com/{GRAPH_API_VERSION}'

# Error codes requiring special handling
ERROR_CODE_TOKEN_EXPIRED = '190'
ERROR_CODE_RATE_LIMITED = '80007'
ERROR_CODE_INVALID_PARAM = '100'

# Production defaults
DEFAULT_TIMEOUT = (10, 30)  # (connect, read) timeouts
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 0.5
DEFAULT_POOL_CONNECTIONS = 20
DEFAULT_POOL_MAXSIZE = 100


@dataclass
class SendResult:
    """Result of sending a message to a recipient."""
    phone: str
    success: bool
    message_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retry_count: int = 0
    response_time_ms: float = 0


@dataclass
class BatchResult:
    """Aggregated result of a batch send operation."""
    total: int = 0
    sent: int = 0
    failed: int = 0
    results: List[SendResult] = field(default_factory=list)
    total_time_ms: float = 0
    avg_response_time_ms: float = 0


class SyncWhatsAppClient:
    """
    Production-grade synchronous WhatsApp Cloud API client.
    
    Features:
    - Connection pooling for high throughput
    - Automatic retries with exponential backoff
    - Configurable timeouts and rate limiting
    - Thread-safe for Celery worker pools
    - Detailed logging and metrics
    
    Usage:
        client = SyncWhatsAppClient.from_tenant(tenant)
        results = client.send_batch(recipients, template_name)
    """
    
    def __init__(
        self,
        phone_id: str,
        access_token: str,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: tuple = DEFAULT_TIMEOUT,
        pool_connections: int = DEFAULT_POOL_CONNECTIONS,
        pool_maxsize: int = DEFAULT_POOL_MAXSIZE
    ):
        """
        Initialize the client with connection pooling.
        
        Args:
            phone_id: WhatsApp Phone Number ID
            access_token: Meta API access token
            max_retries: Maximum retry attempts for failed requests
            timeout: (connect, read) timeout tuple
            pool_connections: Number of connection pools to cache
            pool_maxsize: Maximum connections per pool
        """
        self.phone_id = phone_id
        self.access_token = access_token
        self.timeout = timeout
        self.url = f'{GRAPH_API_URL}/{phone_id}/messages'
        
        # Create session with connection pooling
        self.session = self._create_session(max_retries, pool_connections, pool_maxsize)
        self.session.headers.update({
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        })
    
    def _create_session(
        self,
        max_retries: int,
        pool_connections: int,
        pool_maxsize: int
    ) -> requests.Session:
        """Create a session with retry logic and connection pooling."""
        session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=DEFAULT_BACKOFF_FACTOR,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"],
            raise_on_status=False  # We handle status errors ourselves
        )
        
        # Configure connection pooling
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize
        )
        
        session.mount('https://', adapter)
        session.mount('http://', adapter)
        
        return session
    
    @classmethod
    def from_tenant(cls, tenant, **kwargs):
        """
        Create client from tenant credentials.
        
        Args:
            tenant: Tenant model instance
            **kwargs: Additional arguments for client initialization
        
        Returns:
            SyncWhatsAppClient instance or None if not configured
        """
        from tenants.models import TenantConfig, ConfigProvider
        
        try:
            phone_id = TenantConfig.get_config(
                tenant, ConfigProvider.META_WHATSAPP, 'phone_number_id'
            )
            access_token = TenantConfig.get_config(
                tenant, ConfigProvider.META_WHATSAPP, 'access_token'
            )
            
            if not phone_id or not access_token:
                logger.warning(f'WhatsApp not configured for tenant {tenant.id}')
                return None
            
            return cls(phone_id, access_token, **kwargs)
        except Exception as e:
            logger.error(f'Error loading WhatsApp config for tenant {tenant.id}: {e}')
            return None
    
    def _build_template_payload(
        self,
        phone: str,
        template_name: str,
        language_code: str = 'en_US',
        header_image: str = None,
        body_params: List[str] = None,
        button_params: List[Any] = None
    ) -> dict:
        """Build the WhatsApp template message payload."""
        # Strip leading + — Meta WhatsApp API expects E.164 digits only (no +)
        phone = phone.lstrip('+')
        payload = {
            'messaging_product': 'whatsapp',
            'to': phone,
            'type': 'template',
            'template': {
                'name': template_name,
                'language': {'code': language_code}
            }
        }
        
        components = []
        
        # Header with image
        if header_image:
            components.append({
                'type': 'header',
                'parameters': [{'type': 'image', 'image': {'link': header_image}}]
            })
        
        # Body parameters
        if body_params:
            body_component = {
                'type': 'body',
                'parameters': [{'type': 'text', 'text': str(p)} for p in body_params]
            }
            components.append(body_component)
        
        # Button parameters
        if button_params:
            for btn in button_params:
                if isinstance(btn, dict):
                    components.append(btn)
        
        if components:
            payload['template']['components'] = components
        
        return payload
    
    def send_template(
        self,
        phone: str,
        template_name: str,
        language_code: str = 'en_US',
        header_image: str = None,
        body_params: List[str] = None,
        button_params: List[Any] = None
    ) -> SendResult:
        """
        Send a template message to a single recipient.
        
        Args:
            phone: Recipient phone number (E.164 format without +)
            template_name: Approved template name
            language_code: Template language code
            header_image: Optional header image URL
            body_params: Optional body text parameters
            button_params: Optional button parameters
        
        Returns:
            SendResult with success/failure details
        """
        payload = self._build_template_payload(
            phone, template_name, language_code,
            header_image, body_params, button_params
        )
        
        start_time = time.time()
        
        try:
            logger.info(
                f'Sending template: name={template_name}, '
                f'lang={language_code}, '
                f'components_count={len(payload.get("template", {}).get("components", []))}'
            )
            logger.debug(
                f'Full payload for phone ***{phone[-4:]}: '
                f'components={payload.get("template", {}).get("components", "none")}'
            )
            
            response = self.session.post(
                self.url,
                json=payload,
                timeout=self.timeout
            )
            
            response_time = (time.time() - start_time) * 1000
            
            if response.ok:
                data = response.json()
                message_id = None
                messages = data.get('messages', [])
                if messages:
                    message_id = messages[0].get('id')
                
                logger.info(
                    f'Sent template: message_id={message_id}, '
                    f'response_time={response_time:.0f}ms'
                )
                
                return SendResult(
                    phone=phone,
                    success=True,
                    message_id=message_id,
                    response_time_ms=response_time
                )
            else:
                error_data = {}
                try:
                    error_data = response.json()
                except Exception:
                    pass
                error_info = error_data.get('error', {})
                logger.error(
                    f'Meta API error: status={response.status_code}, '
                    f'code={error_info.get("code", "unknown")}, '
                    f'message={error_info.get("message", "unknown")}'
                )
                logger.debug(f'Meta API error response body: {response.text[:500]}')
                # Handle error response
                return self._handle_error_response(phone, response, response_time)
                
        except requests.exceptions.Timeout as e:
            response_time = (time.time() - start_time) * 1000
            logger.error(f'Timeout sending to {phone}: {e}')
            return SendResult(
                phone=phone,
                success=False,
                error_code='TIMEOUT',
                error_message=f'Request timeout after {self.timeout}s',
                response_time_ms=response_time
            )
            
        except requests.exceptions.ConnectionError as e:
            response_time = (time.time() - start_time) * 1000
            logger.error(f'Connection error for {phone}: {e}')
            return SendResult(
                phone=phone,
                success=False,
                error_code='CONNECTION_ERROR',
                error_message=str(e),
                response_time_ms=response_time
            )
            
        except requests.exceptions.RequestException as e:
            response_time = (time.time() - start_time) * 1000
            logger.error(f'Request error for {phone}: {e}')
            return SendResult(
                phone=phone,
                success=False,
                error_code='REQUEST_ERROR',
                error_message=str(e),
                response_time_ms=response_time
            )
    
    def _handle_error_response(
        self,
        phone: str,
        response: requests.Response,
        response_time: float
    ) -> SendResult:
        """Handle HTTP error responses from Meta API."""
        error_data = {}
        try:
            error_data = response.json()
        except Exception:
            pass
        
        error_info = error_data.get('error', {})
        error_code = str(error_info.get('code', response.status_code))
        error_message = error_info.get('message', response.text[:200])
        
        # Log special error cases
        if error_code == ERROR_CODE_TOKEN_EXPIRED:
            logger.critical(
                f'ACCESS TOKEN EXPIRED for phone_id {self.phone_id}! '
                f'Please refresh the token in Meta Business Suite.'
            )
        elif error_code == ERROR_CODE_RATE_LIMITED:
            logger.warning(
                f'Rate limited by Meta API. Consider reducing send rate. '
                f'Details: {error_message}'
            )
        elif error_code == ERROR_CODE_INVALID_PARAM:
            logger.warning(f'Invalid parameter for {phone}: {error_message}')
        else:
            logger.error(f'Error sending to {phone}: [{error_code}] {error_message}')
        
        return SendResult(
            phone=phone,
            success=False,
            error_code=error_code,
            error_message=error_message,
            response_time_ms=response_time
        )
    
    def send_template_with_components(
        self,
        phone: str,
        template_name: str,
        language_code: str = 'en_US',
        components: list = None
    ) -> SendResult:
        """
        Send a template message with pre-built components.
        
        This is the v2 method for Universal Send.
        Accepts components from ComponentsBuilder (supports standard + carousel).
        
        Args:
            phone: Recipient phone number (E.164 format without +)
            template_name: Approved template name
            language_code: Template language code
            components: Pre-built components from ComponentsBuilder
            
        Returns:
            SendResult with success/failure details
        """
        # Strip leading + — Meta WhatsApp API expects E.164 digits only (no +)
        phone = phone.lstrip('+')

        payload = {
            'messaging_product': 'whatsapp',
            'to': phone,
            'type': 'template',
            'template': {
                'name': template_name,
                'language': {'code': language_code}
            }
        }
        
        if components:
            payload['template']['components'] = components
        
        start_time = time.time()
        
        try:
            logger.info(
                f'Sending v2 template: name={template_name}, '
                f'lang={language_code}, '
                f'components_count={len(components) if components else 0}'
            )
            
            response = self.session.post(
                self.url,
                json=payload,
                timeout=self.timeout
            )
            
            response_time = (time.time() - start_time) * 1000
            
            if response.ok:
                data = response.json()
                message_id = None
                messages = data.get('messages', [])
                if messages:
                    message_id = messages[0].get('id')
                
                logger.info(
                    f'Sent v2 template: message_id={message_id}, '
                    f'response_time={response_time:.0f}ms'
                )
                
                return SendResult(
                    phone=phone,
                    success=True,
                    message_id=message_id,
                    response_time_ms=response_time
                )
            else:
                error_data = {}
                try:
                    error_data = response.json()
                except Exception:
                    pass
                error_info = error_data.get('error', {})
                logger.error(
                    f'Meta API v2 error: status={response.status_code}, '
                    f'code={error_info.get("code", "unknown")}, '
                    f'message={error_info.get("message", "unknown")}'
                )
                logger.debug(f'Meta API v2 error response body: {response.text[:500]}')
                return self._handle_error_response(phone, response, response_time)
                
        except requests.exceptions.Timeout as e:
            response_time = (time.time() - start_time) * 1000
            logger.error(f'Timeout sending to {phone}: {e}')
            return SendResult(
                phone=phone,
                success=False,
                error_code='TIMEOUT',
                error_message=f'Request timeout after {self.timeout}s',
                response_time_ms=response_time
            )
            
        except requests.exceptions.ConnectionError as e:
            response_time = (time.time() - start_time) * 1000
            logger.error(f'Connection error for {phone}: {e}')
            return SendResult(
                phone=phone,
                success=False,
                error_code='CONNECTION_ERROR',
                error_message=str(e),
                response_time_ms=response_time
            )
            
        except requests.exceptions.RequestException as e:
            response_time = (time.time() - start_time) * 1000
            logger.error(f'Request error for {phone}: {e}')
            return SendResult(
                phone=phone,
                success=False,
                error_code='REQUEST_ERROR',
                error_message=str(e),
                response_time_ms=response_time
            )
    
    def send_batch_with_components(
        self,
        recipients: List[dict],
        template_name: str,
        language_code: str = 'en_US',
        components: list = None,
        delay_between: float = 0.1,
        progress_callback: callable = None
    ) -> List[SendResult]:
        """
        Send template with pre-built components to multiple recipients.
        
        v2 batch send that uses ComponentsBuilder output.
        Supports standard, carousel, and all future template types.
        
        Args:
            recipients: List of dicts with 'phone_number'
            template_name: Template name
            language_code: Template language
            components: Pre-built components from ComponentsBuilder
            delay_between: Seconds between messages (rate limiting)
            progress_callback: Optional callback(sent, total)
            
        Returns:
            List of SendResult objects
        """
        results = []
        total = len(recipients)
        batch_start = time.time()
        
        logger.info(f'Starting v2 batch send: {total} recipients, template={template_name}')
        
        for i, recipient in enumerate(recipients):
            phone = recipient.get('phone_number', '')
            
            result = self.send_template_with_components(
                phone=phone,
                template_name=template_name,
                language_code=language_code,
                components=components
            )
            results.append(result)
            
            # Progress callback
            if progress_callback:
                try:
                    progress_callback(i + 1, total)
                except Exception as e:
                    logger.warning(f'Progress callback error: {e}')
            
            # Rate limiting delay (skip on last message)
            if delay_between > 0 and i < total - 1:
                time.sleep(delay_between)
        
        # Log batch summary
        batch_time = (time.time() - batch_start) * 1000
        sent = sum(1 for r in results if r.success)
        failed = total - sent
        
        logger.info(
            f'v2 Batch complete: {sent}/{total} sent, {failed} failed, '
            f'time={batch_time:.0f}ms, avg={batch_time/max(total,1):.0f}ms/msg'
        )
        
        return results
    
    def send_batch(
        self,
        recipients: List[dict],
        template_name: str,
        language_code: str = 'en_US',
        header_image: str = None,
        body_params: List[str] = None,
        button_params: List[Any] = None,
        delay_between: float = 0.1,
        progress_callback: callable = None
    ) -> List[SendResult]:
        """
        Send template to multiple recipients with rate limiting.
        
        Optimized for high-volume sending with:
        - Configurable delay between messages
        - Progress tracking via callback
        - Detailed per-recipient results
        
        Args:
            recipients: List of dicts with 'phone_number' and optional 'custom_body_params'
            template_name: Template name
            language_code: Template language
            header_image: Optional header image URL
            body_params: Default body parameters
            button_params: Button parameters
            delay_between: Seconds between messages (rate limiting)
            progress_callback: Optional callback(sent, total) for progress updates
        
        Returns:
            List of SendResult objects
        """
        results = []
        total = len(recipients)
        batch_start = time.time()
        
        logger.info(f'Starting batch send: {total} recipients, template={template_name}')
        
        for i, recipient in enumerate(recipients):
            phone = recipient.get('phone_number', '')
            custom_params = recipient.get('custom_body_params') or body_params
            
            result = self.send_template(
                phone=phone,
                template_name=template_name,
                language_code=language_code,
                header_image=header_image,
                body_params=custom_params,
                button_params=button_params
            )
            results.append(result)
            
            # Progress callback
            if progress_callback:
                try:
                    progress_callback(i + 1, total)
                except Exception as e:
                    logger.warning(f'Progress callback error: {e}')
            
            # Rate limiting delay (skip on last message)
            if delay_between > 0 and i < total - 1:
                time.sleep(delay_between)
        
        # Log batch summary
        batch_time = (time.time() - batch_start) * 1000
        sent = sum(1 for r in results if r.success)
        failed = total - sent
        
        logger.info(
            f'Batch complete: {sent}/{total} sent, {failed} failed, '
            f'time={batch_time:.0f}ms, avg={batch_time/max(total,1):.0f}ms/msg'
        )
        
        return results
    
    def close(self):
        """Close the session and release connections."""
        if self.session:
            self.session.close()
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
