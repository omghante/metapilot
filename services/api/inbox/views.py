"""
Inbox API Views.

New endpoints — completely isolated from existing API routes:

  GET  /inbox/conversations/
  GET  /inbox/conversations/{id}/
  POST /inbox/conversations/{id}/mark-read/
  GET  /inbox/conversations/{id}/messages/
  POST /inbox/messages/

No existing views are modified.
"""
import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import InboxConversation, InboxMessage, InboxMessageDirection, InboxMessageStatus
from .serializers import (
    InboxConversationSerializer,
    InboxConversationListSerializer,
    InboxMessageSerializer,
    SendMessageSerializer,
)
from .services import InboxSendService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class InboxPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class MessagePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_tenant(request):
    """
    Resolve the tenant from the authenticated user.
    Super admins may pass ?tenant_id= to act on behalf of a tenant.
    """
    from users.models import UserRole

    user = request.user
    if user.role == UserRole.SUPER_ADMIN:
        tenant_id = request.query_params.get('tenant_id') or request.data.get('tenant_id')
        if tenant_id:
            from tenants.models import Tenant
            try:
                return Tenant.objects.get(id=tenant_id)
            except Tenant.DoesNotExist:
                raise NotFound('Tenant not found.')
        # Super admin without explicit tenant_id gets first tenant (for dev)
        raise ValidationError('Super admins must supply ?tenant_id=')

    if user.tenant is None:
        raise PermissionDenied('User has no associated tenant.')
    return user.tenant


def _get_conversation(tenant, pk):
    """Fetch an InboxConversation scoped to the given tenant or raise 404."""
    try:
        return InboxConversation.objects.get(id=pk, tenant=tenant)
    except InboxConversation.DoesNotExist:
        raise NotFound('Conversation not found.')


# ---------------------------------------------------------------------------
# GET /chat-inbox/conversations/
# ---------------------------------------------------------------------------

class ConversationListView(APIView):
    """
    List all inbox conversations for the authenticated user's tenant,
    ordered by last_message_time descending (most recent first).

    Query params:
      - search : filter by customer_phone or customer_name (case-insensitive)
      - page   : page number
      - page_size : items per page (default 20, max 100)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = _get_tenant(request)

        qs = InboxConversation.objects.filter(tenant=tenant).order_by('-last_message_time')

        search = request.query_params.get('search', '').strip()
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(customer_phone__icontains=search) |
                Q(customer_name__icontains=search)
            )

        paginator = InboxPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = InboxConversationListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


# ---------------------------------------------------------------------------
# GET /chat-inbox/conversations/{id}/
# ---------------------------------------------------------------------------

class ConversationDetailView(APIView):
    """Return a single inbox conversation."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        tenant = _get_tenant(request)
        conv = _get_conversation(tenant, pk)
        return Response(InboxConversationSerializer(conv).data)


# ---------------------------------------------------------------------------
# POST /chat-inbox/conversations/{id}/mark-read/
# ---------------------------------------------------------------------------

class ConversationMarkReadView(APIView):
    """
    Reset the unread_count to 0 for a conversation.
    Called by the frontend when an agent opens a conversation.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        tenant = _get_tenant(request)
        conv = _get_conversation(tenant, pk)
        conv.unread_count = 0
        conv.save(update_fields=['unread_count', 'updated_at'])
        return Response({'status': 'ok', 'unread_count': 0})


# ---------------------------------------------------------------------------
# GET /chat-inbox/conversations/{id}/messages/
# ---------------------------------------------------------------------------

class ConversationMessagesView(APIView):
    """
    List messages for a conversation, oldest-first (ascending created_at).
    Supports cursor-style pagination via page / page_size.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        tenant = _get_tenant(request)
        conv = _get_conversation(tenant, pk)

        qs = InboxMessage.objects.filter(conversation=conv).order_by('created_at')

        paginator = MessagePagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = InboxMessageSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


# ---------------------------------------------------------------------------
# POST /chat-inbox/messages/
# ---------------------------------------------------------------------------

class SendMessageView(APIView):
    """
    Send an outbound WhatsApp message from the inbox.

    Request body:
      {
        "conversation_id": "<uuid>",
        "type": "TEXT",
        "text": "Hello there!",
        "content_json": {}     // optional; used for non-text types
      }

    This view:
      1. Validates tenant ownership of the conversation.
      2. Delegates to InboxSendService (which calls Meta Graph API).
      3. Stores the outbound message.
      4. Emits a WebSocket event to the tenant channel.
      5. Returns the stored InboxMessage.

    Does NOT touch existing messaging.views or messaging.whatsapp_service.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        tenant = _get_tenant(request)

        serializer = SendMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Validate conversation belongs to this tenant
        conv = _get_conversation(tenant, data['conversation_id'])

        try:
            message = InboxSendService.send(
                tenant=tenant,
                conversation=conv,
                msg_type=data['type'],
                text=data.get('text', ''),
                content_json=data.get('content_json', {}),
            )
        except Exception as exc:
            logger.error(f"[Inbox] Send failed for tenant {tenant.id}: {exc}")
            return Response(
                {'error': str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            InboxMessageSerializer(message).data,
            status=status.HTTP_201_CREATED,
        )
