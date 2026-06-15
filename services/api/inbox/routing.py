"""
Inbox WebSocket URL Routing.

WebSocket endpoint:
  ws://<host>/ws/inbox/{tenant_id}/?token=<jwt>

Registered in core/asgi.py via URLRouter.
"""
from django.urls import path
from .websocket import InboxConsumer

websocket_urlpatterns = [
    path('ws/inbox/<str:tenant_id>/', InboxConsumer.as_asgi()),
]
