"""
Management command to setup periodic tasks for Celery Beat.
Run once after deployment to configure scheduled tasks.
"""
from django.core.management.base import BaseCommand
from django_celery_beat.models import PeriodicTask, IntervalSchedule


class Command(BaseCommand):
    help = 'Setup periodic tasks for Celery Beat scheduler'

    def handle(self, *args, **options):
        self.stdout.write('Setting up periodic tasks...\n')

        # Create interval schedules
        schedule_1sec, _ = IntervalSchedule.objects.get_or_create(
            every=1,
            period=IntervalSchedule.SECONDS
        )
        self.stdout.write(f'  Created: 1 second interval')

        schedule_5min, _ = IntervalSchedule.objects.get_or_create(
            every=5,
            period=IntervalSchedule.MINUTES
        )
        self.stdout.write(f'  Created: 5 minute interval')

        # Create periodic tasks
        # 1. Scheduler Heartbeat - every 1 second (near real-time)
        task1, created = PeriodicTask.objects.update_or_create(
            name='Scheduler Heartbeat',
            defaults={
                'task': 'scheduler.tasks.scheduler_heartbeat',
                'interval': schedule_1sec,
                'enabled': True,
                'description': 'Check for due scheduled jobs and dispatch them for processing (runs every 1 second)'
            }
        )
        status = 'Created' if created else 'Updated'
        self.stdout.write(f'  {status}: Scheduler Heartbeat (every 1 sec)')

        # 2. Cleanup Stale Jobs - every 5 minutes
        task2, created = PeriodicTask.objects.update_or_create(
            name='Cleanup Stale Jobs',
            defaults={
                'task': 'scheduler.tasks.cleanup_stale_jobs',
                'interval': schedule_5min,
                'enabled': True,
                'description': 'Reset jobs stuck in processing state for too long'
            }
        )
        status = 'Created' if created else 'Updated'
        self.stdout.write(f'  {status}: Cleanup Stale Jobs (every 5 min)')

        self.stdout.write(self.style.SUCCESS('\nPeriodic tasks setup complete!'))
        self.stdout.write('\nConfigured tasks:')
        self.stdout.write('  1. Scheduler Heartbeat - runs every 1 second (near real-time)')
        self.stdout.write('  2. Cleanup Stale Jobs - runs every 5 minutes')
        self.stdout.write('\nMake sure Celery Beat is running:')
        self.stdout.write('  celery -A core beat -l info')
