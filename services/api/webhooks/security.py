"""
Webhook security utilities for Meta WhatsApp API.

Provides signature verification for incoming webhooks to prevent spoofing attacks.
"""
import hmac
import hashlib
import logging

logger = logging.getLogger(__name__)


def verify_webhook_signature(request, app_secret: str) -> bool:
    """
    Verify Meta's X-Hub-Signature-256 header.
    
    Meta signs every webhook POST with HMAC-SHA256 using the app secret.
    This function verifies that signature to prevent spoofed requests.
    
    Args:
        request: Django HttpRequest object
        app_secret: Meta App Secret for this WhatsApp Business Account
    
    Returns:
        True if signature is valid, False otherwise
    """
    if not app_secret:
        logger.warning("App secret not configured - skipping signature verification")
        return True  # Allow if not configured (backward compatibility)
    
    # Get signature header
    signature_header = request.headers.get('X-Hub-Signature-256', '')
    
    if not signature_header:
        logger.warning("Missing X-Hub-Signature-256 header")
        return False
    
    if not signature_header.startswith('sha256='):
        logger.warning("Invalid signature format - missing sha256= prefix")
        return False
    
    # Extract signature
    expected_signature = signature_header[7:]  # Remove 'sha256=' prefix
    
    # Calculate expected signature
    body = request.body
    calculated_signature = hmac.new(
        app_secret.encode('utf-8'),
        body,
        hashlib.sha256
    ).hexdigest()
    
    # Constant-time comparison to prevent timing attacks
    is_valid = hmac.compare_digest(expected_signature, calculated_signature)
    
    if not is_valid:
        logger.warning("Webhook signature verification failed")
    
    return is_valid


def get_app_secret_for_tenant(tenant) -> str | None:
    """
    Get the app secret for a tenant from TenantConfig.
    
    Args:
        tenant: Tenant model instance
    
    Returns:
        App secret string or None if not configured
    """
    from tenants.models import TenantConfig, ConfigProvider
    
    return TenantConfig.get_config(
        tenant, ConfigProvider.META_WHATSAPP, 'app_secret'
    )
