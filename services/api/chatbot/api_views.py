"""
Chatbot API views for testing and direct interaction.
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
import logging

from chatbot.service import PlatformChatbotService
from api.permissions import IsTenantMember
from drf_spectacular.utils import extend_schema, OpenApiTypes

logger = logging.getLogger(__name__)


class ChatbotTestView(APIView):
    """
    API view to test the chatbot functionality directly.
    
    POST /api/chatbot/test/
    {
        "message": "How do I create a new campaign?",
        "tenant_name": "My Business"
    }
    """
    permission_classes = [IsAuthenticated, IsTenantMember]
    
    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT, 500: OpenApiTypes.OBJECT})
    def post(self, request):
        """
        Test the chatbot with a custom message.
        """
        try:
            message = request.data.get('message', '').strip()
            tenant_name = request.data.get('tenant_name')
            if not tenant_name:
                if hasattr(request.user, 'tenant') and request.user.tenant:
                    tenant_name = request.user.tenant.name
                else:
                    tenant_name = "the platform"
            
            if not message:
                return Response(
                    {'error': 'Message is required'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Initialize the chatbot service
            chatbot = PlatformChatbotService()
            
            # Get response from the chatbot
            response = chatbot.get_free_model_response(message, tenant_name)
            
            if response:
                return Response({
                    'success': True,
                    'question': message,
                    'answer': response,
                    'tenant_name': tenant_name
                })
            else:
                return Response({
                    'success': False,
                    'question': message,
                    'answer': 'The message was not identified as a platform-related question.',
                    'tenant_name': tenant_name
                })
                
        except Exception as e:
            logger.error(f"Error in chatbot test view: {e}")
            return Response(
                {'error': 'An error occurred while processing your request'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ChatbotQuestionCheckView(APIView):
    """
    API view to check if a message is a platform-related question.
    
    POST /api/chatbot/check/
    {
        "message": "How do I create a new campaign?"
    }
    """
    permission_classes = [IsAuthenticated, IsTenantMember]
    
    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT, 400: OpenApiTypes.OBJECT, 500: OpenApiTypes.OBJECT})
    def post(self, request):
        """
        Check if a message is a platform-related question.
        """
        try:
            message = request.data.get('message', '').strip()
            
            if not message:
                return Response(
                    {'error': 'Message is required'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Initialize the chatbot service
            chatbot = PlatformChatbotService()
            
            # Check if it's a platform question
            is_platform_question = chatbot.is_platform_question(message)
            
            return Response({
                'message': message,
                'is_platform_question': is_platform_question
            })
                
        except Exception as e:
            logger.error(f"Error in chatbot question check view: {e}")
            return Response(
                {'error': 'An error occurred while processing your request'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
