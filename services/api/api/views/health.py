import time
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.conf import settings
from django.utils import timezone
from django_celery_beat.models import PeriodicTask 
import redis  # Use standard redis client
from scheduler.tasks import debug_celery_ping

class HealthCheckViewSet(viewsets.ViewSet):
    """
    System Health Check API.
    Verifies status of Redis, Celery Worker, and Celery Beat.
    """
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'], url_path='check')
    def check(self, request):
        status_report = {
            'redis': False,
            'celery_worker': False,
            'celery_beat': False,
            'details': {}
        }

        # 1. Check Redis
        try:
            # Connect using Celery broker URL or default local
            redis_url = getattr(settings, 'CELERY_BROKER_URL', 'redis://localhost:6379/0')
            conn = redis.from_url(redis_url)
            conn.ping()
            status_report['redis'] = True
        except Exception as e:
            status_report['details']['redis_error'] = str(e)

        # 2. Check Celery Worker
        try:
            # Send task with short expiry
            task = debug_celery_ping.apply_async(expires=5)
            # Wait for result (blocking for up to 5s)
            result = task.get(timeout=5)
            if result == "pong":
                status_report['celery_worker'] = True
        except Exception as e:
            status_report['details']['celery_worker_error'] = str(e)

        # 3. Check Celery Beat
        # We assume there is a periodic task named 'scheduler.tasks.scheduler_heartbeat'
        # running every 30s. We check if it ran in the last 2 minutes.
        try:
            beat_task = PeriodicTask.objects.filter(task='scheduler.tasks.scheduler_heartbeat').first()
            if beat_task and beat_task.last_run_at:
                # Check if ran recently (last 90 seconds to be safe)
                threshold = timezone.now() - timezone.timedelta(seconds=90)
                if beat_task.last_run_at >= threshold:
                    status_report['celery_beat'] = True
                else:
                    status_report['details']['celery_beat_last_run'] = str(beat_task.last_run_at)
                    status_report['details']['celery_beat_error'] = "Heartbeat stale (older than 90s)"
            else:
                status_report['details']['celery_beat_error'] = "Heartbeat task not found or never ran"
        except Exception as e:
            status_report['details']['celery_beat_error'] = str(e)

        # Overall Status
        all_systems_go = all([status_report['redis'], status_report['celery_worker'], status_report['celery_beat']])
        
        return Response(
            {
                'status': 'healthy' if all_systems_go else 'unhealthy',
                'components': status_report
            },
            status=status.HTTP_200_OK if all_systems_go else status.HTTP_503_SERVICE_UNAVAILABLE
        )
