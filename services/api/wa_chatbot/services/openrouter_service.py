"""
OpenRouter AI service for generating responses.
Supports text generation and vision-capable models for image analysis.
"""
import base64
import logging
from typing import List, Dict, Optional
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class OpenRouterService:
    """
    OpenRouter API service for AI-powered responses.
    Uses auto-routing to find available models.
    """
    
    API_URL = "https://openrouter.ai/api/v1/chat/completions"
    DEFAULT_MODEL = "openrouter/auto"
    VISION_MODEL = "openai/gpt-4o"  # Vision-capable model
    
    def __init__(self, api_key: Optional[str] = None, bot_name: str = "WhatsApp Bot"):
        """
        Initialize OpenRouter service.
        
        Args:
            api_key: OpenRouter API key (defaults to settings.OPENROUTER_API_KEY)
            bot_name: Name of the bot for system prompts
        """
        self.api_key = api_key or getattr(settings, 'OPENROUTER_API_KEY', None)
        self.bot_name = bot_name
        # Allow per-deployment model override via settings / .env
        self.text_model = getattr(settings, 'WA_CHATBOT_TEXT_MODEL', self.DEFAULT_MODEL)
        self.vision_model = getattr(settings, 'WA_CHATBOT_VISION_MODEL', self.VISION_MODEL)
        
        # System prompt for the chatbot
        self.system_prompt = f"""You are '{bot_name}', a helpful and friendly WhatsApp assistant.

GUIDELINES:
- Be concise and helpful
- Keep responses short and suitable for WhatsApp (max 2-3 paragraphs)
- Use simple language that works well on mobile
- If asked in Marathi, respond in Marathi
- If asked in English, respond in English
- Be polite and professional

If you receive context from a knowledge base, use it to provide accurate answers.
If you don't know something, say so honestly.
"""
    
    def _get_headers(self) -> dict:
        """Get request headers for OpenRouter API."""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": getattr(settings, 'SITE_URL', 'https://whatsapp-marketing.com'),
            "X-Title": self.bot_name
        }
    
    def generate_response(
        self, 
        prompt: str, 
        history: List[Dict[str, str]] = None, 
        language: str = 'english',
        context: str = ""
    ) -> str:
        """
        Generate AI response for a text prompt.
        
        Args:
            prompt: User's message
            history: Conversation history (list of {role, content} dicts)
            language: 'english' or 'marathi'
            context: Optional RAG context to include
            
        Returns:
            AI-generated response string
        """
        if not self.api_key:
            logger.error("OpenRouter API key not configured")
            return "I'm sorry, I'm not configured properly. Please contact support."
        
        # Build system prompt with context
        system_content = self.system_prompt
        if context:
            system_content += f"\n\nKNOWLEDGE BASE CONTEXT:\n{context}"
        if language == 'marathi':
            system_content += "\n\nIMPORTANT: Respond in Marathi language."
        
        # Build messages array
        messages = [{"role": "system", "content": system_content}]
        
        # Add conversation history
        if history:
            messages.extend(history)
        
        # Add current prompt
        messages.append({"role": "user", "content": prompt})
        
        try:
            response = requests.post(
                self.API_URL,
                headers=self._get_headers(),
                json={
                    "model": self.text_model,
                    "messages": messages,
                    "temperature": 0.7,
                    "max_tokens": 500  # Keep responses concise for WhatsApp
                },
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                if 'choices' in result and len(result['choices']) > 0:
                    return result['choices'][0]['message']['content'].strip()
                else:
                    logger.error(f"Empty choices in OpenRouter response: {result}")
                    return "I couldn't generate a response. Please try again."
            else:
                logger.error(f"OpenRouter API error: {response.status_code} - {response.text}")
                return "I'm having trouble responding right now. Please try again later."
                
        except requests.Timeout:
            logger.error("OpenRouter API timeout")
            return "The response is taking too long. Please try again."
        except Exception as e:
            logger.error(f"OpenRouter API error: {e}")
            return "An error occurred. Please try again later."
    
    def analyze_image(self, image_base64: str, prompt: str = "Describe this image in detail.") -> str:
        """
        Analyze an image using vision-capable model.
        
        Args:
            image_base64: Base64-encoded image data
            prompt: Question or instruction about the image
            
        Returns:
            AI-generated description/analysis
        """
        if not self.api_key:
            logger.error("OpenRouter API key not configured")
            return "Image analysis is not available."
        
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}"
                        }
                    }
                ]
            }
        ]
        
        try:
            response = requests.post(
                self.API_URL,
                headers=self._get_headers(),
                json={
                    "model": self.vision_model,
                    "messages": messages,
                    "max_tokens": 500
                },
                timeout=60  # Vision takes longer
            )
            
            if response.status_code == 200:
                result = response.json()
                if 'choices' in result and len(result['choices']) > 0:
                    return result['choices'][0]['message']['content'].strip()
            
            logger.error(f"Vision API error: {response.status_code}")
            return "Could not analyze the image."
            
        except Exception as e:
            logger.error(f"Vision API error: {e}")
            return "Error analyzing image."
    
    def transcribe_audio(self, audio_base64: str, mime_type: str = "audio/mpeg") -> str:
        """
        Transcribe audio using AI.
        
        Note: OpenRouter doesn't have direct audio transcription.
        This uses a vision model with a workaround or returns a placeholder.
        For production, consider using a dedicated transcription service.
        
        Args:
            audio_base64: Base64-encoded audio data
            mime_type: Audio MIME type
            
        Returns:
            Transcription or placeholder message
        """
        # OpenRouter doesn't support direct audio transcription
        # In production, use Whisper API or similar
        logger.warning("Audio transcription requested - not fully supported via OpenRouter")
        return "I received your voice message. Audio transcription is being processed."
