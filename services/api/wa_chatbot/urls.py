"""
URL configuration for wa_chatbot app.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api_views import ChatbotClearHistoryView, KnowledgeEntryViewSet
from .webhook_views import TenantWebhookView

app_name = 'wa_chatbot'

# Router for ViewSets
router = DefaultRouter()
router.register(r'knowledge', KnowledgeEntryViewSet, basename='knowledge')

urlpatterns = [
    # Per-tenant webhook endpoint for Meta WhatsApp
    path('webhook/<uuid:tenant_id>/', TenantWebhookView.as_view(), name='tenant-webhook'),
    # Clear conversation history
    path('clear/', ChatbotClearHistoryView.as_view(), name='clear-history'),
    # Knowledge base CRUD
    path('', include(router.urls)),
]

