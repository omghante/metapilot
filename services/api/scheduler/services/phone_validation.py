"""
Phone number validation utilities using phonenumbers library.

Validates and normalizes phone numbers for WhatsApp messaging.
Uses Google's libphonenumber for robust international phone validation.
"""
import logging
from typing import Optional

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat

logger = logging.getLogger(__name__)


def validate_phone_number(phone: str, default_region: str = None) -> tuple[bool, str, Optional[str]]:
    """
    Validate and normalize a phone number for WhatsApp.
    
    Uses the phonenumbers library for robust validation.
    WhatsApp requires E.164 format without the + sign.
    
    Args:
        phone: Phone number string (any format)
        default_region: Optional default region code (e.g., 'IN', 'US')
                       Used when phone doesn't have country code
    
    Returns:
        Tuple of (is_valid, normalized_phone, error_message)
        - is_valid: True if phone is valid
        - normalized_phone: E.164 format without + (e.g., "919011156314")
        - error_message: None if valid, error description if invalid
    """
    if not phone:
        return False, '', 'Phone number is required'
    
    # Clean the input
    phone_str = str(phone).strip()
    
    def try_parse(phone_input: str, region: str = None):
        """Try to parse and validate a phone number."""
        try:
            if phone_input.startswith('+'):
                parsed_number = phonenumbers.parse(phone_input, None)
            else:
                parsed_number = phonenumbers.parse(phone_input, region)
            
            if phonenumbers.is_valid_number(parsed_number):
                e164_format = phonenumbers.format_number(
                    parsed_number, 
                    PhoneNumberFormat.E164
                )
                normalized = e164_format[1:] if e164_format.startswith('+') else e164_format
                return True, normalized, None
            return False, '', 'Invalid phone number'
        except NumberParseException:
            return False, '', None
        except Exception as e:
            return False, '', str(e)
    
    try:
        # Try 1: Parse as-is with region hint
        is_valid, normalized, error = try_parse(phone_str, default_region)
        if is_valid:
            return True, normalized, None
        
        # Try 2: If it's all digits and looks like it has a country code (10+ digits),
        # try adding + prefix to parse as international number
        if phone_str.isdigit() and len(phone_str) >= 10:
            is_valid, normalized, error = try_parse('+' + phone_str, None)
            if is_valid:
                return True, normalized, None
        
        # Try 3: For numbers starting with common country codes, try with + prefix
        common_prefixes = ['1', '7', '20', '27', '30', '31', '32', '33', '34', '36', 
                          '39', '40', '41', '43', '44', '45', '46', '47', '48', '49',
                          '51', '52', '53', '54', '55', '56', '57', '58', '60', '61',
                          '62', '63', '64', '65', '66', '81', '82', '84', '86', '90',
                          '91', '92', '93', '94', '95', '98', '212', '213', '216', '218',
                          '220', '221', '233', '234', '254', '255', '256', '263']
        for prefix in common_prefixes:
            if phone_str.startswith(prefix):
                is_valid, normalized, error = try_parse('+' + phone_str, None)
                if is_valid:
                    return True, normalized, None
                break
        
        return False, '', error or 'Invalid phone number'
        
    except NumberParseException as e:
        error_msg = str(e)
        if 'not a number' in error_msg.lower():
            return False, '', 'Phone number contains invalid characters'
        elif 'too short' in error_msg.lower():
            return False, '', 'Phone number is too short'
        elif 'too long' in error_msg.lower():
            return False, '', 'Phone number is too long'
        else:
            return False, '', f'Invalid phone number: {error_msg}'
    except Exception as e:
        logger.exception(f'Unexpected error validating phone: {e}')
        return False, '', f'Validation error: {str(e)}'


def normalize_phone_number(phone: str, default_region: str = None) -> str:
    """
    Normalize a phone number to E.164 format without +.
    
    Args:
        phone: Phone number to normalize
        default_region: Optional default region code
    
    Returns:
        Normalized phone number (digits only, no +)
    
    Raises:
        ValueError: If phone number is invalid
    """
    is_valid, normalized, error = validate_phone_number(phone, default_region)
    if not is_valid:
        raise ValueError(error)
    return normalized


def validate_recipients(recipients: list[dict], default_region: str = None) -> tuple[list[dict], list[dict]]:
    """
    Validate a list of recipients and separate valid/invalid.
    
    Args:
        recipients: List of dicts with 'phone_number' key
        default_region: Optional default region code for numbers without country code
    
    Returns:
        Tuple of (valid_recipients, invalid_recipients)
        - Each invalid recipient has an 'error' key added
    """
    valid = []
    invalid = []
    seen_phones = set()  # Track normalized numbers to deduplicate
    duplicates_skipped = 0
    
    for recipient in recipients:
        phone = recipient.get('phone_number', '')
        is_valid, normalized, error = validate_phone_number(phone, default_region)
        
        if is_valid:
            # Deduplicate by normalized phone number
            if normalized in seen_phones:
                duplicates_skipped += 1
                continue
            seen_phones.add(normalized)
            # Create new dict with normalized phone
            valid_recipient = recipient.copy()
            valid_recipient['phone_number'] = normalized
            valid.append(valid_recipient)
        else:
            invalid_recipient = recipient.copy()
            invalid_recipient['error'] = error
            invalid.append(invalid_recipient)
    
    if duplicates_skipped:
        logger.info(f'Deduplicated {duplicates_skipped} recipients with the same phone number')
    if invalid:
        logger.warning(f'Filtered {len(invalid)} invalid phone numbers')
    
    return valid, invalid
