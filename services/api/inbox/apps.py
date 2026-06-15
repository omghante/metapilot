"""
Inbox application configuration.
Extension layer for real-time WhatsApp chat inbox.
Does NOT modify existing messaging, webhooks, or WhatsApp API integration.
"""
from django.apps import AppConfig


class InboxConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'inbox'
    verbose_name = 'Inbox'

    def ready(self):
        """
        Connect the webhook listener signal when Django starts.
        Deferred so that all models are registered before signal attachment.
        """
        from . import webhook_listener  # noqa: F401
        webhook_listener._connect()

