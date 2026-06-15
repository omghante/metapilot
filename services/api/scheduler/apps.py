"""
Scheduler app configuration.
"""
from django.apps import AppConfig


class SchedulerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'scheduler'
    verbose_name = 'Message Scheduler'

    def ready(self):
        """Import signals when app is ready."""
        pass
