"""
Per-tenant webhook views for WhatsApp AI chatbot.

Each tenant gets a unique webhook URL:
{WEBHOOK_BASE_URL}/api/wa-chatbot/webhook/{tenant_id}/

Configure via environment variable WEBHOOK_BASE_URL.
Default: https://wavi-api.curlshell.com

Meta WhatsApp will:
1. GET to verify the webhook (challenge verification)
2. POST to send incoming messages
"""
import json
import logging
import traceback
from django.http import HttpResponse, JsonResponse
from django.views import View
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

from tenants.models import Tenant, TenantConfig, ConfigProvider
from messaging.models import (
    Contact, Conversation, Message,
    MessageDirection, MessageStatus, MessageType, ConversationStatus
)
from .views import WhatsAppChatbotHandler

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
class TenantWebhookView(View):
    """
    Handle per-tenant WhatsApp webhooks.
    
    URL: /api/wa-chatbot/webhook/{tenant_id}/
    
    GET: Webhook verification (Meta challenge)
    POST: Receive incoming messages
    """
    
    def get(self, request, tenant_id):
        """
        Handle webhook verification from Meta.
        
        Meta sends:
        - hub.mode=subscribe
        - hub.challenge=random_number
        - hub.verify_token=your_verify_token
        
        We must return the challenge if verify_token matches.
        """
        mode = request.GET.get('hub.mode')
        token = request.GET.get('hub.verify_token')
        challenge = request.GET.get('hub.challenge')
        
        logger.info(f"Webhook verification for tenant {tenant_id}: mode={mode}")
        
        # Get tenant
        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            logger.error(f"Tenant not found: {tenant_id}")
            return HttpResponse('Tenant not found', status=404)
        
        # Check if tenant is active
        if not tenant.is_active:
            logger.warning(f"Tenant suspended: {tenant_id}")
            return HttpResponse('Tenant suspended', status=403)
        
        # Verify token using tenant's webhook_token
        if mode == 'subscribe' and token == tenant.webhook_token:
            logger.info(f"Webhook verified for tenant: {tenant.name}")
            return HttpResponse(challenge, content_type='text/plain')
        else:
            logger.warning(f"Invalid verify token for tenant {tenant_id}")
            return HttpResponse('Forbidden', status=403)
    
    def post(self, request, tenant_id):
        """
        Handle incoming WhatsApp messages for this tenant.
        """
        try:
            # Log incoming webhook for debugging
            logger.info(f"=== Webhook POST received for tenant {tenant_id} ===")
            
            # Get tenant
            try:
                tenant = Tenant.objects.get(id=tenant_id)
            except Tenant.DoesNotExist:
                logger.error(f"Tenant not found: {tenant_id}")
                return JsonResponse({'error': 'Tenant not found'}, status=404)
            
            logger.info(f"Tenant found: {tenant.name} (active={tenant.is_active}, ai_enabled={tenant.ai_features_enabled})")
            
            # Check if tenant is active
            if not tenant.is_active:
                logger.warning(f"Tenant suspended: {tenant_id}")
                return JsonResponse({'error': 'Tenant suspended'}, status=403)
            
            # Verify webhook signature
            from webhooks.security import verify_webhook_signature, get_app_secret_for_tenant
            app_secret = get_app_secret_for_tenant(tenant)
            if app_secret and not verify_webhook_signature(request, app_secret):
                logger.warning(f"Invalid webhook signature for tenant {tenant.name}")
                return JsonResponse({'error': 'Invalid signature'}, status=403)
            
            # Parse request body
            try:
                data = json.loads(request.body)
                logger.debug(f"Webhook payload: {json.dumps(data)[:2000]}")  # Log first 2KB
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in webhook: {e}")
                return JsonResponse({'error': 'Invalid JSON'}, status=400)
            
            # Process WhatsApp messages
            entry = data.get('entry', [])
            if not entry:
                logger.info("No entry in webhook payload, acknowledging")
                return HttpResponse('OK', status=200)
            
            messages_processed = 0
            for e in entry:
                changes = e.get('changes', [])
                for change in changes:
                    value = change.get('value', {})
                    
                    # Handle message status updates
                    statuses = value.get('statuses', [])
                    for status_data in statuses:
                        self._update_message_status(status_data)
                    
                    # Handle incoming messages
                    messages = value.get('messages', [])
                    contacts = value.get('contacts', [])  # Extract sender info
                    
                    for msg in messages:
                        # First, store the message in the database
                        is_new = self._store_incoming_message(tenant, msg, contacts)
                        
                        # Then, process with AI chatbot if enabled (only for new messages)
                        if not is_new:
                            logger.info("Skipping AI processing for duplicate message")
                        elif tenant.ai_features_enabled:
                            self._process_ai_response(tenant, msg)
                        else:
                            logger.info(f"AI features disabled for tenant {tenant.name}, skipping AI response")
                        
                        messages_processed += 1
            
            logger.info(f"Webhook processed successfully: {messages_processed} messages")
            return HttpResponse('OK', status=200)
            
        except Exception as e:
            logger.error(f"Error processing webhook for {tenant_id}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return HttpResponse('OK', status=200)  # Always return 200 to prevent retries
    
    def _store_incoming_message(self, tenant, msg_data, contacts=None):
        """Store incoming message in the database.
        
        Returns:
            True if a new message was stored, False if it was a duplicate.
        """
        try:
            from_phone = msg_data.get('from', '')
            wa_message_id = msg_data.get('id')
            msg_type = msg_data.get('type', 'text').upper()
            
            logger.info(f"Storing message from {from_phone}, type={msg_type}, id={wa_message_id}")
            
            # Extract sender name from contacts if available
            sender_name = ''
            if contacts:
                for contact in contacts:
                    if contact.get('wa_id') == from_phone:
                        profile = contact.get('profile', {})
                        sender_name = profile.get('name', '')
                        break
            
            # Get or create contact
            contact, created = Contact.objects.get_or_create(
                tenant=tenant,
                phone=from_phone,
                defaults={'name': sender_name, 'is_subscribed': True}
            )
            if created:
                logger.info(f"Created new contact: {from_phone} ({sender_name})")
            elif sender_name and not contact.name:
                # Update name if we now have it
                contact.name = sender_name
                contact.save(update_fields=['name'])
            
            # Get or create conversation
            conversation, created = Conversation.objects.get_or_create(
                contact=contact,
                defaults={'status': ConversationStatus.ACTIVE}
            )
            if created:
                logger.info(f"Created new conversation for {from_phone}")
            
            # Extract content based on type
            content = ''
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
            
            # Check if message already exists (avoid duplicates)
            if Message.objects.filter(wa_message_id=wa_message_id).exists():
                logger.info(f"Message {wa_message_id} already exists, skipping storage")
                return False
            
            # Create message
            Message.objects.create(
                conversation=conversation,
                wa_message_id=wa_message_id,
                direction=MessageDirection.INBOUND,
                message_type=message_type_map.get(msg_type, MessageType.TEXT),
                status=MessageStatus.DELIVERED,
                content=content,
                payload=msg_data
            )
            
            # Update conversation last_message_at
            conversation.last_message_at = timezone.now()
            conversation.save(update_fields=['last_message_at'])
            
            logger.info(f"Stored message from {from_phone} for tenant {tenant.name}")
            return True
            
        except Exception as e:
            logger.error(f"Error storing message: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    @staticmethod
    def _mask_phone(phone: str) -> str:
        """Mask phone number for safe logging (show last 4 digits only)."""
        if not phone or len(phone) < 4:
            return "***"
        return f"***{phone[-4:]}"
    
    def _process_ai_response(self, tenant, msg_data):
        """Process message with AI chatbot and send response."""
        try:
            from_phone = msg_data.get('from', '')
            masked = self._mask_phone(from_phone)
            
            logger.info(f"Processing AI response for {masked}")
            
            # Initialize chatbot handler for this tenant
            handler = WhatsAppChatbotHandler(tenant=tenant)
            
            # Process message and get response
            response = handler.process_message(from_phone, msg_data)
            
            if response:
                logger.info(f"AI response generated for {masked}, length={len(response)}")
                # Send reply
                result = handler.send_reply(from_phone, response)
                logger.info(f"Reply sent to {masked}, success={result.get('success', False) if isinstance(result, dict) else 'unknown'}")
                
                # Store the outbound AI response in the database
                self._store_outbound_ai_message(tenant, from_phone, response, result)
            else:
                logger.info(f"No AI response generated for {masked}")
                
        except Exception as e:
            logger.error(f"Error processing AI response for tenant {tenant.id}: {type(e).__name__}")
            logger.error(f"Traceback: {traceback.format_exc()}")
    
    def _store_outbound_ai_message(self, tenant, to_phone, response_text, wa_result):
        """Store the AI chatbot's outbound response in the database."""
        try:
            # Get existing contact (should exist since we stored incoming first)
            contact = Contact.objects.filter(
                tenant=tenant,
                phone=to_phone
            ).first()
            
            if not contact:
                logger.warning("No contact found for recipient, skipping outbound storage")
                return
            
            # Get the conversation
            conversation = Conversation.objects.filter(contact=contact).first()
            if not conversation:
                logger.warning("No conversation found for recipient, skipping outbound storage")
                return
            
            # Extract wa_message_id from the WhatsApp API response
            wa_message_id = ''
            if isinstance(wa_result, dict):
                messages = wa_result.get('messages', [])
                if messages:
                    wa_message_id = messages[0].get('id', '')
            
            # Create outbound message record
            Message.objects.create(
                conversation=conversation,
                wa_message_id=wa_message_id,
                direction=MessageDirection.OUTBOUND,
                message_type=MessageType.TEXT,
                status=MessageStatus.SENT,
                content=response_text,
                sent_at=timezone.now(),
            )
            
            # Update conversation last_message_at
            conversation.last_message_at = timezone.now()
            conversation.save(update_fields=['last_message_at'])
            
            logger.info("Stored outbound AI response successfully")
            
        except Exception as e:
            logger.error(f"Error storing outbound AI message: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
    
    def _update_message_status(self, status_data):
        """Update outbound message status from webhook."""
        try:
            wa_message_id = status_data.get('id')
            new_status = status_data.get('status', '').upper()
            
            if not wa_message_id:
                return
            
            logger.debug(f"Status update for message {wa_message_id}: {new_status}")
            
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
                logger.debug(f"Message not found for status update: {wa_message_id}")
                
        except Exception as e:
            logger.error(f"Error updating message status: {e}")

