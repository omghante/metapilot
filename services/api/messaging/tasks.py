"""
Celery tasks for messaging operations.
Background tasks for async message sending and scheduled campaigns.
"""
import logging
from celery import shared_task
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_message_task(self, message_id: str):
    """
    Send a single WhatsApp message asynchronously.
    
    Args:
        message_id: UUID of the Message to send
    """
    from messaging.models import Message, MessageStatus
    from messaging.whatsapp_service import send_message
    
    try:
        message = Message.objects.get(id=message_id)
        
        # Skip if already sent or failed
        if message.status in [MessageStatus.SENT, MessageStatus.DELIVERED, MessageStatus.READ]:
            logger.info(f"Message {message_id} already sent, skipping")
            return {'status': 'skipped', 'message_id': str(message_id)}
        
        # Send the message
        success = send_message(message)
        
        return {
            'status': 'sent' if success else 'failed',
            'message_id': str(message_id),
            'wa_message_id': message.wa_message_id if success else None
        }
        
    except Message.DoesNotExist:
        logger.error(f"Message {message_id} not found")
        return {'status': 'error', 'error': 'Message not found'}
    except Exception as e:
        logger.exception(f"Error sending message {message_id}: {e}")
        # Retry on failure
        raise self.retry(exc=e)


@shared_task(bind=True)
def send_campaign_messages_task(self, campaign_id: str):
    """
    Send all messages for a campaign.
    
    Args:
        campaign_id: UUID of the Campaign
    """
    from campaigns.models import Campaign, CampaignStatus, ScheduledMessage, MessageResult
    from messaging.models import Contact, Conversation, Message, MessageDirection, MessageStatus, MessageType, ConversationStatus
    from messaging.whatsapp_service import send_message
    
    try:
        campaign = Campaign.objects.get(id=campaign_id)
        
        if campaign.status not in [CampaignStatus.SCHEDULED, CampaignStatus.ACTIVE]:
            logger.info(f"Campaign {campaign_id} status is {campaign.status}, skipping")
            return {'status': 'skipped', 'reason': f'Campaign status: {campaign.status}'}
        
        # Mark campaign as active
        campaign.status = CampaignStatus.ACTIVE
        campaign.started_at = timezone.now()
        campaign.save()
        
        tenant = campaign.tenant
        
        # Get scheduled messages (recipients)
        scheduled_messages = ScheduledMessage.objects.filter(
            campaign=campaign,
            status='PENDING'
        ).select_related('contact')
        
        total = scheduled_messages.count()
        sent = 0
        failed = 0
        
        for scheduled in scheduled_messages:
            try:
                contact = scheduled.contact
                
                # Get or create conversation
                conversation, _ = Conversation.objects.get_or_create(
                    contact=contact,
                    defaults={'status': ConversationStatus.ACTIVE}
                )
                
                # Create message
                message = Message.objects.create(
                    conversation=conversation,
                    direction=MessageDirection.OUTBOUND,
                    message_type=MessageType.TEMPLATE if campaign.template_name else MessageType.TEXT,
                    status=MessageStatus.PENDING,
                    content=campaign.message_content or '',
                    payload={
                        'template_name': campaign.template_name,
                        'template_params': campaign.template_params or [],
                        'header_image': campaign.header_image,
                        'campaign_id': str(campaign.id),
                    },
                    media_url=campaign.header_image or ''
                )
                
                # Send message
                success = send_message(message)
                
                # Update scheduled message status
                scheduled.status = 'SENT' if success else 'FAILED'
                scheduled.processed_at = timezone.now()
                scheduled.save()
                
                # Create message result
                MessageResult.objects.create(
                    campaign=campaign,
                    contact=contact,
                    message=message,
                    status='SENT' if success else 'FAILED',
                    wa_message_id=message.wa_message_id,
                    error_message=message.error_message if not success else ''
                )
                
                if success:
                    sent += 1
                else:
                    failed += 1
                
                # Rate limiting - small delay between messages
                import time
                time.sleep(0.2)
                
            except Exception as e:
                logger.error(f"Error sending to {scheduled.contact_id}: {e}")
                failed += 1
                scheduled.status = 'FAILED'
                scheduled.save()
        
        # Update campaign status
        campaign.completed_at = timezone.now()
        if failed == 0:
            campaign.status = CampaignStatus.COMPLETED
        else:
            campaign.status = CampaignStatus.COMPLETED if sent > 0 else CampaignStatus.CANCELLED
        campaign.save()
        
        logger.info(f"Campaign {campaign_id} completed: {sent} sent, {failed} failed")
        
        return {
            'status': 'completed',
            'campaign_id': str(campaign_id),
            'total': total,
            'sent': sent,
            'failed': failed
        }
        
    except Campaign.DoesNotExist:
        logger.error(f"Campaign {campaign_id} not found")
        return {'status': 'error', 'error': 'Campaign not found'}
    except Exception as e:
        logger.exception(f"Error processing campaign {campaign_id}: {e}")
        return {'status': 'error', 'error': str(e)}


@shared_task
def process_scheduled_campaigns():
    """
    Periodic task to check and start scheduled campaigns.
    Runs every minute via Celery Beat.
    """
    from campaigns.models import Campaign, CampaignStatus
    
    now = timezone.now()
    
    # Find campaigns that are scheduled and due
    due_campaigns = Campaign.objects.filter(
        status=CampaignStatus.SCHEDULED,
        scheduled_at__lte=now
    )
    
    count = 0
    for campaign in due_campaigns:
        # Queue the campaign for sending
        send_campaign_messages_task.delay(str(campaign.id))
        count += 1
        logger.info(f"Queued campaign {campaign.id} for sending")
    
    return {'processed': count, 'timestamp': now.isoformat()}


@shared_task
def update_message_statuses():
    """
    Periodic task to check for stale pending messages.
    Marks messages as failed if stuck in pending for too long.
    """
    from messaging.models import Message, MessageStatus
    
    stale_threshold = timezone.now() - timedelta(hours=24)
    
    stale_messages = Message.objects.filter(
        status=MessageStatus.PENDING,
        created_at__lt=stale_threshold
    )
    
    count = stale_messages.update(
        status=MessageStatus.FAILED,
        error_code='TIMEOUT',
        error_message='Message stuck in pending for over 24 hours'
    )
    
    logger.info(f"Marked {count} stale messages as failed")
    return {'marked_failed': count}
