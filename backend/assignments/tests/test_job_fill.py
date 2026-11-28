"""A job is FILLED only while accepted tasks cover num_workers_needed, and reopens when a cancellation frees a place."""
import datetime

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.deletion import delete_account
from accounts.models import Role, User
from assignments.models import Assignment, AssignmentStatus
from jobs.models import ApplicationStatus, JobApplication, JobListingStatus
from jobs.tests.test_c5_cancel import make_business, make_job, make_worker


class JobFillStatusTests(APITestCase):
    def setUp(self):
        self.biz_user, self.bp = make_business("+970599333001")
        self.admin = User.objects.create_user("+970599333009", "Admin-Pass-123", role=Role.ADMIN)
        self.workers = [make_worker(f"+97059933300{i}") for i in range(2, 6)]

    def offer(self, job, worker):
        app = JobApplication.objects.create(job=job, worker=worker, status=ApplicationStatus.OFFERED)
        return Assignment.objects.create(job=job, worker=worker, application=app, terms_snapshot={},
                                         status=AssignmentStatus.OFFERED)

    def accept(self, task):
        self.client.force_authenticate(user=task.worker)
        return self.client.post(reverse("assignment-accept", args=[task.pk]))

    def cancel(self, task, user):
        self.client.force_authenticate(user=user)
        return self.client.post(reverse("assignment-cancel", args=[task.pk]), {"reason": "سبب"})

    def status_of(self, job):
        job.refresh_from_db()
        return job.status

    def test_job_reopens_when_the_worker_the_business_or_an_admin_cancels(self):
        for canceller in ("worker", "business", "admin"):
            job = make_job(self.bp, days_ahead=3)
            task = self.offer(job, self.workers[0])
            self.assertEqual(self.accept(task).status_code, status.HTTP_200_OK)
            self.assertEqual(self.status_of(job), JobListingStatus.FILLED)
            user = {"worker": task.worker, "business": self.biz_user, "admin": self.admin}[canceller]
            self.assertEqual(self.cancel(task, user).status_code, status.HTTP_200_OK, canceller)
            self.assertEqual(self.status_of(job), JobListingStatus.PUBLISHED, canceller)

    def test_a_job_needing_two_workers_fills_on_the_second_acceptance(self):
        job = make_job(self.bp, days_ahead=3)
        job.num_workers_needed = 2
        job.save(update_fields=["num_workers_needed"])
        first, second = self.offer(job, self.workers[0]), self.offer(job, self.workers[1])
        self.accept(first)
        self.assertEqual(self.status_of(job), JobListingStatus.PUBLISHED)  # still open for applicants
        self.accept(second)
        self.assertEqual(self.status_of(job), JobListingStatus.FILLED)
        self.cancel(first, first.worker)
        self.assertEqual(self.status_of(job), JobListingStatus.PUBLISHED)

    def test_no_acceptance_beyond_the_places(self):
        job = make_job(self.bp, days_ahead=3)
        first, late = self.offer(job, self.workers[0]), self.offer(job, self.workers[1])
        self.accept(first)
        r = self.accept(late)
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        late.refresh_from_db()
        self.assertEqual(late.status, AssignmentStatus.OFFERED)
        self.assertEqual(job.places_taken(), 1)

    def test_withdrawing_an_unaccepted_offer_does_not_reopen_a_full_job(self):
        job = make_job(self.bp, days_ahead=3)
        accepted, extra = self.offer(job, self.workers[0]), self.offer(job, self.workers[1])
        self.accept(accepted)
        self.assertEqual(self.cancel(extra, self.biz_user).status_code, status.HTTP_200_OK)
        self.assertEqual(self.status_of(job), JobListingStatus.FILLED)

    def test_a_cancelled_job_stays_cancelled(self):
        job = make_job(self.bp, days_ahead=3)
        task = self.offer(job, self.workers[0])
        self.accept(task)
        job.status = JobListingStatus.CANCELLED
        job.save(update_fields=["status"])
        self.cancel(task, self.admin)
        self.assertEqual(self.status_of(job), JobListingStatus.CANCELLED)

    def test_job_is_not_reopened_after_its_work_day(self):
        job = make_job(self.bp, days_ahead=3)
        task = self.offer(job, self.workers[0])
        self.accept(task)
        job.work_date = datetime.date.today() - datetime.timedelta(days=1)
        job.save(update_fields=["work_date"])
        Assignment.objects.filter(pk=task.pk).update(status=AssignmentStatus.CANCELLED)
        job.refresh_fill_status()
        self.assertEqual(self.status_of(job), JobListingStatus.FILLED)

    def test_cancelling_then_deleting_the_business_cancels_the_job(self):
        """The path that left the test jobs FILLED: tasks cancelled, then the business deleted."""
        job = make_job(self.bp, days_ahead=3)
        task = self.offer(job, self.workers[0])
        self.accept(task)
        self.cancel(task, self.biz_user)
        self.assertEqual(delete_account(self.biz_user), [])
        self.assertEqual(self.status_of(job), JobListingStatus.CANCELLED)
