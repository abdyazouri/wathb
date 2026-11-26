import datetime

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import BusinessProfile, Role, User, WorkerProfile
from assignments.models import Assignment, AssignmentStatus
from audit.models import AuditEvent
from disputes.models import Dispute, DisputeStatus
from jobs.models import ApplicationStatus, JobApplication, JobListing, JobListingStatus
from notifications.models import Notification
from wages.models import (
    PaymentDeclaration, PaymentDeclarationStatus, WageObligation, WageObligationStatus,
)

PASSWORD = "P@ss1234"
URL = reverse("auth-delete-account")


def make_worker(phone):
    user = User.objects.create_user(phone, PASSWORD, role=Role.WORKER, email=f"w{phone[-4:]}@example.com")
    WorkerProfile.objects.create(
        user=user, full_name="سامي العامل", location_city="غزة", location_region="الرمال",
        skills="بناء", experience_summary="خبرة ٥ سنوات", national_id_hash="a" * 64,
    )
    return user


def make_business(phone):
    user = User.objects.create_user(phone, PASSWORD, role=Role.BUSINESS, is_verified=True)
    bp = BusinessProfile.objects.create(
        user=user, legal_name="مخبز الأمل", trade_name="الأمل", registration_number="R-1",
        location_address="شارع عمر المختار", location_city="غزة",
        contact_name="أبو أحمد", contact_phone="0599111222", verification_status="APPROVED",
    )
    return user, bp


def make_job(bp, job_status=JobListingStatus.PUBLISHED):
    return JobListing.objects.create(
        business=bp, title="عامل مخبز", description="خبز", location_address="غزة", location_city="غزة",
        work_date=datetime.date.today(), start_time="08:00", end_time="16:00",
        wage_amount=10000, payment_method="PALPAY", status=job_status,
    )


def make_assignment(job, worker, assign_status=AssignmentStatus.COMPLETED):
    app = JobApplication.objects.create(job=job, worker=worker, status=ApplicationStatus.ACCEPTED,
                                        cover_note="أنا سامي، هاتفي ٠٥٩٩")
    return Assignment.objects.create(
        job=job, worker=worker, application=app,
        terms_snapshot=job.material_terms_snapshot(), status=assign_status,
    )


def make_obligation(assignment, wage_status):
    return WageObligation.objects.create(
        assignment=assignment, amount=10000, currency="ILS",
        due_date=datetime.date.today(), status=wage_status,
    )


class DeleteAccountTestBase(APITestCase):

    def login(self, phone):
        response = self.client.post(reverse("auth-login"), {"phone": phone, "password": PASSWORD})
        self.assertEqual(response.status_code, 200, response.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        return response.data

    def delete(self, password=PASSWORD):
        return self.client.post(URL, {"password": password}, format="json")


class DeleteAccountAuthTests(DeleteAccountTestBase):

    def setUp(self):
        self.worker = make_worker("0599060001")

    def test_requires_authentication(self):
        self.assertEqual(self.delete().status_code, status.HTTP_401_UNAUTHORIZED)

    def test_missing_password_is_400(self):
        self.login("0599060001")
        response = self.client.post(URL, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data["fields"])

    def test_wrong_password_is_403_and_changes_nothing(self):
        self.login("0599060001")
        response = self.delete(password="wrong")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["detail"], "كلمة المرور غير صحيحة.")
        self.worker.refresh_from_db()
        self.assertTrue(self.worker.is_active)
        self.assertEqual(self.worker.phone, "+970599060001")
        self.assertIsNone(self.worker.deleted_at)
        self.assertFalse(AuditEvent.objects.filter(action="account_deleted").exists())


class DeleteAccountBlockedTests(DeleteAccountTestBase):
    """409 while anything is still open — and nothing is changed."""

    def setUp(self):
        self.biz, self.bp = make_business("0599060101")
        self.worker = make_worker("0599060102")
        self.job = make_job(self.bp, JobListingStatus.FILLED)

    def assert_blocked(self, phone, code):
        self.login(phone)
        response = self.delete()
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn(code, response.data["blockers"])
        self.assertIn("لا يمكن حذف الحساب", response.data["detail"])
        user = User.objects.get(phone=f"+970{phone[1:]}")
        self.assertTrue(user.is_active)
        self.assertIsNone(user.deleted_at)
        self.assertFalse(AuditEvent.objects.filter(action="account_deleted").exists())
        return user

    def test_worker_with_active_assignment(self):
        for assign_status in (AssignmentStatus.OFFERED, AssignmentStatus.ACCEPTED, AssignmentStatus.ACTIVE):
            Assignment.objects.all().delete()
            JobApplication.objects.all().delete()
            make_assignment(self.job, self.worker, assign_status)
            self.assert_blocked("0599060102", "active_assignments")

    def test_business_with_unpaid_wage_cannot_escape(self):
        assignment = make_assignment(self.job, self.worker)
        for wage_status in (
            WageObligationStatus.PENDING, WageObligationStatus.DUE, WageObligationStatus.AWAITING_ACK,
            WageObligationStatus.DISPUTED, WageObligationStatus.REJECTED, WageObligationStatus.UNDER_REVIEW,
        ):
            WageObligation.objects.all().delete()
            make_obligation(assignment, wage_status)
            user = self.assert_blocked("0599060101", "unsettled_wages")
            self.assertEqual(user.business_profile.contact_phone, "0599111222")

    def test_worker_with_unpaid_wage(self):
        make_obligation(make_assignment(self.job, self.worker), WageObligationStatus.AWAITING_ACK)
        self.assert_blocked("0599060102", "unsettled_wages")

    def test_open_dispute_blocks_both_parties(self):
        assignment = make_assignment(self.job, self.worker)
        make_obligation(assignment, WageObligationStatus.VERIFIED_PAID)
        Dispute.objects.create(category="OTHER", assignment=assignment, raised_by=self.worker,
                               description="...", status=DisputeStatus.IN_REVIEW)
        self.assert_blocked("0599060102", "open_disputes")
        self.client.credentials()
        self.assert_blocked("0599060101", "open_disputes")


class DeleteWorkerAccountTests(DeleteAccountTestBase):

    def setUp(self):
        self.biz, self.bp = make_business("0599060201")
        self.worker = make_worker("0599060202")
        job = make_job(self.bp, JobListingStatus.COMPLETED)
        self.assignment = make_assignment(job, self.worker)
        self.paid = make_obligation(self.assignment, WageObligationStatus.VERIFIED_PAID)
        PaymentDeclaration.objects.create(
            wage_obligation=self.paid, declared_amount=10000, currency="ILS",
            payment_date=datetime.date.today(), payment_method="PALPAY",
            declared_by=self.biz, status=PaymentDeclarationStatus.ACKNOWLEDGED,
        )
        self.dispute = Dispute.objects.create(
            category="OTHER", assignment=self.assignment, raised_by=self.worker,
            description="تأخر الدفع", status=DisputeStatus.RESOLVED,
        )
        self.open_job = make_job(self.bp)
        self.pending_app = JobApplication.objects.create(
            job=self.open_job, worker=self.worker, cover_note="رقمي ٠٥٩٩٠٦٠٢٠٢")
        Notification.objects.create(recipient=self.worker, notification_type="WAGE_DUE", title="t", body="b")
        self.earlier_audit = AuditEvent.objects.create(
            actor=self.worker, action="payment_acknowledged", model_name="WageObligation",
            object_id=str(self.paid.pk), details={"notes": "سامي أكد"},
        )
        self.tokens = self.login("0599060202")

    def test_success_returns_204_and_anonymises(self):
        response = self.delete()
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        user = User.objects.get(pk=self.worker.pk)
        self.assertTrue(user.phone.startswith("deleted-"))
        self.assertLessEqual(len(user.phone), 20)
        self.assertIsNone(user.email)
        self.assertFalse(user.is_active)
        self.assertFalse(user.has_usable_password())
        self.assertIsNotNone(user.deleted_at)

        profile = WorkerProfile.objects.get(user=user)
        self.assertEqual(profile.full_name, "مستخدم محذوف")
        self.assertEqual(
            (profile.location_city, profile.location_region, profile.skills,
             profile.experience_summary, profile.national_id_hash),
            ("", "", "", "", ""),
        )

    def test_records_are_kept(self):
        self.delete()
        self.paid.refresh_from_db()
        self.assertEqual(self.paid.status, WageObligationStatus.VERIFIED_PAID)
        self.assertEqual(Assignment.objects.get(pk=self.assignment.pk).worker_id, self.worker.pk)
        self.dispute.refresh_from_db()
        self.assertEqual((self.dispute.raised_by_id, self.dispute.description), (self.worker.pk, "تأخر الدفع"))
        self.assertEqual(PaymentDeclaration.objects.filter(wage_obligation=self.paid).count(), 1)

    def test_business_sees_placeholder_on_past_wage(self):
        self.delete()
        self.client.force_authenticate(user=self.biz)
        response = self.client.get(reverse("wage-detail", args=[self.paid.pk]))
        self.assertEqual(response.data["worker_name"], "مستخدم محذوف")
        self.assertTrue(response.data["worker_phone"].startswith("deleted-"))

    def test_login_and_tokens_stop_working(self):
        self.delete()
        # Access token already issued: rejected because the user is inactive.
        self.assertEqual(self.client.get(reverse("auth-me")).status_code, status.HTTP_401_UNAUTHORIZED)
        self.client.credentials()
        refresh = self.client.post(reverse("auth-token-refresh"), {"refresh": self.tokens["refresh"]})
        self.assertEqual(refresh.status_code, status.HTTP_401_UNAUTHORIZED)
        login = self.client.post(reverse("auth-login"), {"phone": "0599060202", "password": PASSWORD})
        self.assertEqual(login.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_all_refresh_tokens_blacklisted(self):
        from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
        self.client.post(reverse("auth-login"), {"phone": "0599060202", "password": PASSWORD})
        self.delete()
        outstanding = OutstandingToken.objects.filter(user_id=self.worker.pk)
        self.assertGreaterEqual(outstanding.count(), 2)
        self.assertEqual(BlacklistedToken.objects.filter(token__in=outstanding).count(), outstanding.count())

    def test_audit_event_recorded_without_personal_data(self):
        self.delete()
        event = AuditEvent.objects.get(action="account_deleted")
        self.assertEqual((event.actor_id, event.model_name, event.object_id),
                         (self.worker.pk, "User", str(self.worker.pk)))
        self.assertEqual(event.details, {"role": "WORKER"})

    def test_existing_audit_events_untouched(self):
        before = AuditEvent.objects.filter(pk=self.earlier_audit.pk).values().get()
        self.delete()
        self.assertEqual(AuditEvent.objects.filter(pk=self.earlier_audit.pk).values().get(), before)

    def test_open_applications_withdrawn_and_cover_notes_cleared(self):
        self.delete()
        self.pending_app.refresh_from_db()
        self.assertEqual(self.pending_app.status, ApplicationStatus.WITHDRAWN)
        self.assertFalse(JobApplication.objects.filter(worker=self.worker).exclude(cover_note="").exists())

    def test_own_notifications_removed(self):
        self.delete()
        self.assertFalse(Notification.objects.filter(recipient=self.worker).exists())

    def test_phone_can_register_again(self):
        self.delete()
        self.client.credentials()
        response = self.client.post(reverse("auth-register"), {
            "phone": "0599060202", "password": "Str0ng-Pass!", "role": "WORKER",
            "consent_version": 1, "full_name": "عامل جديد",
        }, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

    def test_placeholders_are_unique(self):
        self.delete()
        other = make_worker("0599060203")
        self.client.credentials()
        self.login("0599060203")
        self.assertEqual(self.delete().status_code, status.HTTP_204_NO_CONTENT)
        other.refresh_from_db()
        self.worker.refresh_from_db()
        self.assertNotEqual(other.phone, self.worker.phone)


class DeleteBusinessAccountTests(DeleteAccountTestBase):

    def setUp(self):
        self.biz, self.bp = make_business("0599060301")
        self.worker = make_worker("0599060302")
        past_job = make_job(self.bp, JobListingStatus.COMPLETED)
        self.paid = make_obligation(make_assignment(past_job, self.worker), WageObligationStatus.VERIFIED_PAID)
        cancelled_job = make_job(self.bp, JobListingStatus.CANCELLED)
        make_obligation(make_assignment(cancelled_job, self.worker, AssignmentStatus.CANCELLED),
                        WageObligationStatus.CANCELLED)
        self.open_job = make_job(self.bp)
        self.applicant = make_worker("0599060303")
        self.application = JobApplication.objects.create(job=self.open_job, worker=self.applicant)
        self.login("0599060301")

    def test_settled_business_can_delete(self):
        self.assertEqual(self.delete().status_code, status.HTTP_204_NO_CONTENT)

    def test_owner_contact_removed_commercial_name_kept(self):
        self.delete()
        self.bp.refresh_from_db()
        self.assertEqual((self.bp.contact_name, self.bp.contact_phone), ("", ""))
        self.assertEqual((self.bp.legal_name, self.bp.trade_name), ("مخبز الأمل", "الأمل"))
        from jobs.serializers import JobListingSerializer
        past_job = JobListing.objects.get(pk=self.paid.assignment.job_id)
        self.assertEqual(JobListingSerializer(past_job).data["business_name"], "مخبز الأمل")

    def test_open_listings_cancelled_and_applicants_notified(self):
        self.delete()
        self.open_job.refresh_from_db()
        self.application.refresh_from_db()
        self.assertEqual(self.open_job.status, JobListingStatus.CANCELLED)
        self.assertEqual(self.application.status, ApplicationStatus.CANCELLED)
        self.assertTrue(Notification.objects.filter(
            recipient=self.applicant, notification_type="JOB_CANCELLED", related_id=str(self.open_job.pk)
        ).exists())

    def test_wage_records_kept(self):
        self.delete()
        self.paid.refresh_from_db()
        self.assertEqual(self.paid.status, WageObligationStatus.VERIFIED_PAID)
        self.assertEqual(self.paid.assignment.job.business_id, self.bp.pk)
