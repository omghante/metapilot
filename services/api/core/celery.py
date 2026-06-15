"""
Celery configuration for WhatsApp Marketing API.
"""
import os
from celery import Celery

# Set the default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

# Create Celery app
app = Celery('whatsapp_marketing')

# Load config from Django settings with CELERY_ prefix
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()

# Beat schedule for periodic tasks
# Using Celery Beat for scheduling (recommended for production/high-load)
app.conf.beat_schedule = {
    'scheduler-heartbeat': {
        'task': 'scheduler.tasks.scheduler_heartbeat',
        'schedule': 3.0,  # Every 3 seconds - fast pickup
        'options': {'queue': 'scheduler'}
    },
    'scheduler-cleanup': {
        'task': 'scheduler.tasks.cleanup_stale_jobs',
        'schedule': 300.0,  # Every 5 minutes
        'options': {'queue': 'scheduler'}
    },
    'sync-all-tenant-templates': {
        'task': 'templates.tasks.sync_all_tenant_templates',
        'schedule': 300.0,  # Every 5 minutes - keeps template statuses fresh
    },
}


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task to verify Celery is working."""
    print(f'Request: {self.request!r}')
