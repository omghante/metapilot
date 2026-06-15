"""
Webhook handlers for Meta WhatsApp Business API.
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.utils import timezone
from django.conf import settings
import hashlib
import hmac
import json
import logging

from tenants.models import TenantConfig, ConfigProvider
from messaging.models import (
    Contact, Conversation, Message,
    MessageDirection, MessageStatus, MessageType, ConversationStatus
)

logger = logging.getLogger(__name__)


class WebhookVerifyView(APIView):
    """
    Webhook verification endpoint.
    
    GET /api/webhooks/verify/
    
    Meta sends a GET request to verify the webhook URL.
    We need to return the hub.challenge if hub.verify_token matches.
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        mode = request.query_params.get('hub.mode')
        token = request.query_params.get('hub.verify_token')
        challenge = request.query_params.get('hub.challenge')
        
        if mode == 'subscribe':
            # Find tenant by verify token
            config = TenantConfig.objects.filter(
                provider=ConfigProvider.META_WHATSAPP,
                key_name='webhook_verify_token',
                is_active=True
            ).first()
            
            if config:
                try:
                    stored_token = config.get_value()
                    if stored_token == token:
                        logger.info(f"Webhook verified for tenant: {config.tenant.name}")
                        return Response(int(challenge), status=status.HTTP_200_OK)
                except Exception as e:
                    logger.error(f"Error verifying webhook: {e}")
            
            logger.warning(f"Webhook verification failed for token: {token[:10]}...")
            return Response({'error': 'Verification failed'}, status=status.HTTP_403_FORBIDDEN)
        
        return Response({'error': 'Invalid mode'}, status=status.HTTP_400_BAD_REQUEST)


class WebhookReceiveView(APIView):
    """
    Webhook receiver for incoming messages.
    
    POST /api/webhooks/receive/
    
    Meta sends a POST request with message data.
    We need to:
    1. Verify the signature (optional but recommended)
    2. Find the tenant by phone_number_id
    3. Store the message
    4. Return 200 OK immediately
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            # Parse webhook data
            data = request.data
            
            # Find tenant by phone_number_id to get app_secret for verification
            entries = data.get('entry', [])
            tenant = None
            
            for entry in entries:
                for change in entry.get('changes', []):
                    if change.get('field') == 'messages':
                        value = change.get('value', {})
                        phone_number_id = value.get('metadata', {}).get('phone_number_id')
                        if phone_number_id:
                            # Find tenant
                            for cfg in TenantConfig.objects.filter(
                                provider=ConfigProvider.META_WHATSAPP,
                                key_name='phone_number_id',
                                is_active=True
                            ):
                                try:
                                    if cfg.get_value() == phone_number_id:
                                        tenant = cfg.tenant
                                        break
                                except Exception:
                                    continue
                        if tenant:
                            break
                if tenant:
                    break
            
            # Verify webhook signature if tenant found and app_secret configured
            if tenant:
                from .security import verify_webhook_signature, get_app_secret_for_tenant
                app_secret = get_app_secret_for_tenant(tenant)
                if app_secret and not verify_webhook_signature(request, app_secret):
                    logger.warning(f"Invalid webhook signature for tenant {tenant.name}")
                    return Response({'error': 'Invalid signature'}, status=status.HTTP_403_FORBIDDEN)
            
            # Process entries
            for entry in entries:
                changes = entry.get('changes', [])
                
                for change in changes:
                    if change.get('field') == 'messages':
                        self._process_message_change(change.get('value', {}))
            
            # Always return 200 to acknowledge receipt
            return Response({'status': 'ok'}, status=status.HTTP_200_OK)
        
        except Exception as e:
            logger.error(f"Webhook processing error: {e}")
            # Still return 200 to prevent Meta from retrying
            return Response({'status': 'error'}, status=status.HTTP_200_OK)
    
    def _process_message_change(self, value):
        """Process a message change from webhook."""
        metadata = value.get('metadata', {})
        phone_number_id = metadata.get('phone_number_id')
        
        if not phone_number_id:
            logger.warning("No phone_number_id in webhook")
            return
        
        # Find tenant by phone_number_id
        config = TenantConfig.objects.filter(
            provider=ConfigProvider.META_WHATSAPP,
            key_name='phone_number_id',
            is_active=True
        ).first()
        
        tenant = None
        for cfg in TenantConfig.objects.filter(
            provider=ConfigProvider.META_WHATSAPP,
            key_name='phone_number_id',
            is_active=True
        ):
            try:
                if cfg.get_value() == phone_number_id:
                    tenant = cfg.tenant
                    break
            except Exception:
                continue
        
        if not tenant:
            logger.warning(f"No tenant found for phone_number_id: {phone_number_id}")
            return
        
        # Process messages
        messages = value.get('messages', [])
        for msg_data in messages:
            self._store_message(tenant, msg_data)
            # Feed the real-time inbox
            try:
                from inbox.services import ingest_inbound_message
                ingest_inbound_message(tenant, msg_data)
            except Exception as e:
                logger.error(f"[Inbox ingest] Failed for {tenant.name}: {e}")

        # Process status updates
        statuses = value.get('statuses', [])
        for status_data in statuses:
            self._update_message_status(status_data)
            # Sync delivery status to inbox
            try:
                from inbox.services import ingest_status_update
                ingest_status_update(tenant, status_data)
            except Exception as e:
                logger.error(f"[Inbox status] Failed for {tenant.name}: {e}")
    
    def _store_message(self, tenant, msg_data):
        """Store an incoming message."""
        from_phone = msg_data.get('from')
        wa_message_id = msg_data.get('id')
        msg_type = msg_data.get('type', 'text').upper()
        timestamp = msg_data.get('timestamp')
        
        # Get or create contact
        contact, created = Contact.objects.get_or_create(
            tenant=tenant,
            phone=from_phone,
            defaults={'name': '', 'is_subscribed': True}
        )
        
        # Get or create conversation
        conversation, created = Conversation.objects.get_or_create(
            contact=contact,
            defaults={'status': ConversationStatus.ACTIVE}
        )
        
        # Extract content based on type
        content = ''
        payload = msg_data
        
        if msg_type == 'TEXT':
            content = msg_data.get('text', {}).get('body', '')
        
        # Map message type
        message_type_map = {
            'TEXT': MessageType.TEXT,
            'IMAGE': MessageType.IMAGE,
            'DOCUMENT': MessageType.DOCUMENT,
            'AUDIO': MessageType.AUDIO,
            'VIDEO': MessageType.VIDEO,
            'STICKER': MessageType.STICKER,
            'LOCATION': MessageType.LOCATION,
            'CONTACTS': MessageType.CONTACTS,
            'INTERACTIVE': MessageType.INTERACTIVE,
            'REACTION': MessageType.REACTION,
        }
        
        # Create message
        Message.objects.create(
            conversation=conversation,
            wa_message_id=wa_message_id,
            direction=MessageDirection.INBOUND,
            message_type=message_type_map.get(msg_type, MessageType.TEXT),
            status=MessageStatus.DELIVERED,
            content=content,
            payload=payload
        )
        
        # Update conversation last_message_at
        conversation.last_message_at = timezone.now()
        conversation.save()
        
        logger.info(f"Stored message from {from_phone} for tenant {tenant.name}")
        
        # WhatsApp AI Chatbot auto-reply
        if getattr(settings, 'WA_CHATBOT_ENABLED', False):
            try:
                from wa_chatbot.views import WhatsAppChatbotHandler
                
                handler = WhatsAppChatbotHandler(tenant=tenant)
                response = handler.process_message(from_phone, msg_data)
                
                if response:
                    result = handler.send_reply(from_phone, response)
                    logger.info(f"Chatbot replied to {from_phone}: {result}")
            except Exception as e:
                logger.error(f"Chatbot error for {from_phone}: {e}")
    
    def _update_message_status(self, status_data):
        """Update outbound message status from webhook."""
        wa_message_id = status_data.get('id')
        new_status = status_data.get('status', '').upper()
        
        if not wa_message_id:
            return
        
        status_map = {
            'SENT': MessageStatus.SENT,
            'DELIVERED': MessageStatus.DELIVERED,
            'READ': MessageStatus.READ,
            'FAILED': MessageStatus.FAILED,
        }
        
        message_status = status_map.get(new_status)
        if not message_status:
            return
        
        try:
            message = Message.objects.get(wa_message_id=wa_message_id)
            message.status = message_status
            
            if new_status == 'SENT':
                message.sent_at = timezone.now()
            elif new_status == 'DELIVERED':
                message.delivered_at = timezone.now()
            elif new_status == 'READ':
                message.read_at = timezone.now()
            elif new_status == 'FAILED':
                errors = status_data.get('errors', [])
                if errors:
                    message.error_code = errors[0].get('code', '')
                    message.error_message = errors[0].get('message', '')
            
            message.save()
            logger.info(f"Updated message {wa_message_id} status to {new_status}")
        
        except Message.DoesNotExist:
            logger.warning(f"Message not found for status update: {wa_message_id}")
