"""
Chatbot service for WhatsApp marketing platform.
Implements a RAG-based model using content.json for platform-related questions.
"""
import os
import json
import logging
from typing import Optional, List
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class PlatformChatbotService:
    """
    RAG-based chatbot service that uses content.json for platform-related questions.
    """
    
    def __init__(self):
        """
        Initialize the chatbot service with content.json data.
        """
        self.content_file_path = os.path.join(os.path.dirname(__file__), 'content.json')
        self.content_data = self._load_content_data()
        
        # Load OpenRouter API key if available
        self.api_key = getattr(settings, 'OPENROUTER_API_KEY', None)
        
        # Platform-specific context for the chatbot
        self.system_prompt = """
        You are 'SnoozeScript AI', a highly intelligent, expert technical consultant for the WhatsApp Marketing Platform. 
        Your goal is to provide deep, analytical, and extremely helpful guidance to users.

        TONE & PERSONALITY:
        - Professional, expert, and proactive.
        - You don't just repeat documentation; you interpret it.
        - If a user asks for something that doesn't exist (like 'campaign slides'), explain what the platform actually does instead (e.g., 'Interactive Message Templates').
        - You have a thorough understanding of the WhatsApp Business API, Meta's policies, and marketing best practices.

        CORE KNOWLEDGE BASE:
        1. Setup: WhatsApp Business API, Meta Access Tokens, Phone ID.
        2. Messaging: Direct messages, Universal send, Media assets (Images, Videos, Documents).
        3. Automation: Campaigns, Message Templates (Buttons, Header, Body), Scheduled jobs.
        4. Management: Multi-tenant Agency/Client roles, Contact segmentation, Quotas.

        INSTRUCTIONS:
        - Use the provided 'Local Documentation Context' as your primary source of truth for platform-specific steps.
        - Supplement with your general knowledge only when the local context is missing or if the user asks for general marketing advice.
        - If you see a technical term like 'slides', compare it to platform features like 'Message Templates' or 'Carousel Messages' and advise accordingly.
        - Always aim to be more than just a search engine; be a consultant.
        """
    
    def _load_content_data(self):
        """
        Load content data from content.json file.
        """
        try:
            with open(self.content_file_path, 'r', encoding='utf-8') as file:
                return json.load(file)
        except FileNotFoundError:
            logger.error(f"Content file not found at {self.content_file_path}")
            return {}
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in content file at {self.content_file_path}")
            return {}
    
    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """
        Calculate similarity between two texts using a simple word overlap approach.
        """
        if not text1 or not text2:
            return 0.0
            
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        if len(union) == 0:
            return 0.0

        return len(intersection) / len(union)
    
    def _find_relevant_content(self, query: str) -> str:
        """
        Find the most relevant content from content.json based on the query.
        Returns the best matching content.
        """
        query_lower = query.strip().lower()
        best_match = None
        highest_score = 0.0
        
        # 1. Check in common questions
        common_questions = self.content_data.get('platform_info', {}).get('common_questions', {})
        for question_key, answer in common_questions.items():
            question_text = question_key.replace('_', ' ')
            score = self._calculate_similarity(query_lower, question_text)
            
            # Boost score for short greetings
            greetings = ['hi', 'hello', 'hey', 'hola']
            if query_lower in greetings and (question_key == 'hello' or 'hello' in question_text):
                score = 1.0
            elif query_lower == question_key or query_lower == question_text:
                score = 1.0

            if score > highest_score:
                highest_score = score
                best_match = answer
        
        # 2. Check in setup instructions
        setup = self.content_data.get('platform_info', {}).get('setup', {})
        for setup_key, setup_desc in setup.items():
            setup_text = setup_key.replace('_', ' ')
            score = self._calculate_similarity(query_lower, setup_text)
            if score > highest_score:
                highest_score = score
                best_match = setup_desc # Plain answer only

        # 3. Check in features
        features = self.content_data.get('platform_info', {}).get('features', [])
        for feature in features:
            name = feature.get('name', '')
            description = feature.get('description', '')
            score = max(self._calculate_similarity(query_lower, name), 
                        self._calculate_similarity(query_lower, description) * 0.8)
            if score > highest_score:
                highest_score = score
                best_match = description # Plain answer only
        
        # 4. Check in overview
        overview = self.content_data.get('platform_info', {}).get('overview', '')
        score = self._calculate_similarity(query_lower, overview) * 0.5
        if score > highest_score:
            highest_score = score
            best_match = overview # Plain answer only
        
        # Return best match if score is acceptable
        # Lowered threshold slightly for short words like "hi"
        if highest_score > 0.15:
            return best_match
            
        return "I don't have specific information about this topic in my knowledge base."
    
    def is_platform_question(self, message_content: str) -> bool:
        """
        Determine if a message is asking about the platform.
        """
        platform_keywords = [
            'how do', 'how to', 'what is', 'what are', 'can you', 'help me',
            'whatsapp', 'campaign', 'contact', 'template', 'message', 'api',
            'setup', 'configure', 'settings', 'user', 'admin', 'tenant',
            'agency', 'billing', 'plan', 'analytics', 'report', 'dashboard',
            'create', 'send', 'manage', 'add', 'remove', 'delete', 'update',
            'change', 'enable', 'disable', 'integrate', 'connect',
            'hello', 'hi', 'hey', 'greetings', 'support'
        ]
        
        content_lower = message_content.lower()
        return any(keyword in content_lower for keyword in platform_keywords)
    
    def get_response(self, message_content: str, tenant_name: str = "the platform") -> Optional[str]:
        """
        Get a response by first checking content.json. If no relevant info is found,
        falls back to OpenRouter AI.
        """
        try:
            # Check if this is a platform-related question
            if not self.is_platform_question(message_content):
                logger.info(f"Message '{message_content}' is not a platform question, skipping chatbot")
                return None
            
            logger.info(f"Processing platform question for tenant {tenant_name}: {message_content}")
            
            # 1. First check in content.json (Local Knowledge)
            relevant_content = self._find_relevant_content(message_content)
            
            # Check if we found a valid answer in our local documentation
            is_valid_local_answer = relevant_content and "I don't have specific information" not in relevant_content
            
            if is_valid_local_answer:
                # Found a good match in content.json, use it directly
                logger.info("Found relevant answer in local content.json")
                response = relevant_content
            elif self.api_key:
                # No good match in local content, use OpenRouter as fallback
                logger.info("Local documentation miss. Calling OpenRouter AI as fallback...")
                response = self._get_openrouter_response(message_content, tenant_name, "")
            else:
                # No match and no API key available
                response = "I found your question is about the platform, but I don't have specific information in my knowledge base."
            
            # Add support footer to all responses as requested
            final_response = f"{response}\n\nIf you need more specific help, please contact support."
            
            logger.info(f"Chatbot response generated successfully for tenant {tenant_name}")
            return final_response
            
        except Exception as e:
            logger.error(f"Error getting chatbot response: {str(e)}")
            return "I'm sorry, I'm having trouble responding to your question right now. Please try again later."
    
    def _get_openrouter_response(self, message_content: str, tenant_name: str, context: str = "") -> str:
        """
        Get a response using OpenRouter API.
        """
        try:
            import requests
            import traceback
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://snoozescript.com", # For OpenRouter rankings
                "X-Title": "SnoozeScript AI"
            }
            
            # Augmented prompt with local knowledge
            augmented_system_prompt = self.system_prompt
            if context and "I don't have specific information" not in context:
                augmented_system_prompt += f"\n\n[SNOOZESCRIPT PLATFORM CONTEXT]:\n{context}\n\nNote: If the user is asking about a specific type of message (like carousels or slides) that isn't fully detailed in the context above, explain how to use the 'Campaign' and 'Template' features mentioned to achieve their goal using your knowledge of the WhatsApp Business API."
            
            data = {
                "model": "openrouter/auto", # Guaranteed to find an endpoint
                "messages": [
                    {"role": "system", "content": augmented_system_prompt},
                    {"role": "user", "content": message_content}
                ],
                "temperature": 0.6, # Slightly higher for more creative problem solving
                "max_tokens": 1500
            }
            
            logger.info(f"Calling OpenRouter with auto-routing...")
            
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                if 'choices' in result and len(result['choices']) > 0:
                    return result['choices'][0]['message']['content'].strip()
                else:
                    logger.error(f"OpenRouter empty choices: {result}")
                    return self._context_fallback(context)
            else:
                logger.error(f"OpenRouter API error: {response.status_code} - {response.text}")
                return self._context_fallback(context)
                
        except Exception as e:
            logger.error(f"Error getting OpenRouter response: {str(e)}")
            logger.error(traceback.format_exc())
            return self._context_fallback(context)

    def _context_fallback(self, context: str) -> str:
        """Helper to handle fallback logic with clear indicators."""
        if context and "I don't have specific information" not in context:
            # We add a small note to the log to know it's a fallback
            logger.warning("AI call failed, falling back to local documentation.")
            return context
        return "I'm having trouble connecting to my AI brain, and I couldn't find a match in my offline records."
    
    def get_free_model_response(self, message_content: str, tenant_name: str = "the platform") -> Optional[str]:
        """
        Get a response using the primary approach (alias for get_response).
        """
        return self.get_response(message_content, tenant_name)
