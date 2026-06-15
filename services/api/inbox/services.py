"""
Inbox Send Service.

Handles outbound WhatsApp message sending for the chat inbox.
Reads tenant credentials using the same TenantConfig pattern as the existing
WhatsApp service, but is entirely independent — no imports from messaging.whatsapp_service.

Flow:
  1. Read phone_number_id and access_token from TenantConfig.
  2. Build Meta Graph API payload.
  3. POST to https://graph.facebook.com/{GRAPH_API_VERSION}/{PHONE_NUMBER_ID}/messages
  4. Persist InboxMessage.
  5. Emit WebSocket event to tenant channel.
  6. Update InboxConversation last_message snapshot.

Inbound flow (called from webhooks/views.py):
  ingest_inbound_message(tenant, msg_data) — creates/updates InboxConversation
  and InboxMessage records, then emits WebSocket events.
"""
import logging
import time
from typing import Optional

import requests
from django.conf import settings
from django.db.models import F
from django.utils import timezone

from tenants.models import TenantConfig, ConfigProvider

from .models import (
    InboxConversation,
    InboxMessage,
    InboxMessageDirection,
    InboxMessageStatus,
    InboxMessageType,
)

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = getattr(settings, 'META_GRAPH_API_VERSION', 'v19.0')
GRAPH_API_BASE = f'https://graph.facebook.com/{GRAPH_API_VERSION}'

_MSG_TYPE_MAP = {
    'text': InboxMessageType.TEXT,
    'image': InboxMessageType.IMAGE,
    'document': InboxMessageType.DOCUMENT,
    'audio': InboxMessageType.AUDIO,
    'video': InboxMessageType.VIDEO,
    'sticker': InboxMessageType.STICKER,
    'location': InboxMessageType.LOCATION,
    'contacts': InboxMessageType.CONTACTS,
    'interactive': InboxMessageType.INTERACTIVE,
    'reaction': InboxMessageType.REACTION,
}


# ---------------------------------------------------------------------------
# Inbound ingestion (called by webhooks/views.py)
# ---------------------------------------------------------------------------

def ingest_inbound_message(tenant, msg_data: dict) -> None:
    """
    Create/update InboxConversation + InboxMessage for an inbound message
    received from the Meta webhook, then push WebSocket events.

    Parameters
    ----------
    tenant  : Tenant instance resolved from phone_number_id
    msg_data: Raw message object from the webhook 'messages' array
    """
    from_phone = msg_data.get('from', '')
    if not from_phone:
        logger.warning('[Inbox ingest] msg_data missing "from" field — skipped')
        return

    wa_message_id = msg_data.get('id', '')
    raw_type = msg_data.get('type', 'text').lower()
    msg_type = _MSG_TYPE_MAP.get(raw_type, InboxMessageType.UNSUPPORTED)
    timestamp_unix = int(msg_data.get('timestamp', time.time()))

    # Derive a text preview for the conversation snapshot
    if raw_type == 'text':
        preview = msg_data.get('text', {}).get('body', '')
    elif raw_type == 'reaction':
        preview = f'Reacted {msg_data.get("reaction", {}).get("emoji", "")} to a message'
    else:
        preview = f'[{raw_type}]'

    # Resolve customer display name (best-effort from contacts array)
    customer_name = ''
    contacts = msg_data.get('contacts', []) if raw_type != 'contacts' else []
    if contacts:
        customer_name = contacts[0].get('profile', {}).get('name', '')

    with __import__('django').db.transaction.atomic():
        # get_or_create InboxConversation keyed on (tenant, customer_phone)
        conversation, created = InboxConversation.objects.get_or_create(
            tenant=tenant,
            customer_phone=from_phone,
            defaults={
                'customer_name': customer_name,
                'last_message': preview[:500],
                'last_message_time': timezone.now(),
                'unread_count': 1,
            },
        )

        if not created:
            # Update snapshot atomically
            update_fields = {
                'last_message': preview[:500],
                'last_message_time': timezone.now(),
                'unread_count': F('unread_count') + 1,
                'updated_at': timezone.now(),
            }
            if customer_name and not conversation.customer_name:
                update_fields['customer_name'] = customer_name
            InboxConversation.objects.filter(pk=conversation.pk).update(**update_fields)
            conversation.refresh_from_db()

        # Deduplicate by meta_message_id
        if wa_message_id and InboxMessage.objects.filter(meta_message_id=wa_message_id).exists():
            logger.info(f'[Inbox ingest] Duplicate wamid={wa_message_id} — skipped')
            return

        message = InboxMessage.objects.create(
            tenant=tenant,
            conversation=conversation,
            meta_message_id=wa_message_id,
            direction=InboxMessageDirection.INBOUND,
            type=msg_type,
            content_json=msg_data,
            status=InboxMessageStatus.DELIVERED,
            timestamp=timestamp_unix,
        )

    logger.info(
        f'[Inbox ingest] Stored inbound {raw_type} from {from_phone} '
        f'for tenant {tenant.name} | wamid={wa_message_id}'
    )

    # Push WebSocket events (non-blocking)
    try:
        from .websocket import emit_new_message, emit_conversation_update
        emit_new_message(tenant_id=str(tenant.id), message=message)
        emit_conversation_update(tenant_id=str(tenant.id), conversation=conversation)
    except Exception as exc:
        logger.warning(f'[Inbox ingest] WebSocket emit failed (non-fatal): {exc}')


def ingest_status_update(tenant, status_data: dict) -> None:
    """
    Update InboxMessage delivery status from a webhook statuses entry.

    Parameters
    ----------
    tenant      : Tenant instance
    status_data : Raw status object from the webhook 'statuses' array
    """
    wa_message_id = status_data.get('id', '')
    new_status_raw = status_data.get('status', '').upper()

    status_map = {
        'SENT': InboxMessageStatus.SENT,
        'DELIVERED': InboxMessageStatus.DELIVERED,
        'READ': InboxMessageStatus.READ,
        'FAILED': InboxMessageStatus.FAILED,
    }
    new_status = status_map.get(new_status_raw)
    if not new_status or not wa_message_id:
        return

    updated = InboxMessage.objects.filter(meta_message_id=wa_message_id).update(status=new_status)
    if updated:
        logger.info(f'[Inbox ingest] Status {wa_message_id} → {new_status_raw}')
        try:
            from .websocket import emit_status_update
            emit_status_update(
                tenant_id=str(tenant.id),
                meta_message_id=wa_message_id,
                new_status=new_status_raw,
            )
        except Exception as exc:
            logger.warning(f'[Inbox ingest] WebSocket status emit failed (non-fatal): {exc}')


# ---------------------------------------------------------------------------
# Credential helper (mirrors existing whatsapp_service credential loading)
# ---------------------------------------------------------------------------

def _get_credentials(tenant) -> dict:
    """
    Return {'phone_number_id': ..., 'access_token': ...} for the tenant.
    Raises ValueError if either credential is missing or inactive.
    """
    phone_cfg = TenantConfig.objects.filter(
        tenant=tenant,
        provider=ConfigProvider.META_WHATSAPP,
        key_name='phone_number_id',
        is_active=True,
    ).first()

    token_cfg = TenantConfig.objects.filter(
        tenant=tenant,
        provider=ConfigProvider.META_WHATSAPP,
        key_name='access_token',
        is_active=True,
    ).first()

    if not phone_cfg:
        raise ValueError(f'phone_number_id not configured for tenant {tenant.name}')
    if not token_cfg:
        raise ValueError(f'access_token not configured for tenant {tenant.name}')

    return {
        'phone_number_id': phone_cfg.get_value(),
        'access_token': token_cfg.get_value(),
    }


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------

def _build_text_payload(to: str, text: str) -> dict:
    return {
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': to,
        'type': 'text',
        'text': {'body': text},
    }


def _build_generic_payload(to: str, msg_type: str, content_json: dict) -> dict:
    """
    For non-text types where the caller provides a fully-formed content_json
    object (e.g. image, document, audio, video, template).
    """
    payload = {
        'messaging_product': 'whatsapp',
        'recipient_type': 'individual',
        'to': to,
        'type': msg_type.lower(),
    }
    payload.update(content_json)
    return payload


# ---------------------------------------------------------------------------
# Public service class
# ---------------------------------------------------------------------------

class InboxSendService:
    """
    Stateless service for sending outbound inbox messages.
    Call InboxSendService.send(...) as a class method.
    """

    @classmethod
    def send(
        cls,
        tenant,
        conversation: InboxConversation,
        msg_type: str = 'TEXT',
        text: str = '',
        content_json: Optional[dict] = None,
    ) -> InboxMessage:
        """
        Send a message and persist it.

        Parameters
        ----------
        tenant       : Tenant instance (already validated against conversation)
        conversation : InboxConversation the message belongs to
        msg_type     : One of InboxMessageType choices (default TEXT)
        text         : Plain text body (used when msg_type == TEXT)
        content_json : Full Meta-format payload for non-text types

        Returns
        -------
        InboxMessage instance stored to DB.

        Raises
        ------
        ValueError   : credentials not configured or API rejected the request.
        """
        content_json = content_json or {}
        creds = _get_credentials(tenant)
        recipient_phone = conversation.customer_phone.lstrip('+')  # Meta expects no +

        # Build payload
        if msg_type == 'TEXT':
            payload = _build_text_payload(recipient_phone, text)
        else:
            payload = _build_generic_payload(recipient_phone, msg_type, content_json)

        # Call Meta Graph API
        url = f'{GRAPH_API_BASE}/{creds["phone_number_id"]}/messages'
        headers = {
            'Authorization': f'Bearer {creds["access_token"]}',
            'Content-Type': 'application/json',
        }

        meta_message_id = ''
        send_error_code = ''
        send_error_message = ''
        msg_status = InboxMessageStatus.PENDING

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            resp_data = resp.json()

            if resp.status_code == 200:
                meta_message_id = (
                    resp_data.get('messages', [{}])[0].get('id', '')
                )
                msg_status = InboxMessageStatus.SENT
                logger.info(
                    f'[Inbox] Sent message to {conversation.customer_phone} '
                    f'for tenant {tenant.name} | wamid={meta_message_id}'
                )
            else:
                error_obj = resp_data.get('error', {})
                send_error_code = str(error_obj.get('code', resp.status_code))
                send_error_message = error_obj.get('message', resp.text)
                msg_status = InboxMessageStatus.FAILED
                logger.error(
                    f'[Inbox] Meta API error {resp.status_code} for tenant '
                    f'{tenant.name}: {send_error_message}'
                )
                raise ValueError(f'Meta API error {resp.status_code}: {send_error_message}')

        except requests.RequestException as exc:
            send_error_message = str(exc)
            msg_status = InboxMessageStatus.FAILED
            logger.error(f'[Inbox] Network error sending message: {exc}')
            raise ValueError(f'Network error: {exc}') from exc

        # Persist outbound message
        stored_payload = content_json if msg_type != 'TEXT' else {'text': text}
        message = InboxMessage.objects.create(
            tenant=tenant,
            conversation=conversation,
            meta_message_id=meta_message_id,
            direction=InboxMessageDirection.OUTBOUND,
            type=InboxMessageType(msg_type) if msg_type in InboxMessageType.values else InboxMessageType.TEXT,
            content_json=stored_payload,
            status=msg_status,
            timestamp=int(time.time()),
            error_code=send_error_code,
            error_message=send_error_message,
        )

        # Update conversation snapshot
        preview = text if msg_type == 'TEXT' else f'[{msg_type.lower()}]'
        now = timezone.now()
        InboxConversation.objects.filter(pk=conversation.pk).update(
            last_message=preview[:500],
            last_message_time=now,
            updated_at=now,
        )

        # Emit WebSocket event (non-blocking; errors are swallowed to avoid
        # breaking the HTTP response if the channel layer is unavailable)
        try:
            from .websocket import emit_new_message
            emit_new_message(tenant_id=str(tenant.id), message=message)
        except Exception as exc:
            logger.warning(f'[Inbox] WebSocket emit failed (non-fatal): {exc}')

        return message
