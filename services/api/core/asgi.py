"""
ASGI config for core project.

Extended to support Django Channels WebSocket connections for the Inbox module.
Existing HTTP handling is unchanged.
"""

import os

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

# Django ASGI application must be imported BEFORE channels imports
# to ensure app registry is populated.
from django.core.asgi import get_asgi_application  # noqa: E402
django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from inbox.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter({
    # Existing HTTP traffic routed to Django as before
    'http': django_asgi_app,
    # New WebSocket traffic for inbox real-time updates
    'websocket': AllowedHostsOriginValidator(
        AuthMiddlewareStack(
            URLRouter(websocket_urlpatterns)
        )
    ),
})
