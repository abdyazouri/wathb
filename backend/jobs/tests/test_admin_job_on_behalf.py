"""Admin creates a job on behalf of a business: ADMIN only, the business's own validation, a draft,
an audit entry and an in-app notification; publishing on behalf notifies the business too."""
import datetime

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Role, User
from audit.models import AuditEvent
from jobs.models import JobListing, JobListingStatus
from jobs.tests.test_c5_cancel import make_business, make_worker
from notifications.models import Notification, NotificationType


def job_body(**extra):
    return {
        "title": "مساعد مطبخ", "description": "تحضير وتنظيف", "location_address": "شارع الجلاء",
        "location_city": "غزة", "work_date": str(datetime.date.today() + datetime.timedelta(days=3)),
        "start_time": "08:00", "end_time": "16:00", "num_workers_needed": 2, "wage_amount": 6000,
        "wage_currency": "ILS", "wage_basis": "PER_DAY", **extra,
    }


class AdminJobOnBehalfTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user("+970599700001", "Admin-Pass-123", role=Role.ADMIN, is_verified=True)
        self.biz_user, self.bp = make_business("+970599700002")
        self.url = reverse("admin-business-jobs", args=[self.bp.pk])

    def create(self, user=None, **extra):
        self.client.force_authenticate(user=user or self.admin)
        return self.client.post(self.url, job_body(**extra), format="json")

    def test_admin_creates_a_draft_audited_and_notified(self):
        r = self.create()
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)
        job = JobListing.objects.get(pk=r.data["id"])
        self.assertEqual((job.business, job.status, job.num_workers_needed, job.wage_amount),
                         (self.bp, JobListingStatus.DRAFT, 2, 6000))
        event = AuditEvent.objects.get(action="job_created_by_admin", object_id=str(job.pk))
        self.assertEqual((event.actor, event.details["on_behalf_of_business"]), (self.admin, self.bp.pk))
        self.assertIn(f"on behalf of business {self.bp.pk}", event.details["note"])
        note = Notification.objects.get(recipient=self.biz_user, notification_type=NotificationType.JOB_CREATED_BY_ADMIN)
        self.assertEqual((note.related_model, note.related_id), ("JobListing", str(job.pk)))
        # The business sees it in its own list, as a draft.
        self.client.force_authenticate(user=self.biz_user)
        mine = self.client.get(reverse("job-list")).data["results"]
        self.assertEqual([(j["id"], j["status"]) for j in mine], [(str(job.pk), "DRAFT")])

    def test_same_validation_as_the_business(self):
        for bad in ({"wage_amount": 0}, {"end_time": "07:00"}, {"title": ""}, {"wage_currency": "USD"}):
            r = self.create(**bad)
            self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, bad)
            # The business gets the very same answer.
            self.client.force_authenticate(user=self.biz_user)
            own = self.client.post(reverse("job-list"), job_body(**bad), format="json")
            self.assertEqual(own.status_code, status.HTTP_400_BAD_REQUEST, bad)
        self.assertFalse(JobListing.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action="job_created_by_admin").exists())
        self.assertFalse(Notification.objects.exists())

    def test_unverified_or_inactive_business_is_refused(self):
        self.bp.verification_status = "PENDING"
        self.bp.save(update_fields=["verification_status"])
        self.assertEqual(self.create().status_code, status.HTTP_403_FORBIDDEN)
        self.bp.verification_status = "APPROVED"
        self.bp.save(update_fields=["verification_status"])
        User.objects.filter(pk=self.biz_user.pk).update(is_active=False)
        self.assertEqual(self.create().status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(JobListing.objects.exists())

    def test_only_admins(self):
        for user in (self.biz_user, make_worker("+970599700003")):
            self.assertEqual(self.create(user=user).status_code, status.HTTP_403_FORBIDDEN, user.role)
            self.client.force_authenticate(user=user)
            self.assertEqual(self.client.get(self.url).status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.post(self.url, job_body(), format="json").status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(JobListing.objects.exists())

    def test_list_and_publish_on_behalf_notifies_the_business(self):
        job_id = self.create().data["id"]
        self.client.force_authenticate(user=self.admin)
        listing = self.client.get(self.url)
        self.assertEqual([(j["id"], j["status"]) for j in listing.data], [(job_id, "DRAFT")])
        version = listing.data[0]["version"]
        r = self.client.post(reverse("admin-job-publish", args=[job_id]), {"expected_version": version}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.assertTrue(Notification.objects.filter(recipient=self.biz_user,
                                                    notification_type=NotificationType.JOB_PUBLISHED_BY_ADMIN,
                                                    related_id=job_id).exists())

    def test_unknown_business(self):
        self.client.force_authenticate(user=self.admin)
        self.assertEqual(self.client.post(reverse("admin-business-jobs", args=[999999]), job_body(),
                                          format="json").status_code, status.HTTP_404_NOT_FOUND)
