"""
Database models for WhatsApp AI Chatbot.
"""
import uuid
from django.db import models
from tenants.models import Tenant


class TenantKnowledgeEntry(models.Model):
    """
    Per-tenant knowledge base entry for RAG system.
    Each tenant can have their own FAQ/knowledge entries.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant, 
        on_delete=models.CASCADE, 
        related_name='knowledge_entries'
    )
    keywords = models.JSONField(
        help_text="List of keywords to match, e.g. ['fee', 'price', 'cost']"
    )
    english_response = models.TextField(
        help_text="Response in English"
    )
    marathi_response = models.TextField(
        blank=True,
        default="",
        help_text="Response in Marathi (optional)"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Knowledge Entry"
        verbose_name_plural = "Knowledge Entries"
        ordering = ['-created_at']
    
    def __str__(self):
        keywords_preview = ', '.join(self.keywords[:3]) if self.keywords else 'No keywords'
        return f"{self.tenant.name}: {keywords_preview}"
