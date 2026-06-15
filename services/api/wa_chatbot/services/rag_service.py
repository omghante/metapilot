"""
RAG (Retrieval Augmented Generation) service for knowledge base lookups.
"""
import os
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class RAGService:
    """
    RAG service that retrieves relevant context from a knowledge base JSON file.
    Supports bilingual responses (English/Marathi).
    """
    
    def __init__(self, knowledge_base_path: Optional[str] = None):
        """
        Initialize RAG service with knowledge base.
        
        Args:
            knowledge_base_path: Path to knowledge_base.json file
        """
        if knowledge_base_path is None:
            knowledge_base_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), 
                'knowledge_base.json'
            )
        self.knowledge_base_path = knowledge_base_path
        self.knowledge_base = self._load_knowledge_base()
    
    def _load_knowledge_base(self) -> list:
        """Load knowledge base from JSON file."""
        try:
            with open(self.knowledge_base_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.warning(f"Knowledge base not found at {self.knowledge_base_path}")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in knowledge base: {e}")
            return []
    
    def _calculate_match_score(self, query: str, keywords: list) -> int:
        """
        Calculate match score between query and keywords.
        
        Scoring:
        - Exact match: 3 points
        - Word boundary match: 2 points
        - Partial match: 1 point
        
        Args:
            query: User query (lowercase)
            keywords: List of keywords to match against
            
        Returns:
            Integer score (higher = better match)
        """
        score = 0
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        for keyword in keywords:
            keyword_lower = keyword.lower()
            
            # Exact match (query is exactly the keyword)
            if query_lower == keyword_lower:
                score += 3
            # Word boundary match (keyword is a complete word in query)
            elif keyword_lower in query_words:
                score += 2
            # Partial match (keyword substring in query)
            elif keyword_lower in query_lower:
                score += 1
        
        return score
    
    def enhance_with_rag(self, query: str, language: str = 'english') -> str:
        """
        Find relevant context from knowledge base based on query.
        
        Args:
            query: User query
            language: 'english' or 'marathi'
            
        Returns:
            Relevant response from knowledge base, or empty string if no match
        """
        if not self.knowledge_base:
            return ""
        
        best_match = None
        highest_score = 0
        threshold = 2  # Minimum score to consider a match
        
        for entry in self.knowledge_base:
            keywords = entry.get('keywords', [])
            score = self._calculate_match_score(query, keywords)
            
            if score > highest_score:
                highest_score = score
                best_match = entry
        
        if best_match and highest_score >= threshold:
            # Return response based on language
            if language == 'marathi':
                return best_match.get('marathi_response', best_match.get('english_response', ''))
            return best_match.get('english_response', '')
        
        return ""
    
    def reload_knowledge_base(self):
        """Reload knowledge base from file (useful for hot updates)."""
        self.knowledge_base = self._load_knowledge_base()
        logger.info("Knowledge base reloaded")
