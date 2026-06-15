"""
Inbox Webhook Listener.

Uses Django post_save signals on the existing messaging.Message model.
This is a completely non-breaking extension — the existing webhook controller
in webhooks/views.py is NOT modified in any way.

When the existing webhook controller stores a message via
  messaging.models.Message.objects.create(...)
this signal fires and:

  Inbound  → find-or-create InboxConversation + create InboxMessage + WebSocket emit
  Outbound → (not processed here; outbound already handled in InboxSendService)

When the existing webhook controller updates a message status via
  message.save()
this signal fires and mirrors the status onto the corresponding InboxMessage.
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def _connect():
    """
    Deferred connection.  Called from InboxConfig.ready() so that the
    messaging models are fully registered before we attach signals.
    """
    from django.db.models import F
    from messaging.models import Message, MessageDirection, MessageStatus
    from .models import (
        InboxConversation,
        InboxMessage,
        InboxMessageDirection,
        InboxMessageStatus,
        InboxMessageType,
    )

    # ------------------------------------------------------------------
    # Signal: new inbound message → mirror to inbox
    # ------------------------------------------------------------------

    @receiver(post_save, sender=Message, weak=False, dispatch_uid='inbox_inbound_mirror')
    def on_message_saved(sender, instance: Message, created: bool, **kwargs):
        """
        Mirror inbound messages into the inbox tables.
        Also mirror status updates for tracked outbound messages.
        """
        try:
            tenant = instance.tenant  # property on messaging.Message

            # -----------------------------------------------------------
            # New inbound message → create inbox conversation + message
            # -----------------------------------------------------------
            if created and instance.direction == MessageDirection.INBOUND:
                contact = instance.conversation.contact
                customer_phone = contact.phone
                customer_name = contact.name or ''

                # Derive preview text
                if instance.message_type == 'TEXT':
                    preview = instance.content or ''
                else:
                    preview = f'[{instance.message_type.lower()}]'

                import time
                from django.utils import timezone

                # Find-or-create InboxConversation
                inbox_conv, created = InboxConversation.objects.get_or_create(
                    tenant=tenant,
                    customer_phone=customer_phone,
                    defaults={
                        'customer_name': customer_name,
                        'last_message': preview[:500],
                        'last_message_time': timezone.now(),
                        'unread_count': 1,
                    },
                )

                # Update snapshot atomically (avoids race condition on unread_count)
                if not created:
                    update_fields = {
                        'last_message': preview[:500],
                        'last_message_time': timezone.now(),
                        'unread_count': F('unread_count') + 1,
                        'updated_at': timezone.now(),
                    }
                    if customer_name and not inbox_conv.customer_name:
                        update_fields['customer_name'] = customer_name
                    InboxConversation.objects.filter(pk=inbox_conv.pk).update(**update_fields)
                    # Refresh to get DB-computed unread_count
                    inbox_conv.refresh_from_db(fields=['unread_count'])

                # Map message type
                type_map = {v: v for v in InboxMessageType.values}
                inbox_type = type_map.get(
                    instance.message_type, InboxMessageType.TEXT
                )

                # Create InboxMessage (skip duplicates by meta_message_id)
                if instance.wa_message_id and InboxMessage.objects.filter(
                    meta_message_id=instance.wa_message_id
                ).exists():
                    return  # already mirrored

                inbox_msg = InboxMessage.objects.create(
                    tenant=tenant,
                    conversation=inbox_conv,
                    meta_message_id=instance.wa_message_id or '',
                    direction=InboxMessageDirection.INBOUND,
                    type=inbox_type,
                    content_json=instance.payload or {},
                    status=InboxMessageStatus.DELIVERED,
                    timestamp=int(
                        instance.created_at.timestamp()
                        if instance.created_at else time.time()
                    ),
                )

                # Emit WebSocket event
                try:
                    from .websocket import emit_new_message
                    emit_new_message(tenant_id=str(tenant.id), message=inbox_msg)
                except Exception as exc:
                    logger.warning(f'[Inbox] WebSocket emit failed (non-fatal): {exc}')

            # -----------------------------------------------------------
            # Status update on outbound → mirror to InboxMessage
            # -----------------------------------------------------------
            elif not created and instance.direction == MessageDirection.OUTBOUND:
                if not instance.wa_message_id:
                    return

                status_map = {
                    MessageStatus.SENT: InboxMessageStatus.SENT,
                    MessageStatus.DELIVERED: InboxMessageStatus.DELIVERED,
                    MessageStatus.READ: InboxMessageStatus.READ,
                    MessageStatus.FAILED: InboxMessageStatus.FAILED,
                }
                new_status = status_map.get(instance.status)
                if not new_status:
                    return

                updated = InboxMessage.objects.filter(
                    meta_message_id=instance.wa_message_id
                ).exclude(status=new_status).update(status=new_status)

                if updated:
                    logger.debug(
                        f'[Inbox] Mirrored status {new_status} for '
                        f'wamid={instance.wa_message_id}'
                    )
                    try:
                        from .websocket import emit_status_update
                        emit_status_update(
                            tenant_id=str(instance.tenant.id),
                            meta_message_id=instance.wa_message_id,
                            new_status=new_status,
                        )
                    except Exception as exc:
                        logger.warning(
                            f'[Inbox] WebSocket status emit failed (non-fatal): {exc}'
                        )

        except Exception as exc:
            # Never let inbox errors break the main webhook flow
            logger.error(f'[Inbox] webhook_listener error: {exc}', exc_info=True)
