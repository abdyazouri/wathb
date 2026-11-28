"""Admin publishes a job on behalf of its business: ADMIN only, same rules as the business's own publish,
only the confirmed version, and an audit entry naming the business."""
import datetime

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Role, User
from audit.models import AuditEvent
from jobs.models import JobListing, JobListingStatus
from jobs.tests.test_c5_cancel import make_business, make_job, make_worker


class AdminJobPublishTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user("+970599600001", "Admin-Pass-123", role=Role.ADMIN, is_verified=True)
        self.biz_user, self.bp = make_business("+970599600002")
        self.job = make_job(self.bp, status=JobListingStatus.DRAFT, days_ahead=3)

    def publish(self, user=None, **body):
        self.client.force_authenticate(user=user or self.admin)
        payload = {"expected_version": self.job.version, "reason": "طلب صاحب المنشأة", **body}
        return self.client.post(reverse("admin-job-publish", args=[self.job.pk]), payload, format="json")

    def test_admin_publishes_a_draft_on_behalf_of_the_business(self):
        r = self.publish()
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, JobListingStatus.PUBLISHED)
        self.assertIsNotNone(self.job.published_at)
        event = AuditEvent.objects.get(action="job_published_by_admin", object_id=str(self.job.pk))
        self.assertEqual(event.actor, self.admin)
        self.assertEqual(event.details["on_behalf_of_business"], self.bp.pk)
        self.assertEqual(event.details["previous_status"], JobListingStatus.DRAFT)
        self.assertEqual(event.details["reason"], "طلب صاحب المنشأة")
        # Workers now see it.
        self.client.force_authenticate(user=make_worker("+970599600003"))
        ids = [j["id"] for j in self.client.get(reverse("job-list")).data["results"]]
        self.assertIn(str(self.job.pk), ids)

    def test_only_admins(self):
        for user in (self.biz_user, make_worker("+970599600004")):
            self.assertEqual(self.publish(user=user).status_code, status.HTTP_403_FORBIDDEN, user.role)
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.post(reverse("admin-job-publish", args=[self.job.pk]), {}).status_code,
                         status.HTTP_401_UNAUTHORIZED)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, JobListingStatus.DRAFT)

    def test_only_the_confirmed_version(self):
        r = self.publish(expected_version=self.job.version + 1)
        self.assertEqual(r.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(r.data["version"], self.job.version)
        self.client.force_authenticate(user=self.admin)
        missing = self.client.post(reverse("admin-job-publish", args=[self.job.pk]), {}, format="json")
        self.assertEqual(missing.status_code, status.HTTP_409_CONFLICT)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, JobListingStatus.DRAFT)
        self.assertFalse(AuditEvent.objects.filter(action="job_published_by_admin").exists())

    def test_same_rules_as_the_business_publish(self):
        self.bp.verification_status = "PENDING"
        self.bp.save(update_fields=["verification_status"])
        self.assertEqual(self.publish().status_code, status.HTTP_400_BAD_REQUEST)
        self.bp.verification_status = "APPROVED"
        self.bp.save(update_fields=["verification_status"])

        JobListing.objects.filter(pk=self.job.pk).update(is_funded=True)
        self.assertEqual(self.publish().status_code, status.HTTP_400_BAD_REQUEST)  # no funding allocation
        JobListing.objects.filter(pk=self.job.pk).update(is_funded=False)

        User.objects.filter(pk=self.biz_user.pk).update(is_active=False)
        self.assertEqual(self.publish().status_code, status.HTTP_400_BAD_REQUEST)
        User.objects.filter(pk=self.biz_user.pk).update(is_active=True)

        JobListing.objects.filter(pk=self.job.pk).update(status=JobListingStatus.CANCELLED)
        self.assertEqual(self.publish().status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(AuditEvent.objects.filter(action="job_published_by_admin").exists())

    def test_publishing_twice_is_refused(self):
        self.assertEqual(self.publish().status_code, status.HTTP_200_OK)
        self.assertEqual(self.publish().status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(AuditEvent.objects.filter(action="job_published_by_admin").count(), 1)

    def test_unknown_job(self):
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(reverse("admin-job-publish", args=["00000000-0000-0000-0000-000000000000"]),
                             {"expected_version": 1}, format="json")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)
