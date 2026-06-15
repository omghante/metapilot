"""
WhatsApp Cloud API client for sending messages and downloading media.
"""
import logging
from typing import Tuple, Optional
import requests
from django.conf import settings

from tenants.models import TenantConfig, ConfigProvider

logger = logging.getLogger(__name__)

# Use centralized Graph API version from settings (same as async_whatsapp.py)
GRAPH_API_VERSION = getattr(settings, 'META_GRAPH_API_VERSION', 'v18.0')
GRAPH_API_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def _mask_phone(phone: str) -> str:
    """Mask phone number for safe logging (show last 4 digits only)."""
    if not phone or len(phone) < 4:
        return "***"
    return f"***{phone[-4:]}"


class WhatsAppClient:
    """
    Client for WhatsApp Cloud API (Meta Graph API).
    Handles message sending and media downloading.
    """
    
    def __init__(self, tenant=None, access_token: str = None, phone_number_id: str = None):
        """
        Initialize WhatsApp client.
        
        Args:
            tenant: Tenant model instance (will fetch config from TenantConfig)
            access_token: Direct access token (optional, overrides tenant config)
            phone_number_id: Direct phone number ID (optional, overrides tenant config)
        """
        self.tenant = tenant
        self._access_token = access_token
        self._phone_number_id = phone_number_id
    
    def _get_config(self, key_name: str) -> Optional[str]:
        """Get config value from TenantConfig."""
        if not self.tenant:
            return None
        
        try:
            config = TenantConfig.objects.get(
                tenant=self.tenant,
                provider=ConfigProvider.META_WHATSAPP,
                key_name=key_name,
                is_active=True
            )
            return config.get_value()
        except TenantConfig.DoesNotExist:
            return None
        except Exception as e:
            logger.error("Error getting WhatsApp config", extra={
                "key_name": key_name,
                "tenant_id": str(self.tenant.id) if self.tenant else None,
                "error": str(e)
            })
            return None
    
    @property
    def access_token(self) -> Optional[str]:
        """Get WhatsApp access token."""
        if self._access_token:
            return self._access_token
        return self._get_config('access_token')
    
    @property
    def phone_number_id(self) -> Optional[str]:
        """Get WhatsApp phone number ID."""
        if self._phone_number_id:
            return self._phone_number_id
        return self._get_config('phone_number_id')
    
    def send_message(self, to: str, text: str) -> dict:
        """
        Send a text message via WhatsApp.
        
        Args:
            to: Recipient phone number (with country code, no +)
            text: Message text content
            
        Returns:
            API response dict with 'success' key, or error dict with 'error' key
        """
        if not self.access_token:
            logger.error("WhatsApp access_token not configured", extra={
                "tenant_id": str(self.tenant.id) if self.tenant else None
            })
            return {"error": "Configuration error", "success": False}
        
        if not self.phone_number_id:
            logger.error("WhatsApp phone_number_id not configured", extra={
                "tenant_id": str(self.tenant.id) if self.tenant else None
            })
            return {"error": "Configuration error", "success": False}
        
        url = f"{GRAPH_API_URL}/{self.phone_number_id}/messages"
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text}
        }
        
        # Structured logging without sensitive data
        logger.info("Sending WhatsApp message", extra={
            "recipient_masked": _mask_phone(to),
            "tenant_id": str(self.tenant.id) if self.tenant else None,
            "api_version": GRAPH_API_VERSION
        })
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            
            # Handle JSON decode errors
            try:
                result = response.json()
            except ValueError:
                # Response not valid JSON (proxy error, HTML error page, etc.)
                logger.error("Invalid JSON response from WhatsApp API", extra={
                    "status_code": response.status_code,
                    "response_length": len(response.text) if response.text else 0
                })
                return {"error": "Invalid response from API", "success": False}
            
            logger.info("WhatsApp message sent successfully", extra={
                "recipient_masked": _mask_phone(to),
                "message_id": result.get("messages", [{}])[0].get("id") if result.get("messages") else None
            })
            result["success"] = True
            return result
                
        except requests.exceptions.HTTPError:
            # Log error metadata only - no response body to avoid PII leakage
            logger.error("WhatsApp API HTTP error", extra={
                "status_code": response.status_code,
                "tenant_id": str(self.tenant.id) if self.tenant else None,
                "response_length": len(response.text) if response.text else 0
            })
            return {"error": "Failed to send message", "success": False}
            
        except requests.Timeout:
            logger.error("WhatsApp API timeout", extra={
                "tenant_id": str(self.tenant.id) if self.tenant else None
            })
            return {"error": "Request timeout", "success": False}
            
        except requests.exceptions.RequestException as e:
            logger.error("WhatsApp API request error", extra={
                "tenant_id": str(self.tenant.id) if self.tenant else None,
                "error_type": type(e).__name__
            })
            return {"error": "Failed to send message", "success": False}
    
    def download_media(self, media_id: str) -> Tuple[Optional[bytes], str]:
        """
        Download media from WhatsApp Cloud API.
        
        Args:
            media_id: WhatsApp media ID
            
        Returns:
            Tuple of (media_bytes, mime_type) or (None, error_message)
        """
        if not self.access_token:
            return None, "Access token not configured"
        
        try:
            # First, get media URL
            url = f"{GRAPH_API_URL}/{media_id}"
            headers = {"Authorization": f"Bearer {self.access_token}"}
            
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code != 200:
                logger.error("Failed to get media URL", extra={
                    "status_code": response.status_code,
                    "media_id_prefix": media_id[:8] if media_id else None
                })
                return None, "Failed to retrieve media"
            
            try:
                media_info = response.json()
            except ValueError:
                logger.error("Invalid JSON in media URL response")
                return None, "Invalid API response"
            
            media_url = media_info.get('url')
            mime_type = media_info.get('mime_type', 'application/octet-stream')
            
            if not media_url:
                return None, "No media URL in response"
            
            # Download the actual media
            media_response = requests.get(
                media_url, 
                headers=headers, 
                timeout=60  # Larger timeout for media download
            )
            
            if media_response.status_code == 200:
                logger.info("Media downloaded successfully", extra={
                    "mime_type": mime_type,
                    "size_bytes": len(media_response.content)
                })
                return media_response.content, mime_type
            else:
                logger.error("Failed to download media content", extra={
                    "status_code": media_response.status_code
                })
                return None, "Failed to download media"
                
        except requests.Timeout:
            logger.error("Media download timeout")
            return None, "Download timeout"
        except Exception as e:
            logger.error("Media download error", extra={
                "error_type": type(e).__name__
            })
            return None, "Download failed"
