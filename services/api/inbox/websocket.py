"""
Inbox WebSocket Consumer & Event Emitters.

Architecture
------------
- Each tenant gets its own isolated channel group:  inbox_{tenant_id}
- Frontend connects to: ws://<host>/ws/inbox/{tenant_id}/
- The JWT token must be passed as a query parameter ?token=<jwt>

Channel events
--------------
  new_message    → a new message arrived in any conversation of the tenant
  status_update  → delivery/read status changed on an outbound message
  conversation_update → last_message snapshot update for inbox list refresh

Security
--------
- JWT validated on connect; connection rejected if invalid or tenant mismatch
- Tenant isolation: each consumer only joins its own group
"""
import json
import logging

from asgiref.sync import async_to_sync
from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)


def _group_name(tenant_id: str) -> str:
    """Return the tenant-scoped channel group name."""
    return f'inbox_{tenant_id}'


# ---------------------------------------------------------------------------
# WebSocket Consumer
# ---------------------------------------------------------------------------

class InboxConsumer(AsyncWebsocketConsumer):
    """
    Per-tenant inbox WebSocket consumer.

    URL: /ws/inbox/{tenant_id}/
    Auth: ?token=<jwt_access_token>
    """

    async def connect(self):
        self.tenant_id = self.scope['url_route']['kwargs']['tenant_id']
        self.group_name = _group_name(self.tenant_id)

        # Authenticate
        if not await self._authenticate():
            await self.close(code=4001)
            return

        # Join tenant group
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info(
            f'[Inbox WS] Client connected to tenant group {self.group_name}'
        )

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name, self.channel_name
            )
        logger.info(
            f'[Inbox WS] Client disconnected from {getattr(self, "group_name", "?")} '
            f'(code={close_code})'
        )

    async def receive(self, text_data=None, bytes_data=None):
        """
        We do not accept messages from the client in the current version.
        Clients should use the REST endpoint POST /chat-inbox/messages/ to send.
        """
        pass

    # ------------------------------------------------------------------
    # Channel layer event handlers (called by emit_* helpers below)
    # ------------------------------------------------------------------

    async def inbox_new_message(self, event):
        """Relay a new_message event to the WebSocket client."""
        await self.send(text_data=json.dumps({
            'type': 'new_message',
            'data': event.get('data', {}),
        }))

    async def inbox_status_update(self, event):
        """Relay a status_update event to the WebSocket client."""
        await self.send(text_data=json.dumps({
            'type': 'status_update',
            'data': event.get('data', {}),
        }))

    async def inbox_conversation_update(self, event):
        """Relay a conversation_update event to the WebSocket client."""
        await self.send(text_data=json.dumps({
            'type': 'conversation_update',
            'data': event.get('data', {}),
        }))

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _authenticate(self) -> bool:
        """
        Validate the JWT token from the query string.
        Returns True if valid and the user belongs to (or manages) tenant_id.
        """
        from channels.db import database_sync_to_async

        query_string = self.scope.get('query_string', b'').decode()
        token = None
        for part in query_string.split('&'):
            if part.startswith('token='):
                token = part[len('token='):]
                break

        if not token:
            logger.warning(f'[Inbox WS] No token in connection to {self.tenant_id}')
            return False

        return await database_sync_to_async(self._validate_token)(token)

    def _validate_token(self, token: str) -> bool:
        """Synchronous JWT validation (run in thread pool via database_sync_to_async)."""
        try:
            from rest_framework_simplejwt.authentication import JWTAuthentication
            from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

            jwt_auth = JWTAuthentication()
            validated_token = jwt_auth.get_validated_token(token)
            user = jwt_auth.get_user(validated_token)

            if not user or not user.is_active:
                return False

            from users.models import UserRole
            # Super admin can connect to any tenant group
            if user.role == UserRole.SUPER_ADMIN:
                return True

            # Agency admins can connect to any tenant they manage
            if user.role == UserRole.AGENCY_ADMIN:
                from tenants.models import Tenant
                return Tenant.objects.filter(
                    id=self.tenant_id,
                    agency=user.agency,
                ).exists()

            # Tenant user must belong to this tenant
            return user.tenant and str(user.tenant.id) == self.tenant_id

        except Exception as exc:
            logger.warning(f'[Inbox WS] Auth failed: {exc}')
            return False


# ---------------------------------------------------------------------------
# Synchronous event emitters (safe to call from Django signal handlers)
# ---------------------------------------------------------------------------

def _get_channel_layer():
    """Return the default channel layer, or None if not configured."""
    from channels.layers import get_channel_layer
    return get_channel_layer()


def emit_new_message(tenant_id: str, message) -> None:
    """
    Emit a new_message event to all consumers in the tenant's group.

    Parameters
    ----------
    tenant_id : str  UUID of the tenant
    message   : InboxMessage instance
    """
    from .serializers import InboxMessageSerializer

    channel_layer = _get_channel_layer()
    if not channel_layer:
        logger.debug('[Inbox WS] No channel layer configured — skipping emit')
        return

    data = InboxMessageSerializer(message).data
    # Serialize UUIDs/datetimes to str for JSON safety
    for key, val in data.items():
        data[key] = str(val) if not isinstance(val, (str, int, float, bool, dict, list, type(None))) else val

    async_to_sync(channel_layer.group_send)(
        _group_name(tenant_id),
        {
            'type': 'inbox.new_message',
            'data': data,
        },
    )


def emit_status_update(tenant_id: str, meta_message_id: str, new_status: str) -> None:
    """
    Emit a status_update event when a message's delivery status changes.
    """
    channel_layer = _get_channel_layer()
    if not channel_layer:
        return

    async_to_sync(channel_layer.group_send)(
        _group_name(tenant_id),
        {
            'type': 'inbox.status_update',
            'data': {
                'meta_message_id': meta_message_id,
                'status': new_status,
            },
        },
    )


def emit_conversation_update(tenant_id: str, conversation) -> None:
    """
    Emit a conversation_update event (e.g. after last_message snapshot changes).
    """
    from .serializers import InboxConversationListSerializer

    channel_layer = _get_channel_layer()
    if not channel_layer:
        return

    data = InboxConversationListSerializer(conversation).data
    for key, val in data.items():
        data[key] = str(val) if not isinstance(val, (str, int, float, bool, dict, list, type(None))) else val

    async_to_sync(channel_layer.group_send)(
        _group_name(tenant_id),
        {
            'type': 'inbox.conversation_update',
            'data': data,
        },
    )
