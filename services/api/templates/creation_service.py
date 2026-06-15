"""
Template Creation Service.

Orchestrates the complete WhatsApp template creation flow:
1. Validate template structure
2. Upload media files (if any) via Resumable Upload API
3. Construct Meta API template payload
4. Submit to Meta Graph API for approval
5. Cache the newly created template

Supports: text-only, image/video header, and carousel templates.
"""
import re
import logging
from typing import Dict, Any, List, Optional

import requests
from django.conf import settings

from templates.upload_service import MetaMediaUploadService
from templates.meta_service import MetaTemplateService, GRAPH_API_URL
from tenants.models import TenantConfig, ConfigProvider

logger = logging.getLogger(__name__)


class TemplateCreationError(Exception):
    """Custom exception for template creation failures."""

    def __init__(self, message: str, code: str = 'CREATION_ERROR', details: Any = None):
        self.message = message
        self.code = code
        self.details = details
        super().__init__(self.message)


class TemplateCreationService:
    """
    Service to create WhatsApp message templates via Meta Graph API.

    Uses tenant-specific credentials from TenantConfig:
    - access_token: System User / permanent token
    - business_account_id: WABA ID
    - app_id: Meta Developer App ID (for media uploads)

    The service handles:
    - Template name validation (lowercase, underscores only)
    - Language validation
    - Category validation (UTILITY, MARKETING, AUTHENTICATION)
    - Media upload flow (image/video headers, carousel cards)
    - Component construction
    - Meta API submission
    - Status tracking
    """

    VALID_CATEGORIES = {'UTILITY', 'MARKETING', 'AUTHENTICATION'}
    VALID_LANGUAGES = {
        'en_US', 'en', 'en_GB', 'hi', 'es', 'pt_BR', 'ar', 'fr', 'de',
        'it', 'ja', 'ko', 'zh_CN', 'zh_TW', 'ru', 'tr', 'nl', 'id',
        'mr', 'bn', 'ta', 'te', 'gu', 'kn', 'ml', 'pa', 'ur',
    }
    NAME_PATTERN = re.compile(r'^[a-z][a-z0-9_]{0,511}$')

    def __init__(self, tenant):
        self.tenant = tenant
        self.meta_service = MetaTemplateService(tenant)
        self.upload_service = MetaMediaUploadService(tenant)

    @property
    def is_configured(self) -> bool:
        """Check if all required services are configured."""
        return self.meta_service.is_configured

    # ========================================
    # VALIDATION
    # ========================================

    def validate_template_name(self, name: str) -> Dict[str, Any]:
        """
        Validate template name per Meta rules:
        - Lowercase letters, numbers, and underscores only
        - Must start with a letter
        - Max 512 characters
        """
        if not name:
            return {'valid': False, 'error': 'Template name is required'}

        if not self.NAME_PATTERN.match(name):
            return {
                'valid': False,
                'error': 'Template name must contain only lowercase letters, numbers, and underscores, and start with a letter'
            }

        return {'valid': True}

    def validate_language(self, language: str) -> Dict[str, Any]:
        """Validate language code."""
        if not language:
            return {'valid': False, 'error': 'Language code is required'}

        # Meta accepts many language codes, be lenient but check format
        if not re.match(r'^[a-z]{2}(_[A-Z]{2})?$', language):
            return {
                'valid': False,
                'error': f'Invalid language code format: {language}. Expected format: en_US, hi, etc.'
            }

        return {'valid': True}

    def validate_category(self, category: str) -> Dict[str, Any]:
        """Validate template category."""
        if not category:
            return {'valid': False, 'error': 'Category is required'}

        category_upper = category.upper()
        if category_upper not in self.VALID_CATEGORIES:
            return {
                'valid': False,
                'error': f'Invalid category: {category}. Must be one of: {", ".join(sorted(self.VALID_CATEGORIES))}'
            }

        return {'valid': True, 'normalized': category_upper}

    def validate_template_request(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate the complete template creation request.

        Returns:
            Dict with 'valid' bool and 'errors' list
        """
        errors = []

        # Name
        name_result = self.validate_template_name(data.get('name', ''))
        if not name_result.get('valid'):
            errors.append({'field': 'name', 'error': name_result['error']})

        # Language
        lang_result = self.validate_language(data.get('language', ''))
        if not lang_result.get('valid'):
            errors.append({'field': 'language', 'error': lang_result['error']})

        # Category
        cat_result = self.validate_category(data.get('category', ''))
        if not cat_result.get('valid'):
            errors.append({'field': 'category', 'error': cat_result['error']})

        # Components
        components = data.get('components', [])
        if not components:
            errors.append({'field': 'components', 'error': 'At least one component is required'})

        # Validate BODY component exists (required by Meta)
        has_body = any(
            c.get('type', '').upper() == 'BODY' for c in components
            if isinstance(c, dict)
        )
        # Body is required for non-carousel, optional for carousel
        is_carousel = any(
            c.get('type', '').upper() == 'CAROUSEL' for c in components
            if isinstance(c, dict)
        )
        if not has_body and not is_carousel:
            errors.append({'field': 'components', 'error': 'BODY component is required'})

        return {
            'valid': len(errors) == 0,
            'errors': errors
        }

    # ========================================
    # MEDIA UPLOAD
    # ========================================

    def upload_media_for_template(
        self,
        file_data: bytes,
        content_type: str,
        filename: str = 'upload'
    ) -> Dict[str, Any]:
        """
        Upload a media file and return the media handle.

        This wraps the upload service for convenience.
        """
        if not self.upload_service.is_configured:
            return {
                'success': False,
                'error': 'Media upload not configured. Ensure app_id is set in tenant config.',
                'code': 'NOT_CONFIGURED'
            }

        return self.upload_service.upload_media(
            file_data=file_data,
            content_type=content_type,
            filename=filename
        )

    def process_media_in_components(
        self,
        components: List[Dict],
        media_files: Dict[str, Any]
    ) -> List[Dict]:
        """
        Process media files in components, uploading them and replacing
        file references with media handles.

        Args:
            components: Template components list
            media_files: Dict mapping field keys to file data
                         e.g. {'header_media': <file_bytes>, 'card_0_media': <file_bytes>}

        Returns:
            Updated components list with media handles injected
        """
        processed = []

        for component in components:
            comp = dict(component)
            comp_type = comp.get('type', '').upper()

            if comp_type == 'HEADER' and comp.get('format') in ('IMAGE', 'VIDEO'):
                # Upload header media
                media_key = 'header_media'
                if media_key in media_files:
                    file_info = media_files[media_key]
                    result = self.upload_media_for_template(
                        file_data=file_info['data'],
                        content_type=file_info['content_type'],
                        filename=file_info.get('filename', 'header')
                    )
                    if result.get('success'):
                        comp.setdefault('example', {})
                        comp['example']['header_handle'] = [result['media_handle']]
                        logger.info(f"Header media uploaded: {result['media_handle'][:20]}...")
                    else:
                        raise TemplateCreationError(
                            f"Failed to upload header media: {result.get('error')}",
                            code='HEADER_UPLOAD_FAILED'
                        )

            elif comp_type == 'CAROUSEL':
                # Process carousel cards
                cards = comp.get('cards', [])
                processed_cards = []
                for card_idx, card in enumerate(cards):
                    card = dict(card)
                    card_components = card.get('components', [])
                    processed_card_components = []

                    for card_comp in card_components:
                        card_comp = dict(card_comp)
                        if (card_comp.get('type', '').upper() == 'HEADER'
                                and card_comp.get('format') in ('IMAGE', 'VIDEO')):
                            media_key = f'card_{card_idx}_media'
                            if media_key in media_files:
                                file_info = media_files[media_key]
                                result = self.upload_media_for_template(
                                    file_data=file_info['data'],
                                    content_type=file_info['content_type'],
                                    filename=file_info.get('filename', f'card_{card_idx}')
                                )
                                if result.get('success'):
                                    card_comp.setdefault('example', {})
                                    card_comp['example']['header_handle'] = [result['media_handle']]
                                    logger.info(f"Card {card_idx} media uploaded successfully")
                                else:
                                    raise TemplateCreationError(
                                        f"Failed to upload card {card_idx} media: {result.get('error')}",
                                        code='CARD_UPLOAD_FAILED'
                                    )

                        processed_card_components.append(card_comp)

                    card['components'] = processed_card_components
                    processed_cards.append(card)

                comp['cards'] = processed_cards

            processed.append(comp)

        return processed

    # ========================================
    # TEMPLATE CREATION
    # ========================================

    def create_template(
        self,
        name: str,
        language: str,
        category: str,
        components: List[Dict],
        media_files: Optional[Dict[str, Any]] = None,
        allow_category_change: bool = True,
    ) -> Dict[str, Any]:
        """
        Create a WhatsApp message template on Meta.

        This is the main entry point for template creation.

        Args:
            name: Template name (lowercase, underscores only)
            language: Language code (e.g., en_US)
            category: UTILITY, MARKETING, or AUTHENTICATION
            components: Template components (HEADER, BODY, FOOTER, BUTTONS, CAROUSEL)
            media_files: Optional dict of media files to upload
            allow_category_change: Whether Meta can auto-change category

        Returns:
            Dict with template details on success, or error info on failure
        """
        # Validate
        validation = self.validate_template_request({
            'name': name,
            'language': language,
            'category': category,
            'components': components,
        })
        if not validation['valid']:
            return {
                'success': False,
                'error': 'Validation failed',
                'validation_errors': validation['errors'],
                'code': 'VALIDATION_FAILED'
            }

        if not self.is_configured:
            return {
                'success': False,
                'error': 'WhatsApp Business Account not configured',
                'code': 'NOT_CONFIGURED'
            }

        # Process media uploads if needed
        if media_files:
            try:
                components = self.process_media_in_components(components, media_files)
            except TemplateCreationError as e:
                return {
                    'success': False,
                    'error': e.message,
                    'code': e.code
                }

        # Build payload
        payload = {
            'name': name,
            'language': language,
            'category': category.upper(),
            'components': components,
        }

        if allow_category_change:
            payload['allow_category_change'] = True

        # Submit to Meta
        url = f'{GRAPH_API_URL}/{self.meta_service.waba_id}/message_templates'

        headers = {
            'Authorization': f'Bearer {self.meta_service.access_token}',
            'Content-Type': 'application/json',
        }

        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=30
            )

            if response.status_code in (200, 201):
                data = response.json()
                template_id = data.get('id', '')
                template_status = data.get('status', 'PENDING')
                template_category = data.get('category', category.upper())

                logger.info(
                    f"Template '{name}' created successfully: "
                    f"ID={template_id}, Status={template_status}"
                )

                return {
                    'success': True,
                    'template_id': template_id,
                    'name': name,
                    'category': template_category,
                    'status': template_status,
                    'language': language,
                }

            else:
                error_data = self._parse_error(response)
                error_msg = error_data.get('message', 'Failed to create template')
                error_code = error_data.get('code', str(response.status_code))
                error_subcode = error_data.get('error_subcode', '')

                logger.error(
                    f"Template creation failed ({response.status_code}): "
                    f"{error_msg} [code={error_code}, subcode={error_subcode}]"
                )

                # Provide human-friendly error messages for common errors
                friendly_msg = self._get_friendly_error(error_code, error_subcode, error_msg)

                return {
                    'success': False,
                    'error': friendly_msg,
                    'meta_error': error_msg,
                    'code': error_code,
                    'error_subcode': error_subcode,
                    'status_code': response.status_code,
                }

        except requests.exceptions.Timeout:
            logger.error(f"Timeout creating template '{name}'")
            return {
                'success': False,
                'error': 'Request timed out. Please try again.',
                'code': 'TIMEOUT'
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error creating template '{name}': {e}")
            return {
                'success': False,
                'error': f'Network error: {str(e)}',
                'code': 'NETWORK_ERROR'
            }

    # ========================================
    # STATUS TRACKING
    # ========================================

    def get_template_status(self, template_name: str) -> Dict[str, Any]:
        """
        Get the approval status of a template by name.

        Fetches directly from Meta Graph API.

        Args:
            template_name: Template name to check

        Returns:
            Dict with status information
        """
        if not self.is_configured:
            return {
                'success': False,
                'error': 'WhatsApp Business Account not configured'
            }

        url = f'{GRAPH_API_URL}/{self.meta_service.waba_id}/message_templates'
        params = {
            'name': template_name,
            'fields': 'id,name,status,category,language,components,quality_score,rejected_reason',
        }
        headers = {
            'Authorization': f'Bearer {self.meta_service.access_token}',
        }

        try:
            response = requests.get(url, params=params, headers=headers, timeout=15)

            if response.status_code == 200:
                data = response.json()
                templates = data.get('data', [])

                if not templates:
                    return {
                        'success': True,
                        'found': False,
                        'message': f'No template found with name: {template_name}'
                    }

                results = []
                for t in templates:
                    quality_score_data = t.get('quality_score', {})
                    quality_score = quality_score_data.get('score', '') if isinstance(quality_score_data, dict) else str(quality_score_data)

                    results.append({
                        'template_id': t.get('id', ''),
                        'name': t.get('name', ''),
                        'status': t.get('status', 'UNKNOWN'),
                        'category': t.get('category', ''),
                        'language': t.get('language', ''),
                        'quality_score': quality_score,
                        'rejected_reason': t.get('rejected_reason', ''),
                    })

                return {
                    'success': True,
                    'found': True,
                    'templates': results,
                    'count': len(results),
                }

            else:
                error_data = self._parse_error(response)
                return {
                    'success': False,
                    'error': error_data.get('message', 'Failed to fetch template status'),
                }

        except requests.exceptions.Timeout:
            return {
                'success': False,
                'error': 'Request timed out',
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching template status: {e}")
            return {
                'success': False,
                'error': f'Network error: {str(e)}',
            }

    # ========================================
    # DELETE
    # ========================================

    def delete_template(self, template_name: str) -> Dict[str, Any]:
        """
        Delete a WhatsApp message template from Meta.

        DELETE /{WABA_ID}/message_templates?name={template_name}
        """
        if not self.is_configured:
            return {'success': False, 'error': 'Not configured'}

        url = f'{GRAPH_API_URL}/{self.meta_service.waba_id}/message_templates'
        params = {'name': template_name}
        headers = {
            'Authorization': f'Bearer {self.meta_service.access_token}',
        }

        try:
            response = requests.delete(url, params=params, headers=headers, timeout=15)

            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    logger.info(f"Template '{template_name}' deleted from Meta")
                    return {'success': True}
                else:
                    return {'success': False, 'error': 'Meta returned success=false'}
            else:
                error_data = self._parse_error(response)
                return {
                    'success': False,
                    'error': error_data.get('message', 'Failed to delete template'),
                }

        except Exception as e:
            logger.error(f"Error deleting template: {e}")
            return {'success': False, 'error': str(e)}

    # ========================================
    # HELPERS
    # ========================================

    @staticmethod
    def _parse_error(response) -> Dict[str, str]:
        """Parse error response from Meta API."""
        try:
            data = response.json()
            error = data.get('error', {})
            return {
                'message': error.get('message', response.text[:300]),
                'code': str(error.get('code', response.status_code)),
                'type': error.get('type', ''),
                'error_subcode': str(error.get('error_subcode', '')),
            }
        except Exception:
            return {
                'message': response.text[:300] if response.text else 'Unknown error',
                'code': str(response.status_code),
                'type': 'unknown',
                'error_subcode': '',
            }

    @staticmethod
    def _get_friendly_error(code: str, subcode: str, original: str) -> str:
        """Return human-friendly error message for common Meta API errors."""
        friendly_errors = {
            '100': 'Invalid parameter. Check your template components structure.',
            '190': 'Invalid or expired access token. Please reconfigure your WhatsApp credentials.',
            '368': 'Rate limit reached. Please wait a few minutes before trying again.',
            '80008': 'Rate limit reached for template creation. Please wait before trying again.',
        }

        subcode_errors = {
            '2388023': 'Template name already exists. Choose a different name.',
            '2388022': 'Invalid template structure. Ensure all required components are included.',
            '2388024': 'Template content violates WhatsApp policy.',
        }

        if subcode and subcode in subcode_errors:
            return subcode_errors[subcode]
        if code in friendly_errors:
            return friendly_errors[code]

        return original
