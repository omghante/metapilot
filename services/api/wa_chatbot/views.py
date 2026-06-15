"""
WhatsApp AI Chatbot handler - main entry point for processing messages.
"""
import logging
from typing import Optional, Dict, Any
from django.conf import settings

from .services.language_detector import detect_language
from .services.rag_service import RAGService
from .services.tenant_rag_service import TenantRAGService
from .services.conversation_manager import ConversationManager
from .services.openrouter_service import OpenRouterService
from .services.media_processor import MediaProcessor
from .services.whatsapp_client import WhatsAppClient

logger = logging.getLogger(__name__)


class WhatsAppChatbotHandler:
    """
    Main handler for WhatsApp AI chatbot functionality.
    Processes incoming messages and generates AI-powered responses.
    """
    
    def __init__(self, tenant=None):
        """
        Initialize chatbot handler with all required services.
        
        Args:
            tenant: Tenant model instance for WhatsApp credentials
        """
        self.tenant = tenant
        
        # Initialize services
        bot_name = getattr(settings, 'WA_CHATBOT_BOT_NAME', 'WhatsApp Assistant')
        
        self.openrouter = OpenRouterService(bot_name=bot_name)
        self.rag_service = RAGService()  # Global fallback
        self.tenant_rag_service = TenantRAGService()  # Per-tenant with caching
        self.conversation_manager = ConversationManager()
        self.media_processor = MediaProcessor(openrouter_service=self.openrouter)
        self.whatsapp_client = WhatsAppClient(tenant=tenant)
    
    def process_message(self, from_phone: str, msg_data: Dict[str, Any]) -> Optional[str]:
        """
        Process an incoming WhatsApp message and generate a response.
        
        Args:
            from_phone: Sender's phone number
            msg_data: Raw message data from webhook
            
        Returns:
            Response text or None if no response should be sent
        """
        try:
            msg_type = msg_data.get('type', 'text').lower()
            
            # Handle different message types
            if msg_type == 'text':
                return self._handle_text_message(from_phone, msg_data)
            elif msg_type in ['image', 'sticker']:
                return self._handle_image_message(from_phone, msg_data)
            elif msg_type in ['audio', 'voice']:
                return self._handle_audio_message(from_phone, msg_data)
            elif msg_type == 'video':
                return self._handle_video_message(from_phone, msg_data)
            elif msg_type == 'document':
                return self._handle_document_message(from_phone, msg_data)
            elif msg_type == 'location':
                return self._handle_location_message(from_phone, msg_data)
            elif msg_type == 'contacts':
                return "I received your contact. How can I help you with this?"
            elif msg_type == 'reaction':
                return None  # Don't respond to reactions
            else:
                logger.warning(f"Unsupported message type: {msg_type}")
                return None
                
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return "I'm sorry, I encountered an error processing your message. Please try again."
    
    def _handle_text_message(self, from_phone: str, msg_data: Dict[str, Any]) -> str:
        """Handle text message."""
        text = msg_data.get('text', {}).get('body', '').strip()

        if not text:
            return "I received an empty message. How can I help you?"

        # Detect language
        language = detect_language(text)

        # Check for special commands
        if text.lower() in ['clear', 'reset', 'start over', 'new chat']:
            self.conversation_manager.clear_history(from_phone)
            return "Conversation cleared. How can I help you today?"

        # Get RAG context – prefer tenant-specific, fallback to global
        rag_context = ""
        if self.tenant:
            rag_context = self.tenant_rag_service.enhance_with_rag(
                tenant_id=str(self.tenant.id),
                phone=from_phone,
                query=text,
                language=language,
            )

        # If no tenant context, try global knowledge base
        if not rag_context:
            rag_context = self.rag_service.enhance_with_rag(text, language)

        # ── No knowledge context at all → return configured fallback message ──
        # This prevents the AI from hallucinating answers when no knowledge base
        # has been set up for the tenant yet.
        if not rag_context:
            fallback = getattr(
                settings,
                'WA_CHATBOT_FALLBACK_MESSAGE',
                'Thank you for your message! We have received your query and our team will get back to you shortly.',
            )
            logger.info(
                f'[Chatbot] No knowledge context for tenant '
                f'{self.tenant.name if self.tenant else "unknown"} '
                f'— sending fallback message to {from_phone}'
            )
            # Still store in history so the conversation is trackable
            self.conversation_manager.add_exchange(from_phone, text, fallback)
            return fallback

        # Knowledge context found → call AI with it
        history = self.conversation_manager.get_formatted_history(from_phone)
        response = self.openrouter.generate_response(
            prompt=text,
            history=history,
            language=language,
            context=rag_context,
        )

        # Store in conversation history
        self.conversation_manager.add_exchange(from_phone, text, response)

        return response
    
    def _handle_image_message(self, from_phone: str, msg_data: Dict[str, Any]) -> str:
        """Handle image/sticker message."""
        msg_type = msg_data.get('type', 'image')
        media_data = msg_data.get(msg_type, {})
        media_id = media_data.get('id')
        
        if not media_id:
            return "I couldn't receive the image properly. Please try sending again."
        
        # Get caption if any
        caption = media_data.get('caption', '')
        
        # Download media
        media_bytes, mime_type = self.whatsapp_client.download_media(media_id)
        
        if media_bytes is None:
            return f"I couldn't download the image: {mime_type}"
        
        # Analyze image
        analysis = self.media_processor.process_image(media_bytes, mime_type)
        
        # If there's a caption, treat it as a question about the image
        if caption:
            prompt = f"About this image: {analysis}\n\nUser's question: {caption}"
            language = detect_language(caption)
            response = self.openrouter.generate_response(prompt=prompt, language=language)
            return response
        
        return analysis
    
    def _handle_audio_message(self, from_phone: str, msg_data: Dict[str, Any]) -> str:
        """Handle audio/voice message."""
        msg_type = msg_data.get('type', 'audio')
        media_data = msg_data.get(msg_type, {})
        media_id = media_data.get('id')
        
        if not media_id:
            return "I couldn't receive the audio properly. Please try sending again."
        
        # Download media
        media_bytes, mime_type = self.whatsapp_client.download_media(media_id)
        
        if media_bytes is None:
            return f"I couldn't download the audio: {mime_type}"
        
        # Process audio
        return self.media_processor.process_audio(media_bytes, mime_type)
    
    def _handle_video_message(self, from_phone: str, msg_data: Dict[str, Any]) -> str:
        """Handle video message."""
        media_data = msg_data.get('video', {})
        media_id = media_data.get('id')
        
        if not media_id:
            return "I couldn't receive the video properly. Please try sending again."
        
        # Download media
        media_bytes, mime_type = self.whatsapp_client.download_media(media_id)
        
        if media_bytes is None:
            return f"I couldn't download the video: {mime_type}"
        
        caption = media_data.get('caption', '')
        
        # Process video
        result = self.media_processor.process_video(media_bytes, mime_type)
        
        if caption:
            return f"{result}\n\nRegarding your message: {caption}"
        
        return result
    
    def _handle_document_message(self, from_phone: str, msg_data: Dict[str, Any]) -> str:
        """Handle document message (PDF, etc.)."""
        media_data = msg_data.get('document', {})
        media_id = media_data.get('id')
        mime_type = media_data.get('mime_type', 'application/pdf')
        filename = media_data.get('filename', 'document')
        
        if not media_id:
            return "I couldn't receive the document properly. Please try sending again."
        
        # Download media
        media_bytes, actual_mime = self.whatsapp_client.download_media(media_id)
        
        if media_bytes is None:
            return f"I couldn't download the document: {actual_mime}"
        
        # Use the actual MIME type from download if available
        use_mime = actual_mime if actual_mime != 'application/octet-stream' else mime_type
        
        # Process document
        result = self.media_processor.process_media(media_bytes, use_mime)
        
        caption = media_data.get('caption', '')
        if caption:
            # If there's a caption, generate a response about the document
            prompt = f"Document content:\n{result}\n\nUser's question: {caption}"
            language = detect_language(caption)
            return self.openrouter.generate_response(prompt=prompt, language=language)
        
        return result
    
    def _handle_location_message(self, from_phone: str, msg_data: Dict[str, Any]) -> str:
        """Handle location message."""
        location = msg_data.get('location', {})
        lat = location.get('latitude')
        lng = location.get('longitude')
        name = location.get('name', '')
        address = location.get('address', '')
        
        if lat and lng:
            location_info = f"Location: {lat}, {lng}"
            if name:
                location_info = f"Location: {name}"
            if address:
                location_info += f" ({address})"
            
            return f"I received your location: {location_info}. How can I help you with this location?"
        
        return "I received a location but couldn't read the coordinates."
    
    def send_reply(self, to_phone: str, message: str) -> dict:
        """
        Send a reply message.
        
        Args:
            to_phone: Recipient phone number
            message: Message text
            
        Returns:
            WhatsApp API response
        """
        return self.whatsapp_client.send_message(to_phone, message)
