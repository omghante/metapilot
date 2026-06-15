"""
Meta Resumable Upload API Service.

Handles the complete media upload flow for WhatsApp template creation:
1. Start upload session with file metadata
2. Upload binary file data
3. Return media handle for use in template components

Uses the same tenant credentials and API version as the rest of the system.
"""
import os
import logging
import mimetypes
from typing import Dict, Any, Optional, Tuple
from django.conf import settings
from tenants.models import TenantConfig, ConfigProvider

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = getattr(settings, 'META_GRAPH_API_VERSION', 'v18.0')
GRAPH_API_URL = f'https://graph.facebook.com/{GRAPH_API_VERSION}'

# Maximum file sizes per Meta documentation (in bytes)
MAX_FILE_SIZES = {
    'image/jpeg': 5 * 1024 * 1024,       # 5 MB
    'image/png': 5 * 1024 * 1024,         # 5 MB
    'image/webp': 5 * 1024 * 1024,        # 5 MB
    'video/mp4': 16 * 1024 * 1024,        # 16 MB
    'video/3gpp': 16 * 1024 * 1024,       # 16 MB
}

ALLOWED_IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp'}
ALLOWED_VIDEO_TYPES = {'video/mp4', 'video/3gpp'}
ALLOWED_TYPES = ALLOWED_IMAGE_TYPES | ALLOWED_VIDEO_TYPES


class MediaUploadError(Exception):
    """Custom exception for media upload failures."""

    def __init__(self, message: str, code: str = 'UPLOAD_ERROR'):
        self.message = message
        self.code = code
        super().__init__(self.message)


class MetaMediaUploadService:
    """
    Service for uploading media to Meta via the Resumable Upload API.

    Uses tenant-specific credentials from TenantConfig:
    - access_token: System User / permanent token
    - app_id: Meta Developer App ID (stored in TenantConfig)

    Flow:
    1. validate_file() — check MIME type and size
    2. start_session() — POST to /{APP_ID}/uploads
    3. upload_binary() — POST to /{SESSION_ID} with raw data
    4. Returns media handle (h value)
    """

    def __init__(self, tenant):
        self.tenant = tenant
        self.access_token = None
        self.app_id = None
        self._load_credentials()

    def _load_credentials(self):
        """Load encrypted Meta API credentials for tenant."""
        try:
            token_config = TenantConfig.objects.filter(
                tenant=self.tenant,
                provider=ConfigProvider.META_WHATSAPP,
                key_name='access_token',
                is_active=True
            ).first()

            app_config = TenantConfig.objects.filter(
                tenant=self.tenant,
                provider=ConfigProvider.META_WHATSAPP,
                key_name='app_id',
                is_active=True
            ).first()

            if token_config:
                self.access_token = token_config.get_value()
            if app_config:
                self.app_id = app_config.get_value()

        except Exception as e:
            logger.error(f"Failed to load Meta credentials for {self.tenant.name}: {e}")

    @property
    def is_configured(self) -> bool:
        """Check if upload service is properly configured."""
        return bool(self.access_token and self.app_id)

    @staticmethod
    def validate_file(
        file_data: bytes,
        content_type: str,
        filename: str = ''
    ) -> Tuple[bool, str]:
        """
        Validate a media file before upload.

        Returns:
            (is_valid, error_message)
        """
        # Normalize content type
        content_type = content_type.lower().strip()

        # Check allowed types
        if content_type not in ALLOWED_TYPES:
            return False, f"Unsupported file type: {content_type}. Allowed: {', '.join(sorted(ALLOWED_TYPES))}"

        # Check file size
        file_size = len(file_data)
        max_size = MAX_FILE_SIZES.get(content_type, 5 * 1024 * 1024)
        if file_size > max_size:
            max_mb = max_size / (1024 * 1024)
            actual_mb = file_size / (1024 * 1024)
            return False, f"File too large: {actual_mb:.1f}MB. Maximum for {content_type}: {max_mb:.0f}MB"

        if file_size == 0:
            return False, "File is empty"

        return True, ""

    @staticmethod
    def detect_content_type(filename: str, provided_type: str = '') -> str:
        """Detect content type from filename or use provided type."""
        if provided_type and provided_type in ALLOWED_TYPES:
            return provided_type

        guessed, _ = mimetypes.guess_type(filename)
        if guessed and guessed in ALLOWED_TYPES:
            return guessed

        # Fallback by extension
        ext = os.path.splitext(filename)[1].lower()
        ext_map = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.webp': 'image/webp',
            '.mp4': 'video/mp4',
            '.3gp': 'video/3gpp',
        }
        return ext_map.get(ext, provided_type or 'application/octet-stream')

    def start_upload_session(
        self,
        file_length: int,
        file_type: str
    ) -> Dict[str, Any]:
        """
        Start a resumable upload session with Meta.

        POST https://graph.facebook.com/{API_VERSION}/{APP_ID}/uploads

        Args:
            file_length: Size of the file in bytes
            file_type: MIME type of the file

        Returns:
            Dict with 'session_id' on success, or 'error' on failure
        """
        import requests

        if not self.is_configured:
            return {
                'success': False,
                'error': 'Meta upload API not configured. Ensure app_id and access_token are set.',
                'code': 'NOT_CONFIGURED'
            }

        url = f'{GRAPH_API_URL}/{self.app_id}/uploads'

        params = {
            'file_length': file_length,
            'file_type': file_type,
        }

        headers = {
            'Authorization': f'Bearer {self.access_token}',
        }

        try:
            response = requests.post(
                url,
                params=params,
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                session_id = data.get('id', '')
                if not session_id:
                    return {
                        'success': False,
                        'error': 'No session ID returned from Meta',
                        'code': 'INVALID_RESPONSE'
                    }
                logger.info(f"Upload session started: {session_id}")
                return {
                    'success': True,
                    'session_id': session_id
                }
            else:
                error_data = self._parse_error(response)
                logger.error(f"Upload session failed ({response.status_code}): {error_data}")
                return {
                    'success': False,
                    'error': error_data.get('message', 'Failed to start upload session'),
                    'code': error_data.get('code', 'SESSION_FAILED'),
                    'status_code': response.status_code
                }

        except requests.exceptions.Timeout:
            logger.error("Timeout starting upload session")
            return {
                'success': False,
                'error': 'Request timed out while starting upload session',
                'code': 'TIMEOUT'
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error starting upload session: {e}")
            return {
                'success': False,
                'error': f'Network error: {str(e)}',
                'code': 'NETWORK_ERROR'
            }

    def upload_binary(
        self,
        session_id: str,
        file_data: bytes,
        content_type: str
    ) -> Dict[str, Any]:
        """
        Upload binary file data to an active upload session.

        POST https://graph.facebook.com/{API_VERSION}/{SESSION_ID}

        Args:
            session_id: Upload session ID from start_upload_session
            file_data: Raw binary file data
            content_type: MIME type (used for verify, not sent as content-type)

        Returns:
            Dict with 'media_handle' on success, or 'error' on failure
        """
        import requests

        if not self.access_token:
            return {
                'success': False,
                'error': 'Access token not available',
                'code': 'NOT_CONFIGURED'
            }

        url = f'{GRAPH_API_URL}/{session_id}'

        headers = {
            'Authorization': f'OAuth {self.access_token}',
            'file_offset': '0',
            'Content-Type': 'application/octet-stream',
        }

        try:
            response = requests.post(
                url,
                data=file_data,
                headers=headers,
                timeout=120  # Longer timeout for large file uploads
            )

            if response.status_code == 200:
                data = response.json()
                media_handle = data.get('h', '')
                if not media_handle:
                    return {
                        'success': False,
                        'error': 'No media handle returned from Meta',
                        'code': 'INVALID_RESPONSE'
                    }
                logger.info(f"File uploaded successfully. Handle: {media_handle[:20]}...")
                return {
                    'success': True,
                    'media_handle': media_handle
                }
            else:
                error_data = self._parse_error(response)
                logger.error(f"Binary upload failed ({response.status_code}): {error_data}")
                return {
                    'success': False,
                    'error': error_data.get('message', 'Failed to upload file'),
                    'code': error_data.get('code', 'UPLOAD_FAILED'),
                    'status_code': response.status_code
                }

        except requests.exceptions.Timeout:
            logger.error("Timeout during binary upload")
            return {
                'success': False,
                'error': 'Request timed out during file upload',
                'code': 'TIMEOUT'
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error during binary upload: {e}")
            return {
                'success': False,
                'error': f'Network error: {str(e)}',
                'code': 'NETWORK_ERROR'
            }

    def upload_media(
        self,
        file_data: bytes,
        content_type: str,
        filename: str = 'upload'
    ) -> Dict[str, Any]:
        """
        Complete media upload flow: validate → session → upload → handle.

        This is the primary method to call for uploading a single media file.

        Args:
            file_data: Raw binary file data
            content_type: MIME type
            filename: Original filename (for logging)

        Returns:
            Dict with 'media_handle' on success, or 'error' on failure
        """
        # Step 1: Validate
        is_valid, error_msg = self.validate_file(file_data, content_type, filename)
        if not is_valid:
            return {
                'success': False,
                'error': error_msg,
                'code': 'VALIDATION_FAILED'
            }

        # Step 2: Start upload session
        session_result = self.start_upload_session(
            file_length=len(file_data),
            file_type=content_type
        )
        if not session_result.get('success'):
            return session_result

        session_id = session_result['session_id']

        # Step 3: Upload binary
        upload_result = self.upload_binary(
            session_id=session_id,
            file_data=file_data,
            content_type=content_type
        )

        return upload_result

    @staticmethod
    def _parse_error(response) -> Dict[str, str]:
        """Parse error response from Meta API."""
        try:
            data = response.json()
            error = data.get('error', {})
            return {
                'message': error.get('message', response.text[:200]),
                'code': str(error.get('code', response.status_code)),
                'type': error.get('type', ''),
            }
        except Exception:
            return {
                'message': response.text[:200] if response.text else 'Unknown error',
                'code': str(response.status_code),
                'type': 'unknown'
            }
