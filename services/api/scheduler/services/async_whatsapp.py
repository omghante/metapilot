"""
Async WhatsApp client using httpx for high-performance message sending.
Provides error isolation per recipient and batch processing.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

import httpx
from django.conf import settings

from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

# Meta Graph API version - configurable via settings
GRAPH_API_VERSION = getattr(settings, 'META_GRAPH_API_VERSION', 'v18.0')
GRAPH_API_URL = f'https://graph.facebook.com/{GRAPH_API_VERSION}'

# Error codes that require special handling
ERROR_CODE_TOKEN_EXPIRED = '190'
ERROR_CODE_RATE_LIMITED = '80007'


@dataclass
class SendResult:
    """Result of sending a message to a single recipient."""
    phone: str
    success: bool
    message_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class AsyncWhatsAppClient:
    """
    Async WhatsApp Cloud API client for high-performance message sending.

    Features:
    - Async HTTP using httpx
    - Rate limiting using token bucket
    - Error isolation per recipient
    - Batch processing with configurable delays
    """

    def __init__(self, phone_id: str, access_token: str, rate_limiter: RateLimiter = None):
        """
        Initialize the client.

        Args:
            phone_id: WhatsApp Phone Number ID
            access_token: Meta API access token
            rate_limiter: Optional rate limiter instance
        """
        self.phone_id = phone_id
        self.access_token = access_token
        self.url = f'{GRAPH_API_URL}/{phone_id}/messages'
        self.headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        self.rate_limiter = rate_limiter or RateLimiter()

    @classmethod
    def from_tenant(cls, tenant):
        """
        Create client from tenant credentials.

        Args:
            tenant: Tenant model instance

        Returns:
            AsyncWhatsAppClient instance or None if not configured
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

            return cls(phone_id, access_token)
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
        button_params: List[Dict] = None
    ) -> Dict[str, Any]:
        """
        Build WhatsApp template message payload.

        Args:
            phone: Recipient phone number (with country code, no +)
            template_name: Approved template name
            language_code: Template language code
            header_image: Optional header image URL
            body_params: Optional body text parameters
            button_params: Optional button parameters

        Returns:
            API payload dict
        """
        components = []

        # Header component (image)
        if header_image:
            components.append({
                'type': 'header',
                'parameters': [
                    {'type': 'image', 'image': {'link': header_image}}
                ]
            })

        # Body component (text parameters)
        if body_params:
            components.append({
                'type': 'body',
                'parameters': [
                    {'type': 'text', 'text': str(param)} for param in body_params
                ]
            })

        # Button components
        if button_params:
            for idx, btn in enumerate(button_params):
                btn_component = {
                    'type': 'button',
                    'sub_type': btn.get('sub_type', 'quick_reply'),
                    'index': str(idx),
                }
                if btn.get('text'):
                    btn_component['parameters'] = [{'type': 'text', 'text': btn['text']}]
                elif btn.get('payload'):
                    btn_component['parameters'] = [{'type': 'payload', 'payload': btn['payload']}]
                components.append(btn_component)

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

        return payload

    async def send_template(
        self,
        phone: str,
        template_name: str,
        language_code: str = 'en_US',
        header_image: str = None,
        body_params: List[str] = None,
        button_params: List[Dict] = None
    ) -> SendResult:
        """
        Send a template message to a single recipient.

        Args:
            phone: Recipient phone number
            template_name: Approved template name
            language_code: Template language code
            header_image: Optional header image URL
            body_params: Optional body text parameters
            button_params: Optional button parameters

        Returns:
            SendResult with success/failure details
        """
        # Acquire rate limit token
        if not self.rate_limiter.acquire(timeout=30.0):
            return SendResult(
                phone=phone,
                success=False,
                error_code='RATE_LIMIT',
                error_message='Rate limit timeout'
            )

        payload = self._build_template_payload(
            phone, template_name, language_code,
            header_image, body_params, button_params
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    self.url,
                    json=payload,
                    headers=self.headers
                )
                response.raise_for_status()
                data = response.json()

                message_id = None
                messages = data.get('messages', [])
                if messages:
                    message_id = messages[0].get('id')

                return SendResult(
                    phone=phone,
                    success=True,
                    message_id=message_id
                )

            except httpx.HTTPStatusError as e:
                error_data = {}
                try:
                    error_data = e.response.json()
                except Exception:
                    pass

                error_info = error_data.get('error', {})
                error_code = str(error_info.get('code', e.response.status_code))
                error_message = error_info.get('message', str(e))
                
                # Special handling for token expiry (error 190)
                if error_code == ERROR_CODE_TOKEN_EXPIRED:
                    logger.critical(
                        f'ACCESS TOKEN EXPIRED for phone_id {self.phone_id}! '
                        f'Error: {error_message}. '
                        'Please refresh the token in Meta Business Suite.'
                    )
                
                # Log rate limiting errors
                if error_code == ERROR_CODE_RATE_LIMITED:
                    logger.warning(
                        f'Rate limited by Meta API. Consider reducing send rate. '
                        f'Error: {error_message}'
                    )
                
                return SendResult(
                    phone=phone,
                    success=False,
                    error_code=error_code,
                    error_message=error_message
                )

            except httpx.TimeoutException:
                return SendResult(
                    phone=phone,
                    success=False,
                    error_code='TIMEOUT',
                    error_message='Request timeout'
                )

            except Exception as e:
                logger.exception(f'Error sending to {phone}: {e}')
                return SendResult(
                    phone=phone,
                    success=False,
                    error_code='UNKNOWN',
                    error_message=str(e)
                )

    async def send_template_with_components(
        self,
        phone: str,
        template_name: str,
        language_code: str = 'en_US',
        components: List[Dict] = None
    ) -> SendResult:
        """
        Send a template message with pre-built components.
        
        This is the NEW primary method for Universal Send v2.
        Accepts components from ComponentsBuilder (supports standard + carousel).
        
        Args:
            phone: Recipient phone number
            template_name: Approved template name
            language_code: Template language code
            components: Pre-built components from ComponentsBuilder
            
        Returns:
            SendResult with success/failure details
        """
        # Strip leading + — Meta WhatsApp API expects E.164 digits only (no +)
        phone = phone.lstrip('+')
        # Acquire rate limit token
        if not self.rate_limiter.acquire(timeout=30.0):
            return SendResult(
                phone=phone,
                success=False,
                error_code='RATE_LIMIT',
                error_message='Rate limit timeout'
            )

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

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(
                    self.url,
                    json=payload,
                    headers=self.headers
                )
                response.raise_for_status()
                data = response.json()

                message_id = None
                messages = data.get('messages', [])
                if messages:
                    message_id = messages[0].get('id')

                return SendResult(
                    phone=phone,
                    success=True,
                    message_id=message_id
                )

            except httpx.HTTPStatusError as e:
                error_data = {}
                try:
                    error_data = e.response.json()
                except Exception:
                    pass

                error_info = error_data.get('error', {})
                error_code = str(error_info.get('code', e.response.status_code))
                error_message = error_info.get('message', str(e))
                
                if error_code == ERROR_CODE_TOKEN_EXPIRED:
                    logger.critical(
                        f'ACCESS TOKEN EXPIRED for phone_id {self.phone_id}! '
                        f'Error: {error_message}. '
                        'Please refresh the token in Meta Business Suite.'
                    )
                if error_code == ERROR_CODE_RATE_LIMITED:
                    logger.warning(
                        f'Rate limited by Meta API. Consider reducing send rate. '
                        f'Error: {error_message}'
                    )
                
                return SendResult(
                    phone=phone,
                    success=False,
                    error_code=error_code,
                    error_message=error_message
                )

            except httpx.TimeoutException:
                return SendResult(
                    phone=phone,
                    success=False,
                    error_code='TIMEOUT',
                    error_message='Request timeout'
                )

            except Exception as e:
                logger.exception(f'Error sending to {phone}: {e}')
                return SendResult(
                    phone=phone,
                    success=False,
                    error_code='UNKNOWN',
                    error_message=str(e)
                )

    async def send_batch_with_components(
        self,
        recipients: List[Dict],
        template_name: str,
        language_code: str = 'en_US',
        components: List[Dict] = None,
        delay_ms: int = None
    ) -> List[SendResult]:
        """
        Send messages to multiple recipients with pre-built components.
        
        This is the v2 batch send that uses ComponentsBuilder output.
        Supports standard, carousel, and all future template types.
        
        Args:
            recipients: List of dicts with 'phone_number'
            template_name: Approved template name
            language_code: Template language code
            components: Pre-built components from ComponentsBuilder
            delay_ms: Override delay (None = use dynamic, 0 = no delay)
            
        Returns:
            List of SendResult for each recipient
        """
        results = []
        
        # Dynamic rate limiting based on batch size
        if delay_ms is None:
            batch_size = len(recipients)
            if batch_size <= 50:
                delay_ms = 0
            elif batch_size <= 200:
                delay_ms = 10
            elif batch_size <= 500:
                delay_ms = 25
            else:
                delay_ms = 50

        for recipient in recipients:
            phone = recipient.get('phone_number')

            try:
                result = await self.send_template_with_components(
                    phone=phone,
                    template_name=template_name,
                    language_code=language_code,
                    components=components
                )
                results.append(result)
            except Exception as e:
                logger.error(f'Error sending to {phone}: {e}')
                results.append(SendResult(
                    phone=phone,
                    success=False,
                    error_code='EXCEPTION',
                    error_message=str(e)
                ))

            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000)

        return results

    async def send_batch(
        self,
        recipients: List[Dict],
        template_name: str,
        language_code: str = 'en_US',
        header_image: str = None,
        body_params: List[str] = None,
        button_params: List[Dict] = None,
        delay_ms: int = None  # None = dynamic, otherwise use specified value
    ) -> List[SendResult]:
        """
        Send messages to multiple recipients with error isolation.

        Each recipient is processed independently - one failure does NOT block others.
        
        Dynamic rate limiting based on batch size:
        - ≤50 recipients: No delay (instant delivery)
        - ≤200 recipients: 10ms delay (~100 msg/sec)
        - ≤500 recipients: 25ms delay (~40 msg/sec)
        - >500 recipients: 50ms delay (~20 msg/sec)

        Args:
            recipients: List of dicts with 'phone_number' and optional 'custom_body_params'
            template_name: Approved template name
            language_code: Template language code
            header_image: Optional header image URL
            body_params: Default body text parameters
            button_params: Optional button parameters
            delay_ms: Override delay (None = use dynamic, 0 = no delay)

        Returns:
            List of SendResult for each recipient
        """
        results = []
        
        # Dynamic rate limiting based on batch size
        if delay_ms is None:
            batch_size = len(recipients)
            if batch_size <= 50:
                delay_ms = 0      # Instant for small batches
            elif batch_size <= 200:
                delay_ms = 10     # ~100 msg/sec
            elif batch_size <= 500:
                delay_ms = 25     # ~40 msg/sec
            else:
                delay_ms = 50     # ~20 msg/sec for large batches

        for recipient in recipients:
            phone = recipient.get('phone_number')
            # Use custom params if provided, otherwise use defaults
            params = recipient.get('custom_body_params') or body_params

            try:
                result = await self.send_template(
                    phone=phone,
                    template_name=template_name,
                    language_code=language_code,
                    header_image=header_image,
                    body_params=params,
                    button_params=button_params
                )
                results.append(result)
            except Exception as e:
                # Error isolation - log and continue to next recipient
                logger.error(f'Error sending to {phone}: {e}')
                results.append(SendResult(
                    phone=phone,
                    success=False,
                    error_code='EXCEPTION',
                    error_message=str(e)
                ))

            # Rate limiting delay between messages
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000)

        return results


def run_async(coro):
    """
    Run async coroutine in sync context.

    For Celery workers with gevent/eventlet pools, asyncio.run() fails because
    gevent patches the event loop. In this case, we fall back to synchronous
    execution using httpx.Client instead of AsyncClient.
    """
    import asyncio
    
    try:
        # Try to get the running loop
        try:
            loop = asyncio.get_running_loop()
            # If we get here, there's a running loop (gevent/eventlet)
            # We can't use asyncio.run(), so we need to handle this differently
            # For gevent, we'll use nest_asyncio if available, otherwise fail gracefully
            try:
                import nest_asyncio
                nest_asyncio.apply()
                return asyncio.run(coro)
            except ImportError:
                # nest_asyncio not available - log warning and raise
                import logging
                logging.getLogger(__name__).warning(
                    "Running in async context without nest_asyncio. "
                    "Install nest_asyncio or use prefork pool for Celery."
                )
                # Try to schedule it on the existing loop
                import concurrent.futures
                future = asyncio.ensure_future(coro, loop=loop)
                # Wait for it synchronously - this may not work with all async loops
                while not future.done():
                    import time
                    time.sleep(0.01)
                return future.result()
        except RuntimeError:
            # No running loop, we can use asyncio.run()
            pass
        
        # No running loop - safe to use asyncio.run()
        return asyncio.run(coro)
        
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"run_async failed: {e}")
        raise

