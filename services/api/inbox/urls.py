"""
Inbox REST URL Configuration.

Mounted at /inbox/ in core/urls.py.

  GET  /inbox/conversations/
  GET  /inbox/conversations/{id}/
  POST /inbox/conversations/{id}/mark-read/
  GET  /inbox/conversations/{id}/messages/
  POST /inbox/messages/
"""
from django.urls import path
from .views import (
    ConversationListView,
    ConversationDetailView,
    ConversationMarkReadView,
    ConversationMessagesView,
    SendMessageView,
)

app_name = 'inbox'

urlpatterns = [
    # Conversation list
    path(
        'conversations/',
        ConversationListView.as_view(),
        name='conversation-list',
    ),
    # Conversation detail
    path(
        'conversations/<uuid:pk>/',
        ConversationDetailView.as_view(),
        name='conversation-detail',
    ),
    # Mark conversation as read
    path(
        'conversations/<uuid:pk>/mark-read/',
        ConversationMarkReadView.as_view(),
        name='conversation-mark-read',
    ),
    # Message list for conversation
    path(
        'conversations/<uuid:pk>/messages/',
        ConversationMessagesView.as_view(),
        name='conversation-messages',
    ),
    # Send outbound message
    path(
        'messages/',
        SendMessageView.as_view(),
        name='send-message',
    ),
]
