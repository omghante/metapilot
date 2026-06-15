"""
API views for testing the WhatsApp AI Chatbot locally.
"""
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema, OpenApiTypes
import logging

from .views import WhatsAppChatbotHandler
from .models import TenantKnowledgeEntry
from .serializers import KnowledgeEntrySerializer, KnowledgeEntryCreateSerializer
from api.permissions import IsTenantMember, IsTenantMemberOrAgencyAdmin

logger = logging.getLogger(__name__)


class ChatbotTestView(APIView):
    """
    Test endpoint for the WhatsApp AI Chatbot.
    
    POST /api/wa-chatbot/test/
    {
        "message": "Hello, how can you help me?",
        "phone": "+919876543210"  // optional
    }
    """
    permission_classes = [IsAuthenticated, IsTenantMember]
    
    @extend_schema(
        request=None, 
        responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT}
    )
    def post(self, request):
        """
        Test the WhatsApp chatbot with a simulated text message.
        """
        try:
            message = request.data.get('message', '').strip()
            phone = request.data.get('phone', '+919999999999')
            
            if not message:
                return Response(
                    {'error': 'Message is required'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get tenant from authenticated user
            tenant = getattr(request.user, 'tenant', None)
            
            # Create simulated WhatsApp message data
            msg_data = {
                'type': 'text',
                'text': {
                    'body': message
                }
            }
            
            # Initialize chatbot handler
            handler = WhatsAppChatbotHandler(tenant=tenant)
            
            # Process the message
            response = handler.process_message(phone, msg_data)
            
            return Response({
                'success': True,
                'input': message,
                'phone': phone,
                'response': response,
                'tenant': tenant.name if tenant else None
            })
            
        except Exception as e:
            logger.error(f"Chatbot test error: {e}")
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ChatbotClearHistoryView(APIView):
    """
    Clear conversation history for a phone number.
    
    POST /api/wa-chatbot/clear/
    {
        "phone": "+919876543210"
    }
    """
    permission_classes = [IsAuthenticated, IsTenantMember]
    
    @extend_schema(
        request=None, 
        responses={200: OpenApiTypes.OBJECT}
    )
    def post(self, request):
        """
        Clear conversation history for testing.
        """
        phone = request.data.get('phone', '+919999999999')
        
        from .services.conversation_manager import ConversationManager
        
        manager = ConversationManager()
        manager.clear_history(phone)
        
        return Response({
            'success': True,
            'message': f'History cleared for {phone}'
        })


class KnowledgeEntryViewSet(ModelViewSet):
    """
    CRUD ViewSet for tenant knowledge base entries.
    
    Endpoints:
    - GET    /api/wa-chatbot/knowledge/           - List entries
    - POST   /api/wa-chatbot/knowledge/           - Create entry
    - GET    /api/wa-chatbot/knowledge/{id}/      - Get entry
    - PUT    /api/wa-chatbot/knowledge/{id}/      - Update entry
    - DELETE /api/wa-chatbot/knowledge/{id}/      - Delete entry
    
    Supports ?tenant= query parameter for agency admin access.
    """
    permission_classes = [IsAuthenticated, IsTenantMemberOrAgencyAdmin]
    serializer_class = KnowledgeEntrySerializer
    
    def _get_target_tenant(self):
        """Get the target tenant - either from query param (agency) or user's tenant."""
        from tenants.models import Tenant
        from users.models import UserRole
        
        # Check for tenant query parameter (agency admin access)
        tenant_id = self.request.query_params.get('tenant')
        
        if tenant_id and self.request.user.role == UserRole.AGENCY_ADMIN:
            # Validate that the tenant belongs to the agency admin's agency
            try:
                tenant = Tenant.objects.get(id=tenant_id)
                if tenant.agency_id == self.request.user.agency_id:
                    return tenant
                logger.warning(f"Agency admin tried to access tenant {tenant_id} not in their agency")
                return None
            except Tenant.DoesNotExist:
                return None
        
        # Super admin with tenant param
        if tenant_id and self.request.user.role == UserRole.SUPER_ADMIN:
            try:
                return Tenant.objects.get(id=tenant_id)
            except Tenant.DoesNotExist:
                return None
        
        # Default to user's own tenant
        return getattr(self.request.user, 'tenant', None)
    
    def get_queryset(self):
        """Filter entries by target tenant."""
        tenant = self._get_target_tenant()
        if tenant:
            return TenantKnowledgeEntry.objects.filter(tenant=tenant)
        return TenantKnowledgeEntry.objects.none()
    
    def get_serializer_class(self):
        if self.action == 'create':
            return KnowledgeEntryCreateSerializer
        return KnowledgeEntrySerializer
    
    def perform_create(self, serializer):
        """Auto-assign tenant from target tenant."""
        tenant = self._get_target_tenant()
        if not tenant:
            raise ValueError("User must belong to a tenant to create knowledge entries")
        serializer.save(tenant=tenant)
        
        # Invalidate cached sessions for this tenant
        from .services.tenant_rag_service import TenantRAGService
        TenantRAGService().reload_tenant_sessions(str(tenant.id))
    
    def perform_update(self, serializer):
        """Invalidate cache on update."""
        serializer.save()
        tenant = serializer.instance.tenant
        
        from .services.tenant_rag_service import TenantRAGService
        TenantRAGService().reload_tenant_sessions(str(tenant.id))
    
    def perform_destroy(self, instance):
        """Invalidate cache on delete."""
        tenant = instance.tenant
        instance.delete()
        
        from .services.tenant_rag_service import TenantRAGService
        TenantRAGService().reload_tenant_sessions(str(tenant.id))
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get knowledge base statistics for the tenant."""
        tenant = self._get_target_tenant()
        if not tenant:
            return Response({'error': 'No tenant'}, status=400)
        
        total = TenantKnowledgeEntry.objects.filter(tenant=tenant).count()
        active = TenantKnowledgeEntry.objects.filter(tenant=tenant, is_active=True).count()
        
        return Response({
            'total_entries': total,
            'active_entries': active,
            'inactive_entries': total - active
        })

