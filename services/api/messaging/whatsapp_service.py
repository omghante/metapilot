"""
WhatsApp Business API Service.
Sends messages using Meta's WhatsApp Cloud API.
Ported from Node.js implementation.
"""
import requests
import logging
from typing import List, Dict, Optional, Any
from tenants.models import TenantConfig, ConfigProvider
from messaging.models import Message, MessageStatus, MessageType

logger = logging.getLogger(__name__)

# Meta Graph API version
GRAPH_API_VERSION = 'v18.0'
GRAPH_API_URL = f'https://graph.facebook.com/{GRAPH_API_VERSION}'


# ============================================
# COMPONENTS BUILDER SYSTEM
# ============================================

class ComponentsBuilder:
    """
    Universal components builder for Meta WhatsApp Cloud API.
    
    Converts any template type (standard, carousel, product, auth, etc.)
    into a Meta-compliant components array.
    
    This is the core architecture that replaces flat parameter passing.
    All template types ultimately produce: components = [...]
    
    Usage:
        # Standard template
        builder = ComponentsBuilder()
        builder.add_header({'type': 'image', 'url': 'https://...'})
        builder.add_body_params(['John', '20% OFF'])
        builder.add_button_params([{'sub_type': 'quick_reply', 'text': 'Yes'}])
        components = builder.build()
        
        # Carousel template
        builder = ComponentsBuilder()
        builder.add_body_params(['Welcome'])  # Top-level body
        cards = [
            {
                'header': {'type': 'image', 'url': 'https://...'},
                'bodyParams': ['Card 1 text'],
                'buttonParams': [{'sub_type': 'quick_reply', 'text': 'Buy'}]
            },
            ...
        ]
        builder.add_carousel_cards(cards)
        components = builder.build()
    """
    
    def __init__(self):
        self._components = []
        self._carousel_cards = []
    
    # --- Header ---
    
    @staticmethod
    def _build_header_component(header_data: Dict) -> Optional[Dict]:
        """
        Build a header component from header data.
        
        Supports: image, video, document, text, product.
        
        Args:
            header_data: Dict with 'type' and type-specific fields
            
        Returns:
            Header component dict or None
        """
        if not header_data:
            return None
        
        header_type = header_data.get('type', '')
        
        if header_type == 'image':
            url = header_data.get('url', '')
            if url:
                return {
                    'type': 'header',
                    'parameters': [{'type': 'image', 'image': {'link': url}}]
                }
        
        elif header_type == 'video':
            url = header_data.get('url', '')
            if url:
                return {
                    'type': 'header',
                    'parameters': [{'type': 'video', 'video': {'link': url}}]
                }
        
        elif header_type == 'document':
            url = header_data.get('url', '')
            filename = header_data.get('filename', 'document')
            if url:
                return {
                    'type': 'header',
                    'parameters': [{'type': 'document', 'document': {'link': url, 'filename': filename}}]
                }
        
        elif header_type == 'text':
            text = header_data.get('text', '')
            if text:
                return {
                    'type': 'header',
                    'parameters': [{'type': 'text', 'text': text}]
                }
        
        elif header_type == 'product':
            # Product headers don't use parameters in the same way
            # They use catalog_id and product_retailer_id at template level
            return None  # Handled differently by Meta
        
        return None
    
    # --- Body ---
    
    @staticmethod
    def _build_body_component(body_params: List[str]) -> Optional[Dict]:
        """Build body component from text parameters."""
        if not body_params:
            return None
        return {
            'type': 'body',
            'parameters': [{'type': 'text', 'text': str(p)} for p in body_params]
        }
    
    # --- Buttons ---
    
    @staticmethod
    def _build_button_components(button_params: List[Dict]) -> List[Dict]:
        """
        Build button components with proper index mapping.
        
        Meta requires:
        - type: 'button'
        - sub_type: 'quick_reply' | 'url' | 'copy_code'
        - index: string index ('0', '1', '2')
        - parameters: [{type, text/payload}]
        """
        components = []
        if not button_params:
            return components
        
        for idx, btn in enumerate(button_params):
            btn_index = str(btn.get('index', idx))
            btn_component = {
                'type': 'button',
                'sub_type': btn.get('sub_type', 'quick_reply'),
                'index': btn_index,
            }
            
            # Build parameter based on sub_type
            sub_type = btn.get('sub_type', 'quick_reply')
            if sub_type == 'url' and btn.get('text'):
                btn_component['parameters'] = [{'type': 'text', 'text': btn['text']}]
            elif sub_type == 'copy_code' and btn.get('text'):
                btn_component['parameters'] = [{'type': 'coupon_code', 'coupon_code': btn['text']}]
            elif btn.get('text'):
                btn_component['parameters'] = [{'type': 'payload', 'payload': btn['text']}]
            elif btn.get('payload'):
                btn_component['parameters'] = [{'type': 'payload', 'payload': btn['payload']}]
            
            components.append(btn_component)
        
        return components
    
    # --- Builder Methods ---
    
    def add_header(self, header_data: Optional[Dict]) -> 'ComponentsBuilder':
        """Add header component."""
        component = self._build_header_component(header_data)
        if component:
            self._components.append(component)
        return self
    
    def add_body_params(self, body_params: Optional[List[str]]) -> 'ComponentsBuilder':
        """Add body component."""
        component = self._build_body_component(body_params)
        if component:
            self._components.append(component)
        return self
    
    def add_button_params(self, button_params: Optional[List[Dict]]) -> 'ComponentsBuilder':
        """Add button components."""
        self._components.extend(self._build_button_components(button_params or []))
        return self
    
    def add_carousel_cards(self, cards: List[Dict]) -> 'ComponentsBuilder':
        """
        Add carousel cards.
        
        Each card dict should have:
        - header: {type, url, ...}
        - bodyParams: [str, ...]
        - buttonParams: [{sub_type, text, index}, ...]
        
        Builds the Meta CAROUSEL component structure:
        {
            "type": "CAROUSEL",
            "cards": [
                {
                    "card_index": 0,
                    "components": [
                        {"type": "header", ...},
                        {"type": "body", ...},
                        {"type": "button", ...}
                    ]
                }
            ]
        }
        """
        meta_cards = []
        for idx, card in enumerate(cards):
            card_components = []
            
            # Card header
            header_component = self._build_header_component(card.get('header'))
            if header_component:
                card_components.append(header_component)
            
            # Card body
            body_component = self._build_body_component(card.get('bodyParams', []))
            if body_component:
                card_components.append(body_component)
            
            # Card buttons
            card_components.extend(
                self._build_button_components(card.get('buttonParams', []))
            )
            
            meta_cards.append({
                'card_index': idx,
                'components': card_components
            })
        
        self._carousel_cards = meta_cards
        return self
    
    def build(self) -> List[Dict]:
        """
        Build final components array.
        
        For standard: returns [header, body, button, ...]
        For carousel: returns [body, ..., {type: CAROUSEL, cards: [...]}]
        """
        result = list(self._components)
        
        if self._carousel_cards:
            result.append({
                'type': 'CAROUSEL',
                'cards': self._carousel_cards
            })
        
        return result
    
    # --- Convenience factory methods ---
    
    @classmethod
    def for_standard(
        cls,
        header: Optional[Dict] = None,
        body_params: Optional[List[str]] = None,
        button_params: Optional[List[Dict]] = None
    ) -> List[Dict]:
        """Build components for a standard template."""
        builder = cls()
        builder.add_header(header)
        builder.add_body_params(body_params)
        builder.add_button_params(button_params)
        return builder.build()
    
    @classmethod
    def for_carousel(
        cls,
        cards: List[Dict],
        body_params: Optional[List[str]] = None,
        button_params: Optional[List[Dict]] = None
    ) -> List[Dict]:
        """
        Build components for a carousel template.
        
        Args:
            cards: List of card dicts with header, bodyParams, buttonParams
            body_params: Optional top-level body params
            button_params: Optional top-level button params (rarely used)
        """
        builder = cls()
        builder.add_body_params(body_params)
        builder.add_button_params(button_params)
        builder.add_carousel_cards(cards)
        return builder.build()
    
    @classmethod
    def for_template_type(
        cls,
        template_type: str,
        header: Optional[Dict] = None,
        body_params: Optional[List[str]] = None,
        button_params: Optional[List[Dict]] = None,
        cards: Optional[List[Dict]] = None
    ) -> List[Dict]:
        """
        Universal factory: build components based on template_type.
        
        Args:
            template_type: 'standard' or 'carousel'
            header: Header data (standard only, carousel uses per-card headers)
            body_params: Body text parameters
            button_params: Button parameters
            cards: Carousel cards (carousel only)
        """
        if template_type == 'carousel':
            return cls.for_carousel(
                cards=cards or [],
                body_params=body_params,
                button_params=button_params
            )
        else:
            return cls.for_standard(
                header=header,
                body_params=body_params,
                button_params=button_params
            )


class WhatsAppService:
    """
    WhatsApp Business API client.
    Sends messages using tenant-specific credentials.
    """
    
    def __init__(self, tenant):
        """
        Initialize WhatsApp service with tenant credentials.
        
        Args:
            tenant: Tenant model instance
        """
        self.tenant = tenant
        self.phone_number_id = None
        self.access_token = None
        self._load_credentials()
    
    def _load_credentials(self):
        """Load encrypted WhatsApp credentials for tenant."""
        try:
            # Get phone_number_id
            phone_config = TenantConfig.objects.filter(
                tenant=self.tenant,
                provider=ConfigProvider.META_WHATSAPP,
                key_name='phone_number_id',
                is_active=True
            ).first()
            
            # Get access_token
            token_config = TenantConfig.objects.filter(
                tenant=self.tenant,
                provider=ConfigProvider.META_WHATSAPP,
                key_name='access_token',
                is_active=True
            ).first()
            
            if phone_config:
                self.phone_number_id = phone_config.get_value()
            if token_config:
                self.access_token = token_config.get_value()
                
        except Exception as e:
            logger.error(f"Failed to load WhatsApp credentials for {self.tenant.name}: {e}")
    
    @property
    def is_configured(self) -> bool:
        """Check if WhatsApp is properly configured for this tenant."""
        return bool(self.phone_number_id and self.access_token)
    
    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with authorization."""
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
    
    def _get_messages_url(self) -> str:
        """Get the messages endpoint URL."""
        return f'{GRAPH_API_URL}/{self.phone_number_id}/messages'
    
    def send_text_message(self, to: str, text: str) -> Dict[str, Any]:
        """
        Send a text message.
        
        Args:
            to: Recipient phone number (with country code, no +)
            text: Message text
            
        Returns:
            API response dict with message_id
        """
        if not self.is_configured:
            raise ValueError("WhatsApp not configured for this tenant")
        
        payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': to,
            'type': 'text',
            'text': {'body': text}
        }
        
        response = requests.post(
            self._get_messages_url(),
            json=payload,
            headers=self._get_headers()
        )
        
        if response.status_code == 200:
            data = response.json()
            return {
                'success': True,
                'message_id': data.get('messages', [{}])[0].get('id'),
                'response': data
            }
        else:
            return {
                'success': False,
                'error_code': str(response.status_code),
                'error_message': response.text
            }
    
    def send_template_message(
        self,
        to: str,
        template_name: str,
        language_code: str = 'en_US',
        header_image: Optional[str] = None,
        body_params: Optional[List[str]] = None,
        button_params: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        Send a template message.
        
        Args:
            to: Recipient phone number
            template_name: Approved template name
            language_code: Template language code
            header_image: URL for header image (if template has image header)
            body_params: List of text values for body placeholders {{1}}, {{2}}, etc.
            button_params: List of button parameters
            
        Returns:
            API response dict
        """
        if not self.is_configured:
            raise ValueError("WhatsApp not configured for this tenant")
        
        components = []
        
        # Header component with image
        if header_image:
            components.append({
                'type': 'header',
                'parameters': [{'type': 'image', 'image': {'link': header_image}}]
            })
        
        # Body component with text parameters
        if body_params:
            components.append({
                'type': 'body',
                'parameters': [{'type': 'text', 'text': param} for param in body_params]
            })
        
        # Button components
        if button_params:
            for index, button in enumerate(button_params):
                components.append({
                    'type': 'button',
                    'sub_type': button.get('sub_type', 'quick_reply'),
                    'index': str(index),
                    'parameters': [{'type': 'text', 'text': button['text']}] if button.get('text') else []
                })
        
        payload = {
            'messaging_product': 'whatsapp',
            'to': to,
            'type': 'template',
            'template': {
                'name': template_name,
                'language': {'code': language_code},
                'components': components
            }
        }
        
        response = requests.post(
            self._get_messages_url(),
            json=payload,
            headers=self._get_headers()
        )
        
        if response.status_code == 200:
            data = response.json()
            return {
                'success': True,
                'message_id': data.get('messages', [{}])[0].get('id'),
                'response': data
            }
        else:
            return {
                'success': False,
                'error_code': str(response.status_code),
                'error_message': response.text
            }
    
    def send_template_with_components(
        self,
        to: str,
        template_name: str,
        language_code: str = 'en_US',
        components: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        Send a template message with pre-built components.
        
        This is the NEW primary method for Universal Send v2.
        Accepts components from ComponentsBuilder (supports standard + carousel).
        
        Args:
            to: Recipient phone number
            template_name: Approved template name
            language_code: Template language code
            components: Pre-built components from ComponentsBuilder
            
        Returns:
            API response dict
        """
        if not self.is_configured:
            raise ValueError("WhatsApp not configured for this tenant")
        
        payload = {
            'messaging_product': 'whatsapp',
            'to': to,
            'type': 'template',
            'template': {
                'name': template_name,
                'language': {'code': language_code}
            }
        }
        
        if components:
            payload['template']['components'] = components
        
        response = requests.post(
            self._get_messages_url(),
            json=payload,
            headers=self._get_headers()
        )
        
        if response.status_code == 200:
            data = response.json()
            return {
                'success': True,
                'message_id': data.get('messages', [{}])[0].get('id'),
                'response': data
            }
        else:
            return {
                'success': False,
                'error_code': str(response.status_code),
                'error_message': response.text
            }
    
    def send_image_message(self, to: str, image_url: str, caption: Optional[str] = None) -> Dict[str, Any]:
        """
        Send an image message.
        
        Args:
            to: Recipient phone number
            image_url: URL of the image
            caption: Optional caption text
        """
        if not self.is_configured:
            raise ValueError("WhatsApp not configured for this tenant")
        
        payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': to,
            'type': 'image',
            'image': {
                'link': image_url
            }
        }
        
        if caption:
            payload['image']['caption'] = caption
        
        response = requests.post(
            self._get_messages_url(),
            json=payload,
            headers=self._get_headers()
        )
        
        if response.status_code == 200:
            data = response.json()
            return {
                'success': True,
                'message_id': data.get('messages', [{}])[0].get('id'),
                'response': data
            }
        else:
            return {
                'success': False,
                'error_code': str(response.status_code),
                'error_message': response.text
            }
    
    def send_document_message(self, to: str, document_url: str, filename: str, caption: Optional[str] = None) -> Dict[str, Any]:
        """
        Send a document message.
        """
        if not self.is_configured:
            raise ValueError("WhatsApp not configured for this tenant")
        
        payload = {
            'messaging_product': 'whatsapp',
            'recipient_type': 'individual',
            'to': to,
            'type': 'document',
            'document': {
                'link': document_url,
                'filename': filename
            }
        }
        
        if caption:
            payload['document']['caption'] = caption
        
        response = requests.post(
            self._get_messages_url(),
            json=payload,
            headers=self._get_headers()
        )
        
        if response.status_code == 200:
            data = response.json()
            return {
                'success': True,
                'message_id': data.get('messages', [{}])[0].get('id'),
                'response': data
            }
        else:
            return {
                'success': False,
                'error_code': str(response.status_code),
                'error_message': response.text
            }


def send_message(message: Message) -> bool:
    """
    Send a message using WhatsApp API.
    Updates message status based on result.
    
    Args:
        message: Message model instance
        
    Returns:
        True if successful, False otherwise
    """
    from django.utils import timezone
    
    tenant = message.tenant
    contact = message.conversation.contact
    
    # Initialize WhatsApp service
    wa_service = WhatsAppService(tenant)
    
    if not wa_service.is_configured:
        message.status = MessageStatus.FAILED
        message.error_code = 'NOT_CONFIGURED'
        message.error_message = 'WhatsApp API not configured for this client'
        message.save()
        logger.error(f"WhatsApp not configured for tenant {tenant.name}")
        return False
    
    try:
        result = None
        
        # Send based on message type
        if message.message_type == MessageType.TEXT:
            result = wa_service.send_text_message(
                to=contact.phone,
                text=message.content
            )
        elif message.message_type == MessageType.TEMPLATE:
            payload = message.payload or {}
            result = wa_service.send_template_message(
                to=contact.phone,
                template_name=payload.get('template_name', ''),
                body_params=payload.get('template_params', []),
                header_image=payload.get('header_image'),
                button_params=payload.get('button_params')
            )
        elif message.message_type == MessageType.IMAGE:
            result = wa_service.send_image_message(
                to=contact.phone,
                image_url=message.media_url,
                caption=message.content
            )
        elif message.message_type == MessageType.DOCUMENT:
            result = wa_service.send_document_message(
                to=contact.phone,
                document_url=message.media_url,
                filename=message.payload.get('filename', 'document'),
                caption=message.content
            )
        else:
            # Default to text
            result = wa_service.send_text_message(
                to=contact.phone,
                text=message.content
            )
        
        # Update message based on result
        if result and result.get('success'):
            message.wa_message_id = result.get('message_id', '')
            message.status = MessageStatus.SENT
            message.sent_at = timezone.now()
            message.save()
            logger.info(f"Message sent successfully: {message.wa_message_id}")
            return True
        else:
            message.status = MessageStatus.FAILED
            message.error_code = result.get('error_code', 'UNKNOWN')
            message.error_message = result.get('error_message', 'Unknown error')[:500]
            message.save()
            logger.error(f"Message send failed: {result}")
            return False
            
    except Exception as e:
        message.status = MessageStatus.FAILED
        message.error_code = 'EXCEPTION'
        message.error_message = str(e)[:500]
        message.save()
        logger.exception(f"Exception sending message: {e}")
        return False


def send_messages_batch(messages: List[Message], batch_size: int = 5, delay_seconds: float = 1.0) -> Dict[str, int]:
    """
    Send messages in batches to avoid rate limits.
    
    Args:
        messages: List of Message model instances
        batch_size: Number of messages per batch
        delay_seconds: Delay between batches
        
    Returns:
        Dict with success/failed counts
    """
    import time
    
    results = {'success': 0, 'failed': 0}
    
    for i in range(0, len(messages), batch_size):
        batch = messages[i:i + batch_size]
        
        for message in batch:
            if send_message(message):
                results['success'] += 1
            else:
                results['failed'] += 1
        
        # Delay between batches
        if i + batch_size < len(messages):
            time.sleep(delay_seconds)
    
    return results
