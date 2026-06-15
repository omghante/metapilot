"""
Conversation history manager using Django cache.
"""
import logging
from typing import List, Dict
from django.core.cache import cache

logger = logging.getLogger(__name__)


class ConversationManager:
    """
    Manages per-user conversation history using Django cache.
    Stores conversation in OpenAI-compatible format for use with OpenRouter.
    """
    
    MAX_HISTORY = 15  # Maximum number of message pairs to keep
    CACHE_TTL = 3600  # 1 hour TTL for conversation history
    CACHE_KEY_PREFIX = 'wa_chatbot_history_'
    
    def _get_cache_key(self, phone_number: str) -> str:
        """Generate cache key for phone number."""
        # Normalize phone number (remove spaces, special chars)
        normalized = ''.join(c for c in phone_number if c.isdigit())
        return f"{self.CACHE_KEY_PREFIX}{normalized}"
    
    def get_history(self, phone_number: str) -> List[Dict[str, str]]:
        """
        Get conversation history for a phone number.
        
        Args:
            phone_number: WhatsApp phone number
            
        Returns:
            List of message dicts with 'role' and 'content' keys
        """
        cache_key = self._get_cache_key(phone_number)
        history = cache.get(cache_key)
        
        if history is None:
            return []
        
        return history
    
    def add_message(self, phone_number: str, role: str, content: str):
        """
        Add a message to conversation history.
        
        Args:
            phone_number: WhatsApp phone number
            role: 'user' or 'assistant'
            content: Message content
        """
        cache_key = self._get_cache_key(phone_number)
        history = self.get_history(phone_number)
        
        # Add new message
        history.append({
            'role': role,
            'content': content
        })
        
        # Trim to max history (keep most recent)
        # Each exchange is 2 messages (user + assistant)
        max_messages = self.MAX_HISTORY * 2
        if len(history) > max_messages:
            history = history[-max_messages:]
        
        # Save back to cache
        cache.set(cache_key, history, self.CACHE_TTL)
        logger.debug(f"Added message to history for {phone_number}, total: {len(history)}")
    
    def add_exchange(self, phone_number: str, user_message: str, assistant_response: str):
        """
        Add a complete exchange (user message + assistant response).
        
        Args:
            phone_number: WhatsApp phone number
            user_message: User's message
            assistant_response: Bot's response
        """
        self.add_message(phone_number, 'user', user_message)
        self.add_message(phone_number, 'assistant', assistant_response)
    
    def clear_history(self, phone_number: str):
        """
        Clear conversation history for a phone number.
        
        Args:
            phone_number: WhatsApp phone number
        """
        cache_key = self._get_cache_key(phone_number)
        cache.delete(cache_key)
        logger.info(f"Cleared conversation history for {phone_number}")
    
    def get_formatted_history(self, phone_number: str) -> List[Dict[str, str]]:
        """
        Get history formatted for OpenRouter API.
        
        Args:
            phone_number: WhatsApp phone number
            
        Returns:
            List of message dicts ready for API consumption
        """
        return self.get_history(phone_number)
