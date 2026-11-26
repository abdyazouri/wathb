import datetime

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import User, Role, BusinessProfile, WorkerProfile
from assignments.models import (
    Assignment, AssignmentStatus, AttendanceRecord, AttendanceStatus,
    CompletionRecord, CompletionStatus,
)
from jobs.models import JobListing, JobListingStatus, JobApplication, ApplicationStatus
from wages.models import WageObligation


def make_user(phone, role, password="P@ss1234", **kwargs):
    return User.objects.create_user(phone, password, role=role, **kwargs)


def make_business(phone="+970599010001"):
    user = make_user(phone, Role.BUSINESS)
    bp = BusinessProfile.objects.create(
        user=user, legal_name="Test Co", contact_name="Owner",
        contact_phone="0599000000", verification_status="APPROVED",
    )
    user.is_verified = True
    user.save(update_fields=["is_verified"])
    return user, bp


def make_worker(phone="+970599010002"):
    user = make_user(phone, Role.WORKER)
    WorkerProfile.objects.create(user=user, full_name="Test Worker")
    return user


def make_job(business_profile, **kwargs):
    defaults = dict(
        title="Day Laborer",
        description="Help needed",
        location_address="123 St",
        location_city="Gaza City",
        work_date=datetime.date.today() + datetime.timedelta(days=1),
        start_time="08:00",
        end_time="17:00",
        num_workers_needed=1,
        wage_amount=10000,
        wage_currency="ILS",
        wage_basis="PER_DAY",
        payment_method="JAWWAL_PAY",
        status=JobListingStatus.PUBLISHED,
        is_funded=False,
    )
    defaults.update(kwargs)
    return JobListing.objects.create(business=business_profile, **defaults)


def make_assignment(job, worker, app_status=ApplicationStatus.OFFERED,
                    assign_status=AssignmentStatus.OFFERED):
    app = JobApplication.objects.create(job=job, worker=worker, status=app_status)
    return Assignment.objects.create(
        job=job,
        worker=worker,
        application=app,
        terms_snapshot={},
        status=assign_status,
    )


class AssignmentAcceptTests(APITestCase):

    def setUp(self):
        self.biz_user, self.biz_profile = make_business()
        self.worker = make_worker()
        self.job = make_job(self.biz_profile)
        self.assignment = make_assignment(self.job, self.worker)

    def test_worker_can_accept_offered_assignment(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.post(reverse("assignment-accept", args=[self.assignment.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, AssignmentStatus.ACCEPTED)

    def test_accept_captures_terms_snapshot(self):
        self.client.force_authenticate(user=self.worker)
        self.client.post(reverse("assignment-accept", args=[self.assignment.pk]))
        self.assignment.refresh_from_db()
        snapshot = self.assignment.terms_snapshot
        self.assertEqual(snapshot["wage_amount"], self.job.wage_amount)
        self.assertEqual(snapshot["wage_currency"], self.job.wage_currency)
        self.assertEqual(str(self.job.id), snapshot["job_id"])

    def test_snapshot_preserves_original_wage_after_job_edit(self):
        self.client.force_authenticate(user=self.worker)
        self.client.post(reverse("assignment-accept", args=[self.assignment.pk]))
        self.assignment.refresh_from_db()
        original_wage = self.assignment.terms_snapshot["wage_amount"]

        self.job.wage_amount = 99999
        self.job.save(update_fields=["wage_amount"])

        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.terms_snapshot["wage_amount"], original_wage)
        self.assertNotEqual(self.assignment.terms_snapshot["wage_amount"], 99999)

    def test_accept_transitions_job_to_filled(self):
        self.client.force_authenticate(user=self.worker)
        self.client.post(reverse("assignment-accept", args=[self.assignment.pk]))
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, JobListingStatus.FILLED)

    def test_cannot_accept_already_accepted_assignment(self):
        self.assignment.status = AssignmentStatus.ACCEPTED
        self.assignment.save(update_fields=["status"])
        self.client.force_authenticate(user=self.worker)
        response = self.client.post(reverse("assignment-accept", args=[self.assignment.pk]))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_worker_cannot_accept_another_workers_assignment(self):
        other_worker = make_worker("+970599010003")
        self.client.force_authenticate(user=other_worker)
        response = self.client.post(reverse("assignment-accept", args=[self.assignment.pk]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_assignment_uniqueness_per_job_worker(self):
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            app2 = JobApplication.objects.create(
                job=self.job, worker=make_worker("+970599010004"), status=ApplicationStatus.OFFERED
            )
            Assignment.objects.create(
                job=self.job,
                worker=self.worker,
                application=app2,
                terms_snapshot={},
                status=AssignmentStatus.OFFERED,
            )


class AssignmentDeclineTests(APITestCase):

    def setUp(self):
        self.biz_user, self.biz_profile = make_business()
        self.worker = make_worker()
        self.job = make_job(self.biz_profile)
        self.assignment = make_assignment(self.job, self.worker)

    def test_worker_can_decline_offered_assignment(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.post(reverse("assignment-decline", args=[self.assignment.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, AssignmentStatus.DECLINED)

    def test_cannot_decline_accepted_assignment(self):
        self.assignment.status = AssignmentStatus.ACCEPTED
        self.assignment.save(update_fields=["status"])
        self.client.force_authenticate(user=self.worker)
        response = self.client.post(reverse("assignment-decline", args=[self.assignment.pk]))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class AttendanceTests(APITestCase):

    def setUp(self):
        self.biz_user, self.biz_profile = make_business()
        self.worker = make_worker()
        self.job = make_job(self.biz_profile)
        self.assignment = make_assignment(
            self.job, self.worker, assign_status=AssignmentStatus.ACCEPTED
        )
        self.assignment.terms_snapshot = self.job.material_terms_snapshot()
        self.assignment.save(update_fields=["terms_snapshot"])

    def test_worker_can_submit_attendance(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.post(
            reverse("attendance-list", args=[self.assignment.pk]),
            {"work_date": str(self.job.work_date)},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_business_can_confirm_worker_attendance(self):
        AttendanceRecord.objects.create(
            assignment=self.assignment,
            submitted_by=self.worker,
            work_date=self.job.work_date,
            status=AttendanceStatus.SUBMITTED,
        )
        record = AttendanceRecord.objects.get(assignment=self.assignment)
        self.client.force_authenticate(user=self.biz_user)
        response = self.client.patch(
            reverse("attendance-confirm", args=[self.assignment.pk, record.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        record.refresh_from_db()
        self.assertEqual(record.status, AttendanceStatus.CONFIRMED)

    def test_worker_cannot_confirm_own_attendance(self):
        AttendanceRecord.objects.create(
            assignment=self.assignment,
            submitted_by=self.worker,
            work_date=self.job.work_date,
            status=AttendanceStatus.SUBMITTED,
        )
        record = AttendanceRecord.objects.get(assignment=self.assignment)
        self.client.force_authenticate(user=self.worker)
        response = self.client.patch(
            reverse("attendance-confirm", args=[self.assignment.pk, record.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_attendance_on_inactive_assignment_rejected(self):
        self.assignment.status = AssignmentStatus.OFFERED
        self.assignment.save(update_fields=["status"])
        self.client.force_authenticate(user=self.worker)
        response = self.client.post(
            reverse("attendance-list", args=[self.assignment.pk]),
            {"work_date": str(self.job.work_date)},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class CompletionTests(APITestCase):

    def setUp(self):
        self.biz_user, self.biz_profile = make_business()
        self.worker = make_worker()
        self.job = make_job(self.biz_profile, work_date=timezone.localdate())  # the work day
        self.assignment = make_assignment(
            self.job, self.worker, assign_status=AssignmentStatus.ACCEPTED
        )
        self.assignment.terms_snapshot = self.job.material_terms_snapshot()
        self.assignment.save(update_fields=["terms_snapshot"])

    def test_worker_can_submit_completion(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.post(
            reverse("completion", args=[self.assignment.pk]),
            {"notes": "Done"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_completion_already_recorded_by_the_other_party_returns_409(self):
        CompletionRecord.objects.create(
            assignment=self.assignment, submitted_by=self.biz_user,
            status=CompletionStatus.SUBMITTED,
        )
        self.client.force_authenticate(user=self.worker)
        response = self.client.post(
            reverse("completion", args=[self.assignment.pk]),
            {"notes": "Again"},
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_business_can_confirm_worker_completion(self):
        CompletionRecord.objects.create(
            assignment=self.assignment, submitted_by=self.worker,
            status=CompletionStatus.SUBMITTED,
        )
        self.client.force_authenticate(user=self.biz_user)
        response = self.client.patch(reverse("completion-confirm", args=[self.assignment.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, AssignmentStatus.COMPLETED)

    def test_worker_cannot_confirm_own_completion(self):
        CompletionRecord.objects.create(
            assignment=self.assignment, submitted_by=self.worker,
            status=CompletionStatus.SUBMITTED,
        )
        self.client.force_authenticate(user=self.worker)
        response = self.client.patch(reverse("completion-confirm", args=[self.assignment.pk]))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("لا يمكنك تأكيد إتمام سجّلته أنت", response.data["detail"])

    def test_business_cannot_confirm_own_completion_submission(self):
        CompletionRecord.objects.create(
            assignment=self.assignment, submitted_by=self.biz_user,
            status=CompletionStatus.SUBMITTED,
        )
        self.client.force_authenticate(user=self.biz_user)
        response = self.client.patch(reverse("completion-confirm", args=[self.assignment.pk]))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_confirmation_creates_wage_obligation(self):
        CompletionRecord.objects.create(
            assignment=self.assignment, submitted_by=self.worker,
            status=CompletionStatus.SUBMITTED,
        )
        self.client.force_authenticate(user=self.biz_user)
        self.client.patch(reverse("completion-confirm", args=[self.assignment.pk]))
        self.assertTrue(WageObligation.objects.filter(assignment=self.assignment).exists())

    def test_wage_obligation_amount_from_snapshot_not_current_job(self):
        original_wage = self.job.wage_amount
        self.assignment.terms_snapshot = self.job.material_terms_snapshot()
        self.assignment.save(update_fields=["terms_snapshot"])

        self.job.wage_amount = 99999
        self.job.save(update_fields=["wage_amount"])

        CompletionRecord.objects.create(
            assignment=self.assignment, submitted_by=self.worker,
            status=CompletionStatus.SUBMITTED,
        )
        self.client.force_authenticate(user=self.biz_user)
        self.client.patch(reverse("completion-confirm", args=[self.assignment.pk]))

        obligation = WageObligation.objects.get(assignment=self.assignment)
        self.assertEqual(obligation.amount, original_wage)
        self.assertNotEqual(obligation.amount, 99999)

    def test_wage_obligation_uniqueness(self):
        CompletionRecord.objects.create(
            assignment=self.assignment, submitted_by=self.worker,
            status=CompletionStatus.SUBMITTED,
        )
        from django.db import IntegrityError
        from wages.models import WageObligation
        WageObligation.objects.create(
            assignment=self.assignment, amount=10000, currency="ILS",
            due_date=datetime.date.today() + datetime.timedelta(days=3),
        )
        with self.assertRaises(IntegrityError):
            WageObligation.objects.create(
                assignment=self.assignment, amount=10000, currency="ILS",
                due_date=datetime.date.today() + datetime.timedelta(days=3),
            )


class AssignmentSerializerTermsTests(APITestCase):
    """Job terms are embedded in AssignmentSerializer for pre-acceptance review."""

    def setUp(self):
        self.biz_user, self.biz_profile = make_business()
        self.worker = make_worker()
        self.job = make_job(self.biz_profile)
        self.assignment = make_assignment(self.job, self.worker)

    def test_offered_assignment_list_contains_job_terms(self):
        self.client.force_authenticate(user=self.worker)
        response = self.client.get(reverse("assignment-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item = response.data["results"][0]
        self.assertEqual(str(item["job_work_date"]), str(self.job.work_date))
        self.assertEqual(item["job_wage_amount"], self.job.wage_amount)
        self.assertEqual(item["job_wage_currency"], self.job.wage_currency)
        self.assertEqual(item["job_payment_method"], self.job.payment_method)
        self.assertEqual(item["job_location_city"], self.job.location_city)

    def test_job_terms_survive_after_accept(self):
        self.client.force_authenticate(user=self.worker)
        self.client.post(reverse("assignment-accept", args=[self.assignment.pk]))
        response = self.client.get(reverse("assignment-list"))
        item = response.data["results"][0]
        # Live fields still reflect the job (they come from the FK, not the snapshot)
        self.assertEqual(item["job_wage_amount"], self.job.wage_amount)
        self.assertEqual(item["status"], AssignmentStatus.ACCEPTED)


class AutoConfirmTests(APITestCase):

    def setUp(self):
        self.biz_user, self.biz_profile = make_business()
        self.worker = make_worker()
        self.job = make_job(self.biz_profile, work_date=timezone.localdate())  # the work day
        self.assignment = make_assignment(
            self.job, self.worker, assign_status=AssignmentStatus.ACCEPTED
        )
        self.assignment.terms_snapshot = self.job.material_terms_snapshot()
        self.assignment.save(update_fields=["terms_snapshot"])

    def test_business_can_submit_attendance(self):
        self.client.force_authenticate(user=self.biz_user)
        response = self.client.post(
            reverse("attendance-list", args=[self.assignment.pk]),
            {"work_date": str(self.job.work_date)},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        record = AttendanceRecord.objects.get(assignment=self.assignment)
        self.assertEqual(record.submitted_by, self.biz_user)

    def test_business_can_submit_completion(self):
        self.client.force_authenticate(user=self.biz_user)
        response = self.client.post(
            reverse("completion", args=[self.assignment.pk]),
            {"notes": "Business submitted"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_worker_cannot_self_confirm_attendance(self):
        AttendanceRecord.objects.create(
            assignment=self.assignment, submitted_by=self.worker,
            work_date=self.job.work_date, status=AttendanceStatus.SUBMITTED,
        )
        record = AttendanceRecord.objects.get(assignment=self.assignment)
        self.client.force_authenticate(user=self.worker)
        response = self.client.patch(
            reverse("attendance-confirm", args=[self.assignment.pk, record.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_business_cannot_self_confirm_attendance(self):
        AttendanceRecord.objects.create(
            assignment=self.assignment, submitted_by=self.biz_user,
            work_date=self.job.work_date, status=AttendanceStatus.SUBMITTED,
        )
        record = AttendanceRecord.objects.get(assignment=self.assignment)
        self.client.force_authenticate(user=self.biz_user)
        response = self.client.patch(
            reverse("attendance-confirm", args=[self.assignment.pk, record.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_worker_can_confirm_business_attendance(self):
        AttendanceRecord.objects.create(
            assignment=self.assignment, submitted_by=self.biz_user,
            work_date=self.job.work_date, status=AttendanceStatus.SUBMITTED,
        )
        record = AttendanceRecord.objects.get(assignment=self.assignment)
        self.client.force_authenticate(user=self.worker)
        response = self.client.patch(
            reverse("attendance-confirm", args=[self.assignment.pk, record.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_auto_confirm_attendance_after_24h(self):
        record = AttendanceRecord.objects.create(
            assignment=self.assignment, submitted_by=self.worker,
            work_date=self.job.work_date, status=AttendanceStatus.SUBMITTED,
        )
        AttendanceRecord.objects.filter(pk=record.pk).update(
            submitted_at=timezone.now() - datetime.timedelta(hours=25)
        )
        from assignments.views import _auto_confirm_pending
        _auto_confirm_pending(self.assignment)
        record.refresh_from_db()
        self.assertEqual(record.status, AttendanceStatus.CONFIRMED)

    def test_auto_confirm_completion_creates_wage_obligation(self):
        comp = CompletionRecord.objects.create(
            assignment=self.assignment, submitted_by=self.worker,
            status=CompletionStatus.SUBMITTED,
        )
        CompletionRecord.objects.filter(pk=comp.pk).update(
            submitted_at=timezone.now() - datetime.timedelta(hours=25)
        )
        from assignments.views import _auto_confirm_pending
        _auto_confirm_pending(self.assignment)
        comp.refresh_from_db()
        self.assertEqual(comp.status, CompletionStatus.CONFIRMED)
        self.assertTrue(WageObligation.objects.filter(assignment=self.assignment).exists())

    def test_dispute_blocks_auto_confirm(self):
        comp = CompletionRecord.objects.create(
            assignment=self.assignment, submitted_by=self.worker,
            status=CompletionStatus.DISPUTED,
        )
        CompletionRecord.objects.filter(pk=comp.pk).update(
            submitted_at=timezone.now() - datetime.timedelta(hours=25)
        )
        from assignments.views import _auto_confirm_pending
        _auto_confirm_pending(self.assignment)
        comp.refresh_from_db()
        self.assertEqual(comp.status, CompletionStatus.DISPUTED)
        self.assertFalse(WageObligation.objects.filter(assignment=self.assignment).exists())

    def test_auto_confirm_creates_wage_obligation_exactly_once(self):
        comp = CompletionRecord.objects.create(
            assignment=self.assignment, submitted_by=self.worker,
            status=CompletionStatus.SUBMITTED,
        )
        CompletionRecord.objects.filter(pk=comp.pk).update(
            submitted_at=timezone.now() - datetime.timedelta(hours=25)
        )
        from assignments.views import _auto_confirm_pending
        _auto_confirm_pending(self.assignment)
        _auto_confirm_pending(self.assignment)
        self.assertEqual(WageObligation.objects.filter(assignment=self.assignment).count(), 1)


class BusinessCompleteTests(APITestCase):

    def setUp(self):
        self.biz_user, self.biz_profile = make_business()
        self.worker = make_worker()
        self.job = make_job(self.biz_profile)
        self.assignment = make_assignment(
            self.job, self.worker, assign_status=AssignmentStatus.ACCEPTED
        )
        self.assignment.terms_snapshot = self.job.material_terms_snapshot()
        self.assignment.save(update_fields=["terms_snapshot"])

    def test_business_can_complete_on_work_date(self):
        self.job.work_date = datetime.date.today()
        self.job.save(update_fields=["work_date"])
        self.client.force_authenticate(user=self.biz_user)
        response = self.client.post(
            reverse("business-complete-assignment", args=[self.assignment.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, AssignmentStatus.COMPLETED)

    def test_complete_creates_wage_obligation(self):
        self.job.work_date = datetime.date.today()
        self.job.save(update_fields=["work_date"])
        self.client.force_authenticate(user=self.biz_user)
        self.client.post(reverse("business-complete-assignment", args=[self.assignment.pk]))
        self.assertTrue(WageObligation.objects.filter(assignment=self.assignment).exists())

    def test_complete_sets_obligation_awaiting_ack(self):
        self.job.work_date = datetime.date.today()
        self.job.save(update_fields=["work_date"])
        self.client.force_authenticate(user=self.biz_user)
        self.client.post(reverse("business-complete-assignment", args=[self.assignment.pk]))
        from wages.models import WageObligationStatus
        obligation = WageObligation.objects.get(assignment=self.assignment)
        self.assertEqual(obligation.status, WageObligationStatus.AWAITING_ACK)

    def test_complete_declares_with_jobs_payment_method(self):
        from wages.models import PaymentDeclaration
        self.job.work_date = datetime.date.today()
        self.job.payment_method = "PALPAY"
        self.job.save(update_fields=["work_date", "payment_method"])
        self.assignment.terms_snapshot = self.job.material_terms_snapshot()
        self.assignment.save(update_fields=["terms_snapshot"])
        self.client.force_authenticate(user=self.biz_user)
        self.client.post(reverse("business-complete-assignment", args=[self.assignment.pk]))
        declaration = PaymentDeclaration.objects.get(wage_obligation__assignment=self.assignment)
        self.assertEqual(declaration.payment_method, "PALPAY")
        self.assertEqual(declaration.currency, "ILS")

    def test_complete_notification_shows_shekels_not_agorot(self):
        from notifications.models import Notification
        self.job.work_date = datetime.date.today()
        self.job.save(update_fields=["work_date"])
        self.client.force_authenticate(user=self.biz_user)
        self.client.post(reverse("business-complete-assignment", args=[self.assignment.pk]))
        note = Notification.objects.get(recipient=self.worker, notification_type="PAYMENT_DECLARED")
        amount = WageObligation.objects.get(assignment=self.assignment).amount
        from yawmiyati.money import format_money
        self.assertIn(format_money(amount), note.body)
        self.assertNotIn("ILS", note.body)

    def test_cannot_complete_before_work_date(self):
        self.job.work_date = datetime.date.today() + datetime.timedelta(days=1)
        self.job.save(update_fields=["work_date"])
        self.client.force_authenticate(user=self.biz_user)
        response = self.client.post(
            reverse("business-complete-assignment", args=[self.assignment.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_complete_offered_assignment(self):
        self.assignment.status = AssignmentStatus.OFFERED
        self.assignment.save(update_fields=["status"])
        self.job.work_date = datetime.date.today()
        self.job.save(update_fields=["work_date"])
        self.client.force_authenticate(user=self.biz_user)
        response = self.client.post(
            reverse("business-complete-assignment", args=[self.assignment.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_complete_is_idempotent(self):
        self.job.work_date = datetime.date.today()
        self.job.save(update_fields=["work_date"])
        self.client.force_authenticate(user=self.biz_user)
        self.client.post(reverse("business-complete-assignment", args=[self.assignment.pk]))
        response = self.client.post(reverse("business-complete-assignment", args=[self.assignment.pk]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(WageObligation.objects.filter(assignment=self.assignment).count(), 1)

    def test_worker_cannot_call_business_complete(self):
        self.job.work_date = datetime.date.today()
        self.job.save(update_fields=["work_date"])
        self.client.force_authenticate(user=self.worker)
        response = self.client.post(
            reverse("business-complete-assignment", args=[self.assignment.pk])
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class OfferChangedTermsTests(APITestCase):
    """The offer tells the worker which terms the business changed since they applied."""

    def setUp(self):
        self.biz_user, self.biz_profile = make_business("+970599010501")
        self.worker = make_worker("+970599010502")
        self.job = make_job(self.biz_profile)

    def _apply_and_offer(self):
        self.client.force_authenticate(user=self.worker)
        r = self.client.post(reverse("job-apply", args=[self.job.pk]), {"cover_note": ""}, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)
        app = JobApplication.objects.get(pk=r.data["id"])
        self.client.force_authenticate(user=self.biz_user)
        r = self.client.patch(reverse("application-action", args=[self.job.pk, app.pk]), {"action": "offer"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        return app

    def _offer_as_worker_sees_it(self):
        self.client.force_authenticate(user=self.worker)
        rows = self.client.get(reverse("assignment-list")).data["results"]
        return next(a for a in rows if str(a["job"]) == str(self.job.pk))

    def test_apply_records_the_terms_seen(self):
        app = self._apply_and_offer()
        self.assertEqual(app.terms_at_apply["wage_amount"], 10000)
        self.assertEqual(app.terms_at_apply["work_date"], str(self.job.work_date))

    def test_unchanged_offer_has_no_changed_terms(self):
        self._apply_and_offer()
        self.assertEqual(self._offer_as_worker_sees_it()["changed_terms"], [])

    def test_wage_and_date_changed_after_applying_are_listed(self):
        self._apply_and_offer()
        self.client.force_authenticate(user=self.biz_user)
        r = self.client.patch(
            reverse("job-detail", args=[self.job.pk]),
            {"wage_amount": 8000, "work_date": str(self.job.work_date + datetime.timedelta(days=1))},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.assertEqual(self._offer_as_worker_sees_it()["changed_terms"], ["work_date", "wage_amount"])

    def test_after_confirming_the_list_is_empty(self):
        self._apply_and_offer()
        self.job.wage_amount = 8000
        self.job.save(update_fields=["wage_amount"])
        offer = self._offer_as_worker_sees_it()
        self.assertEqual(offer["changed_terms"], ["wage_amount"])
        self.client.post(reverse("assignment-accept", args=[offer["id"]]))
        self.assertEqual(self._offer_as_worker_sees_it()["changed_terms"], [])

    def test_application_from_before_this_change_lists_nothing(self):
        make_assignment(self.job, self.worker)  # application with no recorded terms
        self.job.wage_amount = 8000
        self.job.save(update_fields=["wage_amount"])
        self.assertEqual(self._offer_as_worker_sees_it()["changed_terms"], [])
