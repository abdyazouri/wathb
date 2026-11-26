import datetime
import io

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase, APITransactionTestCase

from accounts.models import User, Role, BusinessProfile, WorkerProfile
from assignments.models import Assignment, AssignmentStatus
from jobs.models import JobListing, JobListingStatus, JobApplication, ApplicationStatus
from wages.models import WageObligation, WageObligationStatus, PaymentDeclaration, PaymentDeclarationStatus


def make_user(phone, role, password="P@ss1234", **kwargs):
    return User.objects.create_user(phone, password, role=role, **kwargs)


def make_business(phone="+970599013001"):
    user = make_user(phone, Role.BUSINESS)
    bp = BusinessProfile.objects.create(
        user=user, legal_name="Wages Co", contact_name="Owner",
        contact_phone="0599000100", verification_status="APPROVED",
    )
    user.is_verified = True
    user.save(update_fields=["is_verified"])
    return user, bp


def make_worker(phone="+970599013002"):
    user = make_user(phone, Role.WORKER)
    WorkerProfile.objects.create(user=user, full_name="Wage Worker")
    return user


def make_job_and_assignment(biz_profile, worker_user, wage_amount=10000):
    job = JobListing.objects.create(
        business=biz_profile,
        title="Laborer",
        description="Work",
        location_address="Gaza",
        location_city="Gaza City",
        work_date=datetime.date.today() + datetime.timedelta(days=1),
        start_time="08:00",
        end_time="17:00",
        num_workers_needed=1,
        wage_amount=wage_amount,
        wage_currency="ILS",
        wage_basis="PER_DAY",
        payment_method="JAWWAL_PAY",
        status=JobListingStatus.PUBLISHED,
    )
    app = JobApplication.objects.create(job=job, worker=worker_user, status=ApplicationStatus.ACCEPTED)
    assignment = Assignment.objects.create(
        job=job,
        worker=worker_user,
        application=app,
        terms_snapshot=job.material_terms_snapshot(),
        status=AssignmentStatus.COMPLETED,
    )
    return job, assignment


def make_obligation(assignment, wage_amount=10000, obligation_status=WageObligationStatus.PENDING):
    return WageObligation.objects.create(
        assignment=assignment,
        amount=wage_amount,
        currency="ILS",
        due_date=datetime.date.today() + datetime.timedelta(days=3),
        status=obligation_status,
    )


def make_declaration(obligation, declared_by, decl_status=PaymentDeclarationStatus.SUBMITTED):
    return PaymentDeclaration.objects.create(
        wage_obligation=obligation,
        declared_amount=obligation.amount,
        currency=obligation.currency,
        payment_date=datetime.date.today(),
        payment_method="JAWWAL_PAY",
        declared_by=declared_by,
        status=decl_status,
    )


class WageObligationCreationTests(APITestCase):

    def test_wage_obligation_created_from_snapshot_values(self):
        biz_user, biz_profile = make_business("+970599013003")
        worker = make_worker("+970599013004")
        job, assignment = make_job_and_assignment(biz_profile, worker, wage_amount=15000)
        obligation = make_obligation(assignment, wage_amount=15000)
        self.assertEqual(obligation.amount, 15000)
        self.assertEqual(obligation.currency, "ILS")

    def test_wage_is_due_the_day_the_work_is_confirmed(self):
        # Wathb pays daily: no deadline in days, the wage is due as soon as the work is done.
        from django.utils import timezone
        from assignments.views import _create_wage_obligation
        _, biz_profile = make_business("+970599013007")
        worker = make_worker("+970599013008")
        job, assignment = make_job_and_assignment(biz_profile, worker)
        assignment.terms_snapshot = dict(job.material_terms_snapshot(), work_date="2026-11-01")
        assignment.save(update_fields=["terms_snapshot"])
        _create_wage_obligation(assignment)
        obligation = WageObligation.objects.get(assignment=assignment)
        self.assertEqual(obligation.due_date, timezone.localdate())
        self.assertNotIn("payment_deadline_days", job.material_terms_snapshot())

    def test_only_one_obligation_per_assignment(self):
        biz_user, biz_profile = make_business("+970599013005")
        worker = make_worker("+970599013006")
        job, assignment = make_job_and_assignment(biz_profile, worker)
        make_obligation(assignment)
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            make_obligation(assignment)


class PaymentDeclarationTests(APITestCase):

    def setUp(self):
        self.biz_user, self.biz_profile = make_business()
        self.worker = make_worker()
        self.job, self.assignment = make_job_and_assignment(self.biz_profile, self.worker)
        self.obligation = make_obligation(self.assignment)

    def _decl_body(self):
        return {
            "declared_amount": 10000,
            "currency": "ILS",
            "payment_date": str(datetime.date.today()),
            "payment_method": "JAWWAL_PAY",
        }

    def test_business_can_declare_payment(self):
        self.client.force_authenticate(user=self.biz_user)
        response = self.client.post(
            reverse("wage-declare-payment", args=[self.obligation.pk]),
            self._decl_body(),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.obligation.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.AWAITING_ACK)

    def test_worker_cannot_declare_payment(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.post(
            reverse("wage-declare-payment", args=[self.obligation.pk]),
            self._decl_body(),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_cannot_declare_payment_for_already_declared_obligation(self):
        self.obligation.status = WageObligationStatus.AWAITING_ACK
        self.obligation.save(update_fields=["status"])
        self.client.force_authenticate(user=self.biz_user)
        response = self.client.post(
            reverse("wage-declare-payment", args=[self.obligation.pk]),
            self._decl_body(),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_declare_for_another_businesss_obligation(self):
        other_biz_user, other_biz_profile = make_business("+970599013007")
        self.client.force_authenticate(user=other_biz_user)
        response = self.client.post(
            reverse("wage-declare-payment", args=[self.obligation.pk]),
            self._decl_body(),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_invalid_payment_method_returns_400(self):
        """payment_method must be one of JAWWAL_PAY / PALPAY / BANK_OF_PALESTINE."""
        self.client.force_authenticate(user=self.biz_user)
        body = self._decl_body()
        body["payment_method"] = "BITCOIN"
        response = self.client.post(
            reverse("wage-declare-payment", args=[self.obligation.pk]),
            body,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_removed_payment_methods_rejected(self):
        """Owner decision: no cash. CASH, OTHER and the old BANK_TRANSFER are rejected."""
        self.client.force_authenticate(user=self.biz_user)
        for method in ("CASH", "OTHER", "BANK_TRANSFER"):
            body = self._decl_body()
            body["payment_method"] = method
            response = self.client.post(
                reverse("wage-declare-payment", args=[self.obligation.pk]),
                body,
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, msg=f"method={method}")
            self.assertIn("payment_method", response.data["fields"])
        self.obligation.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.PENDING)

    def test_non_ils_currency_rejected(self):
        self.client.force_authenticate(user=self.biz_user)
        for currency in ("USD", "EUR", "JOD"):
            body = self._decl_body()
            body["currency"] = currency
            response = self.client.post(
                reverse("wage-declare-payment", args=[self.obligation.pk]),
                body,
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, msg=f"currency={currency}")
            self.assertIn("currency", response.data["fields"])
        self.obligation.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.PENDING)

    def test_all_valid_payment_methods_accepted(self):
        methods = ("JAWWAL_PAY", "PALPAY", "BANK_OF_PALESTINE")
        for i, method in enumerate(methods):
            # Re-create an obligation for each variant (tearDown not available here,
            # so we just chain a new obligation on a new assignment).
            _, assign = make_job_and_assignment(
                self.biz_profile, self.worker,
                wage_amount=5000 + i
            )
            obl = make_obligation(assign)
            self.client.force_authenticate(user=self.biz_user)
            body = {
                "declared_amount": obl.amount,
                "currency": "ILS",
                "payment_date": str(__import__("datetime").date.today()),
                "payment_method": method,
            }
            resp = self.client.post(reverse("wage-declare-payment", args=[obl.pk]), body)
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED, msg=f"method={method}")


class PaymentAcknowledgmentTests(APITestCase):

    def setUp(self):
        self.biz_user, self.biz_profile = make_business()
        self.worker = make_worker()
        self.job, self.assignment = make_job_and_assignment(self.biz_profile, self.worker)
        self.obligation = make_obligation(self.assignment, obligation_status=WageObligationStatus.AWAITING_ACK)
        make_declaration(self.obligation, self.biz_user)

    def test_worker_can_acknowledge_payment(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.post(reverse("wage-acknowledge", args=[self.obligation.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.obligation.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.VERIFIED_PAID)

    def test_acknowledgment_marks_declaration_acknowledged(self):
        self.client.force_authenticate(user=self.worker)
        self.client.post(reverse("wage-acknowledge", args=[self.obligation.pk]))
        decl = PaymentDeclaration.objects.get(wage_obligation=self.obligation)
        self.assertEqual(decl.status, PaymentDeclarationStatus.ACKNOWLEDGED)

    def test_cannot_acknowledge_non_awaiting_obligation(self):
        self.obligation.status = WageObligationStatus.PENDING
        self.obligation.save(update_fields=["status"])
        self.client.force_authenticate(user=self.worker)
        response = self.client.post(reverse("wage-acknowledge", args=[self.obligation.pk]))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_business_cannot_acknowledge_payment(self):
        self.client.force_authenticate(user=self.biz_user)
        response = self.client.post(reverse("wage-acknowledge", args=[self.obligation.pk]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def _ack(self, data=None):
        self.client.force_authenticate(user=self.worker)
        return self.client.post(reverse("wage-acknowledge", args=[self.obligation.pk]), data or {}, format="json")

    def _ack_audit(self):
        from audit.models import AuditEvent
        return AuditEvent.objects.get(action="payment_acknowledged", object_id=str(self.obligation.pk))

    def test_acknowledge_with_correct_password(self):
        response = self._ack({"password": "P@ss1234"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.obligation.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.VERIFIED_PAID)
        self.assertEqual(self._ack_audit().details, {"confirmed_with": "password"})

    def test_acknowledge_with_wrong_or_blank_password_is_403_and_changes_nothing(self):
        from yawmiyati.exception_handler import is_arabic
        for password in ("wrong-password", ""):
            response = self._ack({"password": password})
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, password)
            self.assertEqual(response.data["detail"], "كلمة المرور غير صحيحة.")
            self.assertTrue(is_arabic(response.data["detail"]))
        self.obligation.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.AWAITING_ACK)
        decl = PaymentDeclaration.objects.get(wage_obligation=self.obligation)
        self.assertEqual(decl.status, PaymentDeclarationStatus.SUBMITTED)

    def test_acknowledge_after_device_auth_records_method(self):
        response = self._ack()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._ack_audit().details, {"confirmed_with": "device"})

    def test_password_attempts_are_throttled(self):
        from django.core.cache import cache
        from wages.views import _AcknowledgePasswordThrottle
        cache.clear()
        _AcknowledgePasswordThrottle.THROTTLE_RATES = {"acknowledge_password": "2/hour"}
        try:
            codes = [self._ack({"password": "wrong"}).status_code for _ in range(3)]
        finally:
            del _AcknowledgePasswordThrottle.THROTTLE_RATES  # back to the inherited settings
            cache.clear()
        self.assertEqual(codes, [403, 403, 429])


class PaymentDisputeTests(APITestCase):

    def setUp(self):
        self.biz_user, self.biz_profile = make_business()
        self.worker = make_worker()
        self.job, self.assignment = make_job_and_assignment(self.biz_profile, self.worker)
        self.obligation = make_obligation(self.assignment, obligation_status=WageObligationStatus.AWAITING_ACK)
        make_declaration(self.obligation, self.biz_user)

    def test_worker_can_dispute_payment(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.post(
            reverse("wage-dispute-payment", args=[self.obligation.pk]),
            {"category": "PAYMENT_NOT_RECEIVED", "description": "I never got paid"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.obligation.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.DISPUTED)

    def test_dispute_creates_dispute_record(self):
        from disputes.models import Dispute
        self.client.force_authenticate(user=self.worker)
        self.client.post(
            reverse("wage-dispute-payment", args=[self.obligation.pk]),
            {"category": "PAYMENT_NOT_RECEIVED", "description": "Not paid"},
        )
        self.assertTrue(Dispute.objects.filter(assignment=self.assignment).exists())

    def test_dispute_marks_declaration_disputed(self):
        self.client.force_authenticate(user=self.worker)
        self.client.post(
            reverse("wage-dispute-payment", args=[self.obligation.pk]),
            {"category": "PAYMENT_NOT_RECEIVED"},
        )
        decl = PaymentDeclaration.objects.get(wage_obligation=self.obligation)
        self.assertEqual(decl.status, PaymentDeclarationStatus.DISPUTED)

    def test_cannot_dispute_non_awaiting_obligation(self):
        self.obligation.status = WageObligationStatus.PENDING
        self.obligation.save(update_fields=["status"])
        self.client.force_authenticate(user=self.worker)
        response = self.client.post(
            reverse("wage-dispute-payment", args=[self.obligation.pk]),
            {"category": "PAYMENT_NOT_RECEIVED"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_business_cannot_dispute_payment(self):
        self.client.force_authenticate(user=self.biz_user)
        response = self.client.post(
            reverse("wage-dispute-payment", args=[self.obligation.pk]),
            {"category": "PAYMENT_NOT_RECEIVED"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class FileUploadValidationTests(APITestCase):

    def setUp(self):
        self.biz_user, self.biz_profile = make_business("+970599013010")
        self.worker = make_worker("+970599013011")
        self.job, self.assignment = make_job_and_assignment(self.biz_profile, self.worker)
        self.obligation = make_obligation(self.assignment, obligation_status=WageObligationStatus.AWAITING_ACK)
        self.declaration = make_declaration(self.obligation, self.biz_user)

    def _upload_url(self):
        return reverse("wage-upload-evidence", args=[self.obligation.pk, self.declaration.pk])

    def test_upload_valid_jpeg(self):
        jpeg_bytes = b'\xff\xd8\xff\xe0' + b'\x00' * 100
        f = io.BytesIO(jpeg_bytes)
        f.name = "receipt.jpg"
        self.client.force_authenticate(user=self.biz_user)
        response = self.client.post(self._upload_url(), {"file": f}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_upload_valid_png(self):
        png_bytes = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
        f = io.BytesIO(png_bytes)
        f.name = "receipt.png"
        self.client.force_authenticate(user=self.biz_user)
        response = self.client.post(self._upload_url(), {"file": f}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_upload_valid_pdf(self):
        pdf_bytes = b'%PDF' + b'\x00' * 100
        f = io.BytesIO(pdf_bytes)
        f.name = "receipt.pdf"
        self.client.force_authenticate(user=self.biz_user)
        response = self.client.post(self._upload_url(), {"file": f}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_upload_disallowed_file_type_rejected(self):
        exe_bytes = b'MZ' + b'\x00' * 100
        f = io.BytesIO(exe_bytes)
        f.name = "malware.exe"
        self.client.force_authenticate(user=self.biz_user)
        response = self.client.post(self._upload_url(), {"file": f}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("نوع الملف غير مسموح", response.data["detail"])

    def test_upload_oversized_file_rejected(self):
        from django.conf import settings
        large_bytes = b'\xff\xd8\xff\xe0' + b'\x00' * (settings.MAX_UPLOAD_SIZE_BYTES + 1)
        f = io.BytesIO(large_bytes)
        f.name = "large.jpg"
        self.client.force_authenticate(user=self.biz_user)
        response = self.client.post(self._upload_url(), {"file": f}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("حجم الملف", response.data["detail"])

    def test_worker_cannot_upload_evidence(self):
        f = io.BytesIO(b'\xff\xd8\xff\xe0' + b'\x00' * 100)
        f.name = "receipt.jpg"
        self.client.force_authenticate(user=self.worker)
        response = self.client.post(self._upload_url(), {"file": f}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class AdminVerifyPaymentTests(APITestCase):

    def setUp(self):
        self.biz_user, self.biz_profile = make_business("+970599013015")
        self.worker = make_worker("+970599013016")
        self.admin = make_user("+970599013017", Role.ADMIN)
        self.job, self.assignment = make_job_and_assignment(self.biz_profile, self.worker)
        self.obligation = make_obligation(self.assignment, obligation_status=WageObligationStatus.AWAITING_ACK)
        self.declaration = make_declaration(self.obligation, self.biz_user)

    def _verify_url(self):
        return reverse("wage-admin-verify", args=[self.obligation.pk, self.declaration.pk])

    def _dispute(self):
        """The worker disputed the declaration: the only state admin verify/reject accept."""
        from disputes.models import Dispute
        self.obligation.status = WageObligationStatus.DISPUTED
        self.obligation.save(update_fields=["status"])
        self.declaration.status = PaymentDeclarationStatus.DISPUTED
        self.declaration.save(update_fields=["status"])
        self.dispute = Dispute.objects.create(
            category="PAYMENT_NOT_RECEIVED", assignment=self.assignment,
            wage_obligation=self.obligation, raised_by=self.worker, description="لم أستلم",
        )

    def test_admin_can_verify_disputed_wage_with_notes(self):
        self._dispute()
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(self._verify_url(), {"action": "verify", "review_notes": "إيصال جوال باي واضح"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.declaration.refresh_from_db()
        self.obligation.refresh_from_db()
        self.assertEqual(self.declaration.status, PaymentDeclarationStatus.VERIFIED)
        self.assertEqual(self.declaration.review_notes, "إيصال جوال باي واضح")
        self.assertEqual(self.obligation.status, WageObligationStatus.VERIFIED_PAID)

    def test_admin_can_reject_disputed_wage_and_it_returns_to_due(self):
        self._dispute()
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(self._verify_url(), {"action": "reject", "review_notes": "لا يوجد إيصال"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.declaration.refresh_from_db()
        self.obligation.refresh_from_db()
        self.assertEqual(self.declaration.status, PaymentDeclarationStatus.REJECTED)
        self.assertEqual(self.declaration.review_notes, "لا يوجد إيصال")
        self.assertEqual(self.obligation.status, WageObligationStatus.DUE)

        # The business must pay and declare again.
        self.client.force_authenticate(user=self.biz_user)
        response = self.client.post(
            reverse("wage-declare-payment", args=[self.obligation.pk]),
            {"declared_amount": self.obligation.amount, "currency": "ILS",
             "payment_date": str(datetime.date.today()), "payment_method": "PALPAY"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.obligation.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.AWAITING_ACK)

    def test_settling_notifies_worker_and_business_in_arabic(self):
        from notifications.models import Notification
        from yawmiyati.exception_handler import is_arabic
        for action, notification_type in (("verify", "PAYMENT_VERIFIED"), ("reject", "PAYMENT_REJECTED")):
            with self.subTest(action=action):
                Notification.objects.all().delete()
                self._dispute()
                self.client.force_authenticate(user=self.admin)
                response = self.client.post(self._verify_url(), {"action": action, "review_notes": "تمت مراجعة الإيصال"})
                self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
                for user in (self.worker, self.biz_user):
                    n = Notification.objects.get(recipient=user, related_id=str(self.obligation.pk))
                    self.assertEqual(n.notification_type, notification_type)
                    self.assertTrue(is_arabic(n.title) and is_arabic(n.body), (n.title, n.body))
                    self.assertIn("تمت مراجعة الإيصال", n.body)

    def test_settling_resolves_linked_dispute_with_same_note(self):
        from disputes.models import DisputeStatus
        for action in ("verify", "reject"):
            with self.subTest(action=action):
                self._dispute()
                self.client.force_authenticate(user=self.admin)
                self.client.post(self._verify_url(), {"action": action, "review_notes": "  قرار المشرف  "})
                self.dispute.refresh_from_db()
                self.assertEqual(self.dispute.status, DisputeStatus.RESOLVED)
                self.assertEqual(self.dispute.resolution_notes, "قرار المشرف")
                self.assertIsNotNone(self.dispute.resolved_at)
                event = self.dispute.events.get(action="resolved")
                self.assertEqual((event.actor, event.notes), (self.admin, "قرار المشرف"))

    def test_settling_requires_non_empty_notes(self):
        self._dispute()
        self.client.force_authenticate(user=self.admin)
        for action in ("verify", "reject"):
            for notes in (None, "", "   "):
                data = {"action": action} if notes is None else {"action": action, "review_notes": notes}
                response = self.client.post(self._verify_url(), data)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, data)
                self.assertIn("review_notes", response.data["detail"])
        self.declaration.refresh_from_db()
        self.obligation.refresh_from_db()
        self.assertEqual(self.declaration.status, PaymentDeclarationStatus.DISPUTED)
        self.assertEqual(self.obligation.status, WageObligationStatus.DISPUTED)

    def test_settling_refused_while_awaiting_worker(self):
        # setUp state: declared, worker has not acknowledged or disputed yet.
        self.client.force_authenticate(user=self.admin)
        for action in ("verify", "reject"):
            response = self.client.post(self._verify_url(), {"action": action, "review_notes": "ملاحظة"})
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, action)
        self.declaration.refresh_from_db()
        self.obligation.refresh_from_db()
        self.assertEqual(self.declaration.status, PaymentDeclarationStatus.SUBMITTED)
        self.assertEqual(self.obligation.status, WageObligationStatus.AWAITING_ACK)

    def test_settling_checks_wage_status_not_only_declaration(self):
        # A disputed declaration on a wage that is no longer DISPUTED must not flip the wage.
        self._dispute()
        self.client.force_authenticate(user=self.admin)
        for action in ("verify", "reject"):
            for wage_status in (WageObligationStatus.VERIFIED_PAID, WageObligationStatus.REJECTED,
                                WageObligationStatus.AWAITING_ACK, WageObligationStatus.PENDING,
                                WageObligationStatus.DUE):
                self.obligation.status = wage_status
                self.obligation.save(update_fields=["status"])
                response = self.client.post(self._verify_url(), {"action": action, "review_notes": "ملاحظة"})
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, (action, wage_status))
                self.obligation.refresh_from_db()
                self.assertEqual(self.obligation.status, wage_status)
                self.declaration.refresh_from_db()
                self.assertEqual(self.declaration.status, PaymentDeclarationStatus.DISPUTED)

    def test_settling_refused_for_non_disputed_declaration_on_disputed_wage(self):
        self._dispute()
        self.declaration.status = PaymentDeclarationStatus.SUBMITTED
        self.declaration.save(update_fields=["status"])
        self.client.force_authenticate(user=self.admin)
        for action in ("verify", "reject"):
            response = self.client.post(self._verify_url(), {"action": action, "review_notes": "ملاحظة"})
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, action)
        self.obligation.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.DISPUTED)

    def test_dispute_list_exposes_wage_status_and_disputed_declaration(self):
        self._dispute()
        self.client.force_authenticate(user=self.admin)
        row = self.client.get(reverse("dispute-list")).data["results"][0]
        self.assertEqual(row["wage_obligation_status"], WageObligationStatus.DISPUTED)
        self.assertEqual(row["disputed_declaration"], str(self.declaration.pk))

        self.client.post(self._verify_url(), {"action": "reject", "review_notes": "ملاحظة"})
        row = self.client.get(reverse("dispute-list")).data["results"][0]
        self.assertEqual(row["wage_obligation_status"], WageObligationStatus.DUE)
        self.assertIsNone(row["disputed_declaration"])

    def test_non_admin_cannot_verify(self):
        for user in [self.biz_user, self.worker]:
            self.client.force_authenticate(user=user)
            response = self.client.post(self._verify_url(), {"action": "verify"})
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_invalid_action_returns_400(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(self._verify_url(), {"action": "approve"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_verify_sets_reviewed_by(self):
        self._dispute()
        self.client.force_authenticate(user=self.admin)
        self.client.post(self._verify_url(), {"action": "verify", "review_notes": "ملاحظة"})
        self.declaration.refresh_from_db()
        self.assertEqual(self.declaration.reviewed_by, self.admin)

    def test_wage_obligation_list_status_filter(self):
        other_biz_user, other_biz_profile = make_business("+970599013020")
        other_worker = make_worker("+970599013021")
        other_job, other_assignment = make_job_and_assignment(other_biz_profile, other_worker)
        make_obligation(other_assignment, obligation_status=WageObligationStatus.PENDING)

        self.client.force_authenticate(user=self.admin)
        response = self.client.get(reverse("wage-list"), {"status": "AWAITING_ACK"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        statuses = [o["status"] for o in response.data["results"]]
        self.assertTrue(all(s == WageObligationStatus.AWAITING_ACK for s in statuses))

    def test_amount_display_is_arabic_shekels(self):
        from wages.serializers import WageObligationSerializer
        self.assertEqual(WageObligationSerializer(self.obligation).data["amount_display"], "١٠٠ ₪")
        self.obligation.amount = 2550
        data = WageObligationSerializer(self.obligation).data
        self.assertEqual(data["amount_display"], "٢٥٫٥٠ ₪")
        # Raw minor-unit field is unchanged.
        self.assertEqual(data["amount"], 2550)

    def test_obligation_serializer_includes_declarations(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(reverse("wage-detail", args=[self.obligation.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("declarations", response.data)
        self.assertEqual(len(response.data["declarations"]), 1)
        self.assertEqual(response.data["declarations"][0]["id"], str(self.declaration.pk))


class AdminPhoneResolveTests(APITestCase):

    def setUp(self):
        from django.utils import timezone as tz
        self.admin = User.objects.create_user("+970599016001", "P@ss1234", role=Role.ADMIN, is_staff=True)
        biz_user, biz_profile = make_business("+970599016002")
        worker_user = make_worker("+970599016003")
        _, assignment = make_job_and_assignment(biz_profile, worker_user)
        self.obligation = make_obligation(assignment, obligation_status=WageObligationStatus.AWAITING_ACK)
        self.declaration = make_declaration(self.obligation, biz_user)
        PaymentDeclaration.objects.filter(pk=self.declaration.pk).update(
            declared_at=tz.now() - datetime.timedelta(days=4)
        )
        self.url = reverse("wage-admin-phone-resolve", kwargs={"pk": str(self.obligation.pk)})

    def _auth_admin(self):
        resp = self.client.post(reverse("auth-login"), {"phone": "0599016001", "password": "P@ss1234"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

    def _auth_worker(self):
        resp = self.client.post(reverse("auth-login"), {"phone": "0599016003", "password": "P@ss1234"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

    def test_confirmed_by_phone_sets_verified_paid(self):
        self._auth_admin()
        resp = self.client.patch(self.url, {"action": "confirmed_by_phone", "notes": "تحدثت مع العامل"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.obligation.refresh_from_db()
        self.declaration.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.VERIFIED_PAID)
        self.assertEqual(self.declaration.status, PaymentDeclarationStatus.VERIFIED)

    def test_disputed_by_phone_creates_dispute_and_sets_disputed(self):
        from disputes.models import Dispute
        self._auth_admin()
        resp = self.client.patch(self.url, {"action": "disputed_by_phone", "notes": "نفى العامل الاستلام"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.obligation.refresh_from_db()
        self.declaration.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.DISPUTED)
        self.assertEqual(self.declaration.status, PaymentDeclarationStatus.DISPUTED)
        self.assertTrue(Dispute.objects.filter(wage_obligation=self.obligation).exists())

    def test_non_admin_cannot_phone_resolve(self):
        self._auth_worker()
        resp = self.client.patch(self.url, {"action": "confirmed_by_phone", "notes": "test"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_empty_notes_returns_400(self):
        self._auth_admin()
        resp = self.client.patch(self.url, {"action": "confirmed_by_phone", "notes": ""}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_action_returns_400(self):
        self._auth_admin()
        resp = self.client.patch(self.url, {"action": "bad_action", "notes": "test"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_awaiting_ack_obligation_returns_400(self):
        self._auth_admin()
        self.obligation.status = WageObligationStatus.VERIFIED_PAID
        self.obligation.save(update_fields=["status"])
        resp = self.client.patch(self.url, {"action": "confirmed_by_phone", "notes": "test"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class AdminPhoneResolveAutocommitTests(APITransactionTestCase):
    """Runs in autocommit, as production does. APITestCase wraps every test in a
    transaction, which hides a select_for_update() issued outside transaction.atomic()."""

    def setUp(self):
        self.admin = make_user("+970599016101", Role.ADMIN, is_staff=True)
        biz_user, biz_profile = make_business("+970599016102")
        worker_user = make_worker("+970599016103")
        _, assignment = make_job_and_assignment(biz_profile, worker_user)
        self.obligation = make_obligation(assignment, obligation_status=WageObligationStatus.AWAITING_ACK)
        self.declaration = make_declaration(self.obligation, biz_user)
        self.url = reverse("wage-admin-phone-resolve", kwargs={"pk": str(self.obligation.pk)})
        self.client.force_authenticate(user=self.admin)

    def test_confirmed_by_phone_outside_test_transaction(self):
        resp = self.client.patch(self.url, {"action": "confirmed_by_phone", "notes": "تحدثت مع العامل"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.obligation.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.VERIFIED_PAID)

    def test_disputed_by_phone_outside_test_transaction(self):
        resp = self.client.patch(self.url, {"action": "disputed_by_phone", "notes": "نفى العامل الاستلام"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.obligation.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.DISPUTED)


class ListCallSideEffectTests(APITestCase):
    """List/detail GETs run lazy auto-confirm and wage reminders. Those may create a wage
    but must never move one along the payment flow."""

    def setUp(self):
        self.biz_user, biz_profile = make_business("+970599018001")
        self.worker = make_worker("+970599018002")
        self.admin = make_user("+970599018003", Role.ADMIN, is_staff=True)
        _, self.assignment = make_job_and_assignment(biz_profile, self.worker)
        self.assignment.status = AssignmentStatus.ACTIVE
        self.assignment.save(update_fields=["status"])

    def _hit_every_list_endpoint(self, completion_recorded):
        pk = self.assignment.pk
        calls = [
            (self.worker, reverse("wage-list")),
            (self.biz_user, reverse("wage-list")),
            (self.admin, reverse("wage-list")),
            (self.worker, reverse("notification-list")),
            (self.biz_user, reverse("notification-list")),
            (self.worker, reverse("assignment-list")),
            (self.biz_user, reverse("assignment-list")),
            (self.worker, reverse("assignment-detail", args=[pk])),
            (self.worker, reverse("attendance-list", args=[pk])),
            (self.worker, reverse("completion", args=[pk])),
            (self.admin, reverse("admin-pilot-summary")),
        ]
        for user, url in calls:
            self.client.force_authenticate(user=user)
            response = self.client.get(url)
            # The completion GET answers 404 when no completion has been recorded yet.
            expected = status.HTTP_404_NOT_FOUND if url.endswith("/completion/") and not completion_recorded else status.HTTP_200_OK
            self.assertEqual(response.status_code, expected, url)

    def test_auto_confirm_creates_new_wage_as_due(self):
        from assignments.models import CompletionRecord, CompletionStatus
        from django.utils import timezone as tz
        comp = CompletionRecord.objects.create(
            assignment=self.assignment, submitted_by=self.worker, status=CompletionStatus.SUBMITTED,
        )
        CompletionRecord.objects.filter(pk=comp.pk).update(submitted_at=tz.now() - datetime.timedelta(hours=25))

        self.client.force_authenticate(user=self.worker)
        response = self.client.get(reverse("wage-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        obligation = WageObligation.objects.get(assignment=self.assignment)
        # Daily pay: a wage is due the moment the work is confirmed.
        self.assertEqual(obligation.status, WageObligationStatus.DUE)
        self.assertEqual([o["status"] for o in response.data["results"]], [WageObligationStatus.DUE])

        self._hit_every_list_endpoint(completion_recorded=True)
        obligation.refresh_from_db()
        self.assertEqual(obligation.status, WageObligationStatus.DUE)
        self.assertEqual(WageObligation.objects.filter(assignment=self.assignment).count(), 1)
        self.assertFalse(obligation.declarations.exists())

    def test_awaiting_ack_wage_unchanged_by_list_calls(self):
        from django.utils import timezone as tz
        obligation = make_obligation(self.assignment, obligation_status=WageObligationStatus.AWAITING_ACK)
        declaration = make_declaration(obligation, self.biz_user)
        # Old enough that the 3-day worker reminder fires on the list call.
        PaymentDeclaration.objects.filter(pk=declaration.pk).update(declared_at=tz.now() - datetime.timedelta(days=4))

        self._hit_every_list_endpoint(completion_recorded=False)

        obligation.refresh_from_db()
        declaration.refresh_from_db()
        self.assertEqual(obligation.status, WageObligationStatus.AWAITING_ACK)
        self.assertEqual(declaration.status, PaymentDeclarationStatus.SUBMITTED)
        from notifications.models import Notification, NotificationType
        self.assertTrue(Notification.objects.filter(
            recipient=self.worker, notification_type=NotificationType.WAGE_REMINDER_3D,
            related_id=str(obligation.pk),
        ).exists())


class DisputePaymentConcurrencyTests(APITransactionTestCase):
    """Runs in autocommit with real row locks. An acknowledge that commits while a
    dispute request is in flight must win; the dispute must then see the new status."""

    def setUp(self):
        biz_user, biz_profile = make_business("+970599019001")
        self.worker = make_worker("+970599019002")
        _, assignment = make_job_and_assignment(biz_profile, self.worker)
        self.obligation = make_obligation(assignment, obligation_status=WageObligationStatus.AWAITING_ACK)
        self.declaration = make_declaration(self.obligation, biz_user)

    def test_dispute_waits_for_concurrent_acknowledge(self):
        import threading
        import time
        from django.db import connection, transaction
        from disputes.models import Dispute

        result = {}

        def dispute_request():
            try:
                client = APIClient()
                client.force_authenticate(user=self.worker)
                result["response"] = client.post(
                    reverse("wage-dispute-payment", args=[self.obligation.pk]),
                    {"category": "PAYMENT_NOT_RECEIVED", "description": "لم أستلم"}, format="json",
                )
            finally:
                connection.close()

        with transaction.atomic():
            # Acknowledge in progress: the wage row is locked.
            locked = WageObligation.objects.select_for_update().get(pk=self.obligation.pk)
            thread = threading.Thread(target=dispute_request)
            thread.start()
            time.sleep(0.5)  # the dispute request is now reading/waiting
            locked.status = WageObligationStatus.VERIFIED_PAID
            locked.save(update_fields=["status"])
            PaymentDeclaration.objects.filter(pk=self.declaration.pk).update(
                status=PaymentDeclarationStatus.ACKNOWLEDGED
            )
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive())

        self.assertEqual(result["response"].status_code, status.HTTP_400_BAD_REQUEST)
        self.obligation.refresh_from_db()
        self.declaration.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.VERIFIED_PAID)
        self.assertEqual(self.declaration.status, PaymentDeclarationStatus.ACKNOWLEDGED)
        self.assertFalse(Dispute.objects.filter(wage_obligation=self.obligation).exists())

    def test_dispute_outside_test_transaction(self):
        from disputes.models import Dispute
        self.client.force_authenticate(user=self.worker)
        response = self.client.post(
            reverse("wage-dispute-payment", args=[self.obligation.pk]),
            {"category": "PAYMENT_NOT_RECEIVED", "description": "لم أستلم"}, format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.obligation.refresh_from_db()
        self.declaration.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.DISPUTED)
        self.assertEqual(self.declaration.status, PaymentDeclarationStatus.DISPUTED)
        self.assertEqual(Dispute.objects.filter(wage_obligation=self.obligation).count(), 1)


class AdminStaleWageListTests(APITestCase):

    def setUp(self):
        self.admin = User.objects.create_user("+970599017001", "P@ss1234", role=Role.ADMIN, is_staff=True)
        biz_user, biz_profile = make_business("+970599017002")
        worker_user = make_worker("+970599017003")
        _, self.assignment = make_job_and_assignment(biz_profile, worker_user)
        self.biz_user = biz_user
        self.url = reverse("admin-stale-wages")

    def _auth_admin(self):
        resp = self.client.post(reverse("auth-login"), {"phone": "0599017001", "password": "P@ss1234"})
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")

    def test_returns_obligations_older_than_3_days(self):
        from django.utils import timezone as tz
        obligation = make_obligation(self.assignment, obligation_status=WageObligationStatus.AWAITING_ACK)
        decl = make_declaration(obligation, self.biz_user)
        PaymentDeclaration.objects.filter(pk=decl.pk).update(
            declared_at=tz.now() - datetime.timedelta(days=4)
        )
        self._auth_admin()
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = [o["id"] for o in resp.data]
        self.assertIn(str(obligation.pk), ids)

    def test_excludes_recent_obligations(self):
        from django.utils import timezone as tz
        obligation = make_obligation(self.assignment, obligation_status=WageObligationStatus.AWAITING_ACK)
        decl = make_declaration(obligation, self.biz_user)
        PaymentDeclaration.objects.filter(pk=decl.pk).update(
            declared_at=tz.now() - datetime.timedelta(days=1)
        )
        self._auth_admin()
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = [o["id"] for o in resp.data]
        self.assertNotIn(str(obligation.pk), ids)
