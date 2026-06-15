"""
Unit tests for scheduler service.
"""
from django.test import TransactionTestCase
from django.utils import timezone
from datetime import timedelta

from scheduler.models import SchedulerJob, SchedulerJobRecipient, SchedulerJobStatus, RecipientStatus
from scheduler.services.scheduler_service import SchedulerService


class SchedulerServiceTestCase(TransactionTestCase):
    """Test cases for SchedulerService."""

    def setUp(self):
        """Set up test data."""
        # Create test tenant
        from tenants.models import Tenant
        self.tenant = Tenant.objects.create(
            name='Test Tenant',
            status='ACTIVE'
        )

        self.service = SchedulerService()

    def _create_job(self, scheduled_time=None, status=SchedulerJobStatus.PENDING):
        """Helper to create a test job."""
        if scheduled_time is None:
            scheduled_time = timezone.now() - timedelta(minutes=1)

        job = SchedulerJob.objects.create(
            tenant=self.tenant,
            template_name='test_template',
            scheduled_time=scheduled_time,
            status=status
        )
        return job

    def test_fetch_due_jobs_returns_pending_jobs(self):
        """Test that fetch_due_jobs returns pending jobs with past scheduled time."""
        # Create a due job
        job = self._create_job()

        # Fetch due jobs
        job_ids = self.service.fetch_due_jobs()

        self.assertEqual(len(job_ids), 1)
        self.assertEqual(job_ids[0], str(job.id))

        # Job should be marked as processing
        job.refresh_from_db()
        self.assertEqual(job.status, SchedulerJobStatus.PROCESSING)

    def test_fetch_due_jobs_skips_future_jobs(self):
        """Test that jobs scheduled in the future are skipped."""
        # Create a future job
        future_time = timezone.now() + timedelta(hours=1)
        self._create_job(scheduled_time=future_time)

        # Fetch due jobs
        job_ids = self.service.fetch_due_jobs()

        self.assertEqual(len(job_ids), 0)

    def test_fetch_due_jobs_includes_retry_eligible(self):
        """Test that failed jobs with next_retry_at in the past are included."""
        # Create a failed job with retry scheduled
        job = self._create_job(status=SchedulerJobStatus.FAILED)
        job.retry_count = 1
        job.max_retries = 3
        job.next_retry_at = timezone.now() - timedelta(minutes=1)
        job.save()

        # Fetch due jobs
        job_ids = self.service.fetch_due_jobs()

        self.assertEqual(len(job_ids), 1)
        self.assertEqual(job_ids[0], str(job.id))

    def test_fetch_due_jobs_skips_max_retries_exceeded(self):
        """Test that jobs with max retries exceeded are skipped."""
        # Create a failed job with max retries exceeded
        job = self._create_job(status=SchedulerJobStatus.FAILED)
        job.retry_count = 3
        job.max_retries = 3
        job.next_retry_at = timezone.now() - timedelta(minutes=1)
        job.save()

        # Fetch due jobs
        job_ids = self.service.fetch_due_jobs()

        self.assertEqual(len(job_ids), 0)

    def test_create_job_with_recipients(self):
        """Test creating a job with recipients."""
        scheduled_time = timezone.now() + timedelta(hours=1)
        recipients = [
            {'phone_number': '919876543210', 'contact_name': 'Test User 1'},
            {'phone_number': '919876543211', 'contact_name': 'Test User 2'},
        ]

        job = self.service.create_job(
            tenant=self.tenant,
            template_name='test_template',
            scheduled_time=scheduled_time,
            recipients=recipients
        )

        self.assertIsNotNone(job.id)
        self.assertEqual(job.total_recipients, 2)
        self.assertEqual(job.recipients.count(), 2)

    def test_update_recipient_result_success(self):
        """Test updating recipient with success result."""
        job = self._create_job()
        recipient = SchedulerJobRecipient.objects.create(
            job=job,
            phone_number='919876543210'
        )

        self.service.update_recipient_result(
            recipient=recipient,
            success=True,
            message_id='wamid.xyz123'
        )

        recipient.refresh_from_db()
        self.assertEqual(recipient.status, RecipientStatus.SENT)
        self.assertEqual(recipient.whatsapp_message_id, 'wamid.xyz123')
        self.assertIsNotNone(recipient.sent_at)

    def test_update_recipient_result_failure(self):
        """Test updating recipient with failure result."""
        job = self._create_job()
        recipient = SchedulerJobRecipient.objects.create(
            job=job,
            phone_number='919876543210'
        )

        self.service.update_recipient_result(
            recipient=recipient,
            success=False,
            error_code='131031',
            error_message='Recipient phone number not in allowed list'
        )

        recipient.refresh_from_db()
        self.assertEqual(recipient.status, RecipientStatus.FAILED)
        self.assertEqual(recipient.error_code, '131031')

    def test_update_job_completion_all_sent(self):
        """Test job completion when all recipients sent."""
        job = self._create_job()
        job.total_recipients = 2
        job.save()

        SchedulerJobRecipient.objects.create(
            job=job, phone_number='919876543210', status=RecipientStatus.SENT
        )
        SchedulerJobRecipient.objects.create(
            job=job, phone_number='919876543211', status=RecipientStatus.SENT
        )

        self.service.update_job_completion(str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.status, SchedulerJobStatus.COMPLETED)
        self.assertEqual(job.sent_count, 2)
        self.assertEqual(job.failed_count, 0)

    def test_update_job_completion_partial_failure(self):
        """Test job completion with partial failure."""
        job = self._create_job()
        job.total_recipients = 2
        job.save()

        SchedulerJobRecipient.objects.create(
            job=job, phone_number='919876543210', status=RecipientStatus.SENT
        )
        SchedulerJobRecipient.objects.create(
            job=job, phone_number='919876543211', status=RecipientStatus.FAILED
        )

        self.service.update_job_completion(str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.status, SchedulerJobStatus.PARTIAL_FAILURE)
        self.assertEqual(job.sent_count, 1)
        self.assertEqual(job.failed_count, 1)

    def test_cleanup_stale_jobs(self):
        """Test cleanup of stale processing jobs."""
        # Create a stale job (processing for too long)
        stale_job = self._create_job(status=SchedulerJobStatus.PROCESSING)
        stale_job.processing_started_at = timezone.now() - timedelta(minutes=15)
        stale_job.max_retries = 3
        stale_job.save()

        reset_count = self.service.cleanup_stale_jobs(stale_minutes=10)

        self.assertEqual(reset_count, 1)
        stale_job.refresh_from_db()
        self.assertEqual(stale_job.status, SchedulerJobStatus.FAILED)
        self.assertEqual(stale_job.retry_count, 1)
        self.assertIsNotNone(stale_job.next_retry_at)
