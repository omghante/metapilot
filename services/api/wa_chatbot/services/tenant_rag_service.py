"""
Tenant-aware RAG service with session-based caching.
Loads tenant knowledge on first message, caches for 10 minutes.
"""
import logging
from typing import Optional, List, Dict
from django.core.cache import cache

logger = logging.getLogger(__name__)


class TenantRAGService:
    """
    RAG service with per-tenant knowledge and session-based caching.
    
    - Loads tenant's knowledge from DB on first message
    - Caches knowledge for 10 minutes (from last message)
    - Refreshes TTL on each message
    - Expires after 10 minutes of inactivity
    """
    
    SESSION_TTL = 600  # 10 minutes
    CACHE_KEY_PREFIX = 'wa_rag_session_'
    
    def _get_cache_key(self, tenant_id: str, phone: str) -> str:
        """Generate cache key for tenant+phone session."""
        phone_normalized = ''.join(c for c in phone if c.isdigit())
        return f"{self.CACHE_KEY_PREFIX}{tenant_id}_{phone_normalized}"
    
    def _load_knowledge_from_db(self, tenant_id: str) -> List[Dict]:
        """Load knowledge entries from database for a tenant."""
        try:
            from wa_chatbot.models import TenantKnowledgeEntry

            entries = TenantKnowledgeEntry.objects.filter(
                tenant_id=tenant_id,
                is_active=True
            ).values('keywords', 'english_response', 'marathi_response')
            
            knowledge = [
                {
                    'keywords': entry['keywords'],
                    'english_response': entry['english_response'],
                    'marathi_response': entry['marathi_response']
                }
                for entry in entries
            ]
            
            logger.info(f"Loaded {len(knowledge)} knowledge entries for tenant {tenant_id}")
            return knowledge
            
        except Exception as e:
            logger.error(f"Error loading knowledge for tenant {tenant_id}: {e}")
            return []
    
    def get_or_create_session(self, tenant_id: str, phone: str) -> List[Dict]:
        """
        Get existing session or create new one.
        Loads knowledge from DB if session doesn't exist.
        
        Returns:
            List of knowledge entries for this tenant
        """
        cache_key = self._get_cache_key(tenant_id, phone)
        
        # Try to get from cache
        knowledge = cache.get(cache_key)
        
        if knowledge is None:
            # Session doesn't exist - create new one
            logger.info(f"Creating new RAG session for tenant {tenant_id}, phone {phone}")
            knowledge = self._load_knowledge_from_db(tenant_id)
            cache.set(cache_key, knowledge, self.SESSION_TTL)
        else:
            logger.debug(f"Using cached RAG session for tenant {tenant_id}, phone {phone}")
        
        return knowledge
    
    def refresh_session(self, tenant_id: str, phone: str):
        """
        Refresh session TTL to 10 minutes from now.
        Called on each message.
        """
        cache_key = self._get_cache_key(tenant_id, phone)
        knowledge = cache.get(cache_key)
        
        if knowledge is not None:
            # Refresh TTL
            cache.set(cache_key, knowledge, self.SESSION_TTL)
            logger.debug(f"Refreshed RAG session TTL for tenant {tenant_id}, phone {phone}")
    
    def clear_session(self, tenant_id: str, phone: str):
        """Manually clear a session (for testing)."""
        cache_key = self._get_cache_key(tenant_id, phone)
        cache.delete(cache_key)
        logger.info(f"Cleared RAG session for tenant {tenant_id}, phone {phone}")
    
    def _calculate_match_score(self, query: str, keywords: list) -> int:
        """
        Calculate match score between query and keywords.
        
        Scoring:
        - Exact match: 3 points
        - Word boundary match: 2 points
        - Partial match: 1 point
        """
        score = 0
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        for keyword in keywords:
            keyword_lower = keyword.lower()
            
            if query_lower == keyword_lower:
                score += 3
            elif keyword_lower in query_words:
                score += 2
            elif keyword_lower in query_lower:
                score += 1
        
        return score
    
    def enhance_with_rag(
        self, 
        tenant_id: str, 
        phone: str, 
        query: str, 
        language: str = 'english'
    ) -> str:
        """
        Find relevant context from tenant's knowledge base.
        
        Args:
            tenant_id: Tenant UUID
            phone: User's phone number
            query: User's message
            language: 'english' or 'marathi'
            
        Returns:
            Matching response or empty string
        """
        # Get or create session (loads from DB if needed)
        knowledge = self.get_or_create_session(str(tenant_id), phone)
        
        # Refresh session TTL
        self.refresh_session(str(tenant_id), phone)
        
        if not knowledge:
            return ""
        
        # Find best match
        best_match = None
        highest_score = 0
        threshold = 2  # Minimum score to consider a match
        
        for entry in knowledge:
            keywords = entry.get('keywords', [])
            score = self._calculate_match_score(query, keywords)
            
            if score > highest_score:
                highest_score = score
                best_match = entry
        
        if best_match and highest_score >= threshold:
            # Return response based on language
            if language == 'marathi' and best_match.get('marathi_response'):
                return best_match['marathi_response']
            return best_match.get('english_response', '')
        
        return ""
    
    def reload_tenant_sessions(self, tenant_id: str):
        """
        Invalidate all cached sessions for a tenant.
        Call this when tenant's knowledge base is updated.
        
        Note: This is a simple implementation. In production with Redis,
        you might want to use pattern-based key deletion.
        """
        # For now, just log - sessions will naturally expire
        # or reload on next access after 10 mins
        logger.info(f"Tenant {tenant_id} knowledge updated - sessions will reload on next access")
