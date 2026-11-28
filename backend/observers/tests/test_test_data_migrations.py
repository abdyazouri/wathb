"""The two data migrations touch only the confirmed test records."""
import importlib
import uuid

from django.apps import apps as django_apps
from django.test import TestCase

from accounts.models import BusinessProfile, Role, User
from assignments.models import Assignment, AssignmentStatus
from jobs.models import ApplicationStatus, JobApplication, JobListing, JobListingStatus
from jobs.tests.test_c5_cancel import make_job, make_worker

mark_businesses = importlib.import_module("accounts.migrations.0009_mark_trial_test_businesses")
cancel_jobs = importlib.import_module("jobs.migrations.0010_cancel_filled_test_jobs")


def business(pk, name, phone):
    user = User.objects.create_user(phone, "Biz-Pass-123", role=Role.BUSINESS)
    return BusinessProfile.objects.create(pk=pk, user=user, legal_name=name, contact_name="م",
                                          contact_phone="0599444009", verification_status="APPROVED")


class TestDataMigrationTests(TestCase):
    def test_marks_ids_1_2_3_only_when_they_are_the_test_businesses(self):
        business(1, "[تجريبي] مخبز النور", "+970599444001")
        business(2, "منشأة حقيقية", "+970599444002")  # ID 2 is real here: never marked
        business(4, "[تجريبي] أخرى", "+970599444004")  # not in the confirmed list
        mark_businesses.mark(django_apps, None)
        marked = set(BusinessProfile.objects.filter(is_test=True).values_list("pk", flat=True))
        self.assertEqual(marked, {1})

    def test_cancels_the_two_filled_jobs_only_when_no_task_holds_a_place(self):
        bp = business(10, "[تجريبي] مخبز النور", "+970599444010")
        stuck = make_job(bp, status=JobListingStatus.FILLED)
        JobListing.objects.filter(pk=stuck.pk).update(id=cancel_jobs.JOB_IDS[0])
        busy = make_job(bp, status=JobListingStatus.FILLED)
        JobListing.objects.filter(pk=busy.pk).update(id=cancel_jobs.JOB_IDS[1])
        busy = JobListing.objects.get(pk=cancel_jobs.JOB_IDS[1])
        worker = make_worker("+970599444011")
        app = JobApplication.objects.create(job=busy, worker=worker, status=ApplicationStatus.ACCEPTED)
        Assignment.objects.create(job=busy, worker=worker, application=app, terms_snapshot={},
                                  status=AssignmentStatus.ACCEPTED)
        other = make_job(bp, status=JobListingStatus.FILLED)  # same state, not in the list
        cancel_jobs.cancel(django_apps, None)
        statuses = dict(JobListing.objects.values_list("pk", "status"))
        self.assertEqual(statuses[cancel_jobs.JOB_IDS[0]], JobListingStatus.CANCELLED)
        self.assertEqual(statuses[cancel_jobs.JOB_IDS[1]], JobListingStatus.FILLED)
        self.assertEqual(statuses[other.pk], JobListingStatus.FILLED)
        self.assertIn("التجريبية", JobListing.objects.get(pk=cancel_jobs.JOB_IDS[0]).cancellation_reason)
        self.assertIsInstance(cancel_jobs.JOB_IDS[0], uuid.UUID)
