"""
Universal WhatsApp Template Message Send API v2.

This module provides a universal API endpoint for sending WhatsApp template
messages with support for:
- Standard templates (header, body, buttons)
- Carousel templates (multiple cards, each with header/body/buttons)
- Dynamic header (image/video/document/text/product)
- Multiple recipients
- Dynamic language
- Multiple body variables
- Multiple button variables with index mapping
- Multi-tenant credentials
- Scheduling with IST → UTC conversion
- Deduplication via MD5 hash
- Async batch sending

ARCHITECTURE:
All template types flow through ComponentsBuilder which produces a unified
components[] array for the Meta WhatsApp Cloud API.

Standard: header + body + buttons → components[]
Carousel: body + CAROUSEL{cards[{header, body, buttons}]} → components[]
"""
import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pytz

from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from django.db import transaction

from scheduler.models import SchedulerJob, SchedulerJobRecipient, SchedulerJobStatus
from scheduler.services.async_whatsapp import AsyncWhatsAppClient, run_async
from messaging.whatsapp_service import WhatsAppService, ComponentsBuilder
from api.permissions import IsTenantMember

logger = logging.getLogger(__name__)

IST = pytz.timezone('Asia/Kolkata')


# ============================================
# SERIALIZERS
# ============================================

class HeaderSerializer(serializers.Serializer):
    """
    Header component for template messages.
    Supports: image, video, document, text, product.
    """
    type = serializers.ChoiceField(
        choices=['image', 'video', 'document', 'text', 'product'],
        required=True
    )
    # For image/video/document
    url = serializers.URLField(required=False, allow_blank=True)
    # For document
    filename = serializers.CharField(max_length=255, required=False, allow_blank=True)
    # For text header
    text = serializers.CharField(max_length=60, required=False, allow_blank=True)
    # For catalog/product
    catalog_id = serializers.CharField(max_length=100, required=False, allow_blank=True)
    product_retailer_id = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate(self, data):
        header_type = data.get('type')
        if header_type in ['image', 'video', 'document'] and not data.get('url'):
            raise serializers.ValidationError(
                "url is required for {} header".format(header_type)
            )
        if header_type == 'text' and not data.get('text'):
            raise serializers.ValidationError("text is required for text header")
        if header_type == 'product':
            if not data.get('catalog_id') or not data.get('product_retailer_id'):
                raise serializers.ValidationError(
                    "catalog_id and product_retailer_id are required for product header"
                )
        return data


class ButtonParamSerializer(serializers.Serializer):
    """
    Button parameter for template messages.
    Now includes index for proper Meta API button mapping.
    """
    index = serializers.IntegerField(required=False, help_text='Button index (0, 1, 2)')
    sub_type = serializers.ChoiceField(
        choices=['quick_reply', 'url', 'copy_code'],
        default='quick_reply'
    )
    text = serializers.CharField(max_length=255, required=False, allow_blank=True)


class CardSerializer(serializers.Serializer):
    """
    Single carousel card.
    Each card has its own header, body params, and button params.
    """
    header = HeaderSerializer(required=False)
    bodyParams = serializers.ListField(
        child=serializers.CharField(max_length=1024),
        required=False,
        default=list
    )
    buttonParams = ButtonParamSerializer(many=True, required=False, default=list)


class UniversalSendSerializer(serializers.Serializer):
    """
    Universal WhatsApp template message serializer v2.

    Supports both Standard and Carousel templates in a single JSON format.

    Standard request:
    {
        "phoneNumbers": ["919876543210"],
        "templateName": "welcome_offer",
        "language": "en_US",
        "templateType": "standard",
        "date": "2025-12-30",
        "time": "14:30",
        "header": {"type": "image", "url": "https://..."},
        "bodyParams": ["John", "20% OFF"],
        "buttonParams": [{"sub_type": "quick_reply", "text": "Yes", "index": 0}]
    }

    Carousel request:
    {
        "phoneNumbers": ["919876543210"],
        "templateName": "product_showcase",
        "language": "en_US",
        "templateType": "carousel",
        "date": "2025-12-30",
        "time": "14:30",
        "bodyParams": ["Welcome"],
        "cards": [
            {
                "header": {"type": "image", "url": "https://...card1.jpg"},
                "bodyParams": ["Product 1", "$99"],
                "buttonParams": [{"sub_type": "quick_reply", "text": "Buy Now"}]
            },
            {
                "header": {"type": "image", "url": "https://...card2.jpg"},
                "bodyParams": ["Product 2", "$149"],
                "buttonParams": [{"sub_type": "url", "text": "details", "index": 0}]
            }
        ]
    }
    """
    phoneNumbers = serializers.ListField(
        child=serializers.CharField(max_length=20),
        min_length=1,
        error_messages={'min_length': 'Valid phoneNumbers array required'}
    )
    templateName = serializers.CharField(max_length=255)
    language = serializers.CharField(max_length=10, default='en_US')
    date = serializers.CharField(max_length=10)  # Format: YYYY-MM-DD
    time = serializers.CharField(max_length=5)   # Format: HH:MM

    # Template type: standard or carousel
    templateType = serializers.ChoiceField(
        choices=['standard', 'carousel'],
        default='standard',
        help_text='Template type: standard or carousel'
    )

    # Standard template fields
    header = HeaderSerializer(required=False)
    bodyParams = serializers.ListField(
        child=serializers.CharField(max_length=1024),
        required=False,
        default=list
    )
    buttonParams = ButtonParamSerializer(many=True, required=False, default=list)

    # Carousel template fields
    cards = CardSerializer(many=True, required=False, default=list)

    def validate_phoneNumbers(self, value):
        """Validate phone numbers format."""
        for phone in value:
            cleaned = phone.replace('+', '').replace(' ', '').replace('-', '')
            if not cleaned.isdigit() or len(cleaned) < 10:
                raise serializers.ValidationError(
                    "Invalid phone number: {}".format(phone)
                )
        return value

    def validate_date(self, value):
        """Validate date format: YYYY-MM-DD."""
        import re
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', value):
            raise serializers.ValidationError("Date format must be YYYY-MM-DD")
        return value

    def validate_time(self, value):
        """Validate time format: HH:MM."""
        import re
        if not re.match(r'^\d{2}:\d{2}$', value):
            raise serializers.ValidationError("Time format must be HH:MM")
        return value

    def validate(self, data):
        """
        Cross-field validation based on templateType.

        Standard rules:
        - cards must be empty
        - header is optional

        Carousel rules:
        - cards required, min 2, max 10
        - top-level header not allowed (headers go inside cards)
        """
        template_type = data.get('templateType', 'standard')

        if template_type == 'standard':
            if data.get('cards'):
                raise serializers.ValidationError({
                    'cards': 'Cards must be empty for standard templates. Use templateType=carousel for card-based templates.'
                })

        elif template_type == 'carousel':
            cards = data.get('cards', [])
            if len(cards) < 2:
                raise serializers.ValidationError({
                    'cards': 'Carousel templates require at least 2 cards.'
                })
            if len(cards) > 10:
                raise serializers.ValidationError({
                    'cards': 'Carousel templates support a maximum of 10 cards.'
                })
            if data.get('header'):
                raise serializers.ValidationError({
                    'header': 'Top-level header is not allowed for carousel templates. Place headers inside each card.'
                })

        return data


# ============================================
# SERVICE
# ============================================

class UniversalSendService:
    """
    Service for sending WhatsApp template messages.
    Uses ComponentsBuilder for universal component generation.
    Uses existing WhatsAppService for actual API calls.
    Uses existing SchedulerJob for scheduling.
    """

    def __init__(self, tenant):
        self.tenant = tenant
        self.wa_service = WhatsAppService(tenant)

    @staticmethod
    def create_request_hash(
        phone_numbers: List[str],
        template_name: str,
        template_type: str,
        date_str: str,
        time_str: str,
        body_params: Optional[List[str]] = None,
        button_params: Optional[List[Dict]] = None,
        cards: Optional[List[Dict]] = None
    ) -> str:
        """
        Create MD5 hash for deduplication.
        
        Includes template_type, body/button params, and cards data
        to prevent different campaign types from colliding.
        """
        hash_parts = [
            template_name,
            template_type,
            ','.join(sorted(phone_numbers)),
            date_str,
            time_str,
        ]
        
        # Include params for more specific dedup
        if body_params:
            hash_parts.append(json.dumps(body_params, sort_keys=True))
        if button_params:
            hash_parts.append(json.dumps(button_params, sort_keys=True))
        if cards:
            hash_parts.append(json.dumps(cards, sort_keys=True))
        
        hash_source = "-".join(hash_parts)
        return hashlib.md5(hash_source.encode()).hexdigest()

    @staticmethod
    def parse_ist_to_utc(date_str: str, time_str: str) -> datetime:
        """Parse IST date/time to UTC."""
        year, month, day = map(int, date_str.split('-'))
        hour, minute = map(int, time_str.split(':'))

        # Create as IST, convert to UTC
        ist_dt = IST.localize(datetime(year, month, day, hour, minute, 0))
        return ist_dt.astimezone(pytz.UTC)

    @staticmethod
    def build_components(
        template_type: str,
        header: Optional[Dict] = None,
        body_params: Optional[List[str]] = None,
        button_params: Optional[List[Dict]] = None,
        cards: Optional[List[Dict]] = None
    ) -> List[Dict]:
        """
        Build Meta API components using ComponentsBuilder.
        
        This is the single point where all template types get converted
        into components[]. Used by both immediate and scheduled paths.
        """
        return ComponentsBuilder.for_template_type(
            template_type=template_type,
            header=header,
            body_params=body_params,
            button_params=button_params,
            cards=cards
        )

    def send_immediate(
        self,
        phone_numbers: List[str],
        template_name: str,
        language: str,
        template_type: str = 'standard',
        header: Optional[Dict] = None,
        body_params: Optional[List[str]] = None,
        button_params: Optional[List[Dict]] = None,
        cards: Optional[List[Dict]] = None
    ) -> List[Dict]:
        """
        Send messages immediately using component-based architecture.
        
        For standard: uses header + body + buttons → components
        For carousel: uses body + cards → components (with CAROUSEL structure)
        """
        # Build components once (same for all recipients)
        components = self.build_components(
            template_type=template_type,
            header=header,
            body_params=body_params,
            button_params=button_params,
            cards=cards
        )

        # Try async client first (preferred), fall back to sync
        async_client = AsyncWhatsAppClient.from_tenant(self.tenant)

        if async_client:
            # Use async batch sending with components
            recipient_data = [
                {'phone_number': phone, 'custom_body_params': body_params or []}
                for phone in phone_numbers
            ]

            async_results = run_async(async_client.send_batch_with_components(
                recipients=recipient_data,
                template_name=template_name,
                language_code=language,
                components=components,
                delay_ms=200
            ))

            return [
                {
                    "phone": r.phone,
                    "success": r.success,
                    "messageId": r.message_id,
                    "error": r.error_message if not r.success else None
                }
                for r in async_results
            ]

        # Fallback to sync sending via WhatsAppService
        results = []
        for phone in phone_numbers:
            try:
                result = self.wa_service.send_template_with_components(
                    to=phone,
                    template_name=template_name,
                    language_code=language,
                    components=components
                )
                results.append({
                    "phone": phone,
                    "success": result.get('success', False),
                    "messageId": result.get('message_id'),
                    "error": result.get('error_message') if not result.get('success') else None
                })
            except Exception as e:
                logger.exception("Error sending to {}: {}".format(phone, e))
                results.append({
                    "phone": phone,
                    "success": False,
                    "messageId": None,
                    "error": str(e)
                })

        return results

    def create_scheduled_job(
        self,
        phone_numbers: List[str],
        template_name: str,
        language: str,
        scheduled_time: datetime,
        request_hash: str,
        template_type: str = 'standard',
        header: Optional[Dict] = None,
        body_params: Optional[List[str]] = None,
        button_params: Optional[List[Dict]] = None,
        cards: Optional[List[Dict]] = None
    ) -> SchedulerJob:
        """
        Create a scheduled job with full v2 data.
        
        Stores template_type, header_data, and cards_json for accurate
        replay when the scheduled time arrives.
        """
        # Legacy field: extract image URL for backward compat
        header_image = ''
        if header and header.get('type') == 'image':
            header_image = header.get('url', '')

        with transaction.atomic():
            job = SchedulerJob.objects.create(
                tenant=self.tenant,
                template_name=template_name,
                language_code=language,
                body_params=body_params or [],
                header_image_url=header_image,
                button_params=button_params or [],
                # v2 fields
                template_type=template_type,
                header_data=header or {},
                cards_json=cards or [],
                scheduled_time=scheduled_time,
                job_hash=request_hash,
                status=SchedulerJobStatus.PENDING
            )

            # Bulk create recipients
            recipients = [
                SchedulerJobRecipient(job=job, phone_number=phone)
                for phone in phone_numbers
            ]
            SchedulerJobRecipient.objects.bulk_create(recipients, batch_size=1000)

        return job


# ============================================
# VIEW
# ============================================

@api_view(['POST'])
@permission_classes([IsAuthenticated, IsTenantMember])
def universal_send(request):
    """
    Universal WhatsApp template message send endpoint v2.

    POST /api/messaging/send

    Supports BOTH standard and carousel templates in a single endpoint.

    === Standard Template Request ===
    {
        "phoneNumbers": ["919876543210", "919876543211"],
        "templateName": "welcome_offer",
        "language": "en_US",
        "templateType": "standard",
        "date": "2025-12-30",
        "time": "14:30",
        "header": {
            "type": "image",
            "url": "https://example.com/image.jpg"
        },
        "bodyParams": ["John", "20% OFF"],
        "buttonParams": [
            {"sub_type": "quick_reply", "text": "Yes", "index": 0}
        ]
    }

    === Carousel Template Request ===
    {
        "phoneNumbers": ["919876543210"],
        "templateName": "product_showcase",
        "language": "en_US",
        "templateType": "carousel",
        "date": "2025-12-30",
        "time": "14:30",
        "bodyParams": ["Welcome to our store!"],
        "cards": [
            {
                "header": {"type": "image", "url": "https://example.com/p1.jpg"},
                "bodyParams": ["Product 1", "$99"],
                "buttonParams": [
                    {"sub_type": "url", "text": "/product/1", "index": 0},
                    {"sub_type": "quick_reply", "text": "Buy Now", "index": 1}
                ]
            },
            {
                "header": {"type": "image", "url": "https://example.com/p2.jpg"},
                "bodyParams": ["Product 2", "$149"],
                "buttonParams": [
                    {"sub_type": "url", "text": "/product/2", "index": 0},
                    {"sub_type": "quick_reply", "text": "Buy Now", "index": 1}
                ]
            }
        ]
    }

    === Response (Immediate) ===
    {
        "success": true,
        "immediate": true,
        "templateType": "carousel",
        "message": "Messages sent immediately",
        "results": [...]
    }

    === Response (Scheduled) ===
    {
        "scheduled": true,
        "templateType": "carousel",
        "jobId": "uuid",
        "scheduledFor": "30/12/2025, 02:30:00 PM",
        "scheduledForUTC": "2025-12-30T09:00:00Z",
        "recipientCount": 2
    }
    """
    # Validate input
    serializer = UniversalSendSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(
            {"error": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST
        )

    data = serializer.validated_data
    tenant = request.user.tenant

    if not tenant:
        return Response(
            {"error": "User must belong to a tenant"},
            status=status.HTTP_400_BAD_REQUEST
        )

    template_type = data.get('templateType', 'standard')

    # Initialize service
    service = UniversalSendService(tenant)

    # Check WhatsApp configuration
    if not service.wa_service.is_configured:
        return Response(
            {"error": "WhatsApp not configured for this client"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Create request hash for deduplication (includes template_type + params)
    request_hash = service.create_request_hash(
        phone_numbers=data['phoneNumbers'],
        template_name=data['templateName'],
        template_type=template_type,
        date_str=data['date'],
        time_str=data['time'],
        body_params=data.get('bodyParams', []),
        button_params=data.get('buttonParams', []),
        cards=data.get('cards', [])
    )

    # Check for duplicates
    if SchedulerJob.objects.filter(
        job_hash=request_hash,
        status__in=[SchedulerJobStatus.PENDING, SchedulerJobStatus.PROCESSING]
    ).exists():
        return Response(
            {
                "error": "Duplicate request detected",
                "message": "A request with the same parameters is already scheduled or processing"
            },
            status=status.HTTP_409_CONFLICT
        )

    # Parse IST to UTC
    scheduled_utc = service.parse_ist_to_utc(data['date'], data['time'])
    scheduled_ist = scheduled_utc.astimezone(IST)

    # Check if should process immediately (buffer: now + 1 min)
    now = timezone.now()
    buffer_time = now + timedelta(minutes=1)

    if buffer_time >= scheduled_utc:
        # Process immediately
        results = service.send_immediate(
            phone_numbers=data['phoneNumbers'],
            template_name=data['templateName'],
            language=data.get('language', 'en_US'),
            template_type=template_type,
            header=data.get('header'),
            body_params=data.get('bodyParams', []),
            button_params=data.get('buttonParams', []),
            cards=data.get('cards', [])
        )

        success_count = sum(1 for r in results if r.get('success'))

        return Response({
            "success": success_count > 0,
            "immediate": True,
            "templateType": template_type,
            "message": "Messages sent immediately",
            "total": len(results),
            "sent": success_count,
            "failed": len(results) - success_count,
            "results": results
        })

    # Create scheduled job
    job = service.create_scheduled_job(
        phone_numbers=data['phoneNumbers'],
        template_name=data['templateName'],
        language=data.get('language', 'en_US'),
        scheduled_time=scheduled_utc,
        request_hash=request_hash,
        template_type=template_type,
        header=data.get('header'),
        body_params=data.get('bodyParams', []),
        button_params=data.get('buttonParams', []),
        cards=data.get('cards', [])
    )

    return Response({
        "scheduled": True,
        "templateType": template_type,
        "jobId": str(job.id),
        "scheduledFor": scheduled_ist.strftime('%d/%m/%Y, %I:%M:%S %p'),
        "scheduledForUTC": scheduled_utc.isoformat(),
        "recipientCount": len(data['phoneNumbers'])
    }, status=status.HTTP_201_CREATED)
