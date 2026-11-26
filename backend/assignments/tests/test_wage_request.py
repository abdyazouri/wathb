"""Work item 1: the worker's «أتممت يوم عملي واطلب أجري» and the business's answer."""
import datetime

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Role, User
from assignments.models import Assignment, AssignmentStatus, CompletionRecord, CompletionStatus
from assignments.tests.test_assignments import make_assignment, make_business, make_job, make_worker
from audit.models import AuditEvent
from disputes.models import Dispute
from notifications.models import Notification, NotificationType
from wages.models import PaymentDeclaration, WageObligation, WageObligationStatus


class WageRequestTestBase(APITestCase):

    def setUp(self):
        self.biz_user, self.biz_profile = make_business("+970599020001")
        self.worker = make_worker("+970599020002")
        self.other_worker = make_worker("+970599020003")
        self.other_biz, _ = make_business("+970599020004")
        self.admin = User.objects.create_user("+970599020005", "P@ss1234", role=Role.ADMIN, is_staff=True)
        self.job = make_job(self.biz_profile, work_date=timezone.localdate(), wage_amount=9000)
        self.assignment = make_assignment(self.job, self.worker, assign_status=AssignmentStatus.ACCEPTED)
        self.assignment.terms_snapshot = self.job.material_terms_snapshot()
        self.assignment.save(update_fields=["terms_snapshot"])

    def as_user(self, user):
        self.client.force_authenticate(user=user)
        return self.client

    def request_wage(self, user=None):
        return self.as_user(user or self.worker).post(reverse("completion", args=[self.assignment.pk]), {}, format="json")

    def confirm_and_pay(self, user=None):
        return self.as_user(user or self.biz_user).post(reverse("business-complete-assignment", args=[self.assignment.pk]))

    def not_done(self, user=None, **data):
        return self.as_user(user or self.biz_user).patch(
            reverse("completion-dispute", args=[self.assignment.pk]), data, format="json")


class WorkerRequestTests(WageRequestTestBase):

    def test_two_presses_create_one_completion_and_one_notification(self):
        first = self.request_wage()
        second = self.request_wage()
        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)
        self.assertEqual(second.status_code, status.HTTP_200_OK, second.data)
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(CompletionRecord.objects.filter(assignment=self.assignment).count(), 1)
        self.assertEqual(Notification.objects.filter(
            recipient=self.biz_user, notification_type="COMPLETION_SUBMITTED").count(), 1)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, AssignmentStatus.ACTIVE)

    def test_request_before_the_work_date_is_refused(self):
        self.job.work_date = timezone.localdate() + datetime.timedelta(days=1)
        self.job.save(update_fields=["work_date"])
        r = self.request_wage()
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(CompletionRecord.objects.filter(assignment=self.assignment).exists())

    def test_only_the_assigned_worker_can_request(self):
        self.assertEqual(self.request_wage(self.other_worker).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.request_wage(self.other_biz).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.request_wage(self.admin).status_code, status.HTTP_403_FORBIDDEN)
        self.client.force_authenticate(user=None)
        r = self.client.post(reverse("completion", args=[self.assignment.pk]), {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(CompletionRecord.objects.filter(assignment=self.assignment).exists())

    def test_admin_can_see_the_request(self):
        self.request_wage()
        r = self.as_user(self.admin).get(reverse("completion", args=[self.assignment.pk]))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["status"], CompletionStatus.SUBMITTED)
        rows = self.as_user(self.admin).get(reverse("assignment-list")).data["results"]
        row = next(a for a in rows if str(a["id"]) == str(self.assignment.pk))
        self.assertEqual(row["completion_status"], CompletionStatus.SUBMITTED)
        self.assertTrue(row["completion_requested_by_worker"])

    def test_request_is_audited(self):
        self.request_wage()
        event = AuditEvent.objects.get(action="completion_submitted")
        self.assertEqual((event.actor, event.details["by"]), (self.worker, Role.WORKER))


class ConfirmAndPayTests(WageRequestTestBase):

    def test_confirm_leads_to_the_existing_declare_and_acknowledge_flow(self):
        self.request_wage()
        # The business edits the job later: the wage still comes from the agreed terms.
        self.job.wage_amount = 1
        self.job.save(update_fields=["wage_amount"])

        r = self.confirm_and_pay()
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)

        record = CompletionRecord.objects.get(assignment=self.assignment)
        self.assertEqual((record.status, record.confirmed_by), (CompletionStatus.CONFIRMED, self.biz_user))
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, AssignmentStatus.COMPLETED)
        wage = WageObligation.objects.get(assignment=self.assignment)
        self.assertEqual((wage.amount, wage.status), (9000, WageObligationStatus.AWAITING_ACK))
        self.assertEqual(wage.due_date, timezone.localdate())
        declaration = PaymentDeclaration.objects.get(wage_obligation=wage)
        self.assertEqual(declaration.declared_amount, 9000)
        self.assertTrue(Notification.objects.filter(recipient=self.worker, notification_type="PAYMENT_DECLARED").exists())
        actions = set(AuditEvent.objects.values_list("action", flat=True))
        self.assertTrue({"completion_submitted", "completion_confirmed", "wage_created",
                         "business_complete_and_declare"} <= actions)

    def test_only_that_jobs_business_can_confirm(self):
        self.request_wage()
        self.assertEqual(self.confirm_and_pay(self.other_biz).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.confirm_and_pay(self.worker).status_code, status.HTTP_403_FORBIDDEN)
        confirm = reverse("completion-confirm", args=[self.assignment.pk])
        self.assertEqual(self.as_user(self.admin).patch(confirm).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.as_user(self.other_biz).patch(confirm).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.as_user(self.worker).patch(confirm).status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(CompletionRecord.objects.get(assignment=self.assignment).status, CompletionStatus.SUBMITTED)
        self.assertFalse(WageObligation.objects.filter(assignment=self.assignment).exists())

    def test_business_can_still_complete_when_the_worker_forgot(self):
        r = self.confirm_and_pay()
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.assertEqual(WageObligation.objects.get(assignment=self.assignment).status, WageObligationStatus.AWAITING_ACK)


class NotDoneTests(WageRequestTestBase):

    def test_reason_is_required(self):
        self.request_wage()
        for data in ({}, {"category": "OTHER"}, {"category": ""}):
            r = self.not_done(**data)
            self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST, data)
        self.assertEqual(CompletionRecord.objects.get(assignment=self.assignment).status, CompletionStatus.SUBMITTED)
        self.assertFalse(Dispute.objects.exists())

    def test_not_done_opens_a_dispute_and_pays_nothing(self):
        self.request_wage()
        r = self.not_done(category="WORKER_NO_SHOW", description="لم يحضر في الموعد")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.assertEqual(CompletionRecord.objects.get(assignment=self.assignment).status, CompletionStatus.DISPUTED)
        dispute = Dispute.objects.get(assignment=self.assignment)
        self.assertEqual((dispute.category, dispute.raised_by), ("WORKER_NO_SHOW", self.biz_user))
        self.assertFalse(WageObligation.objects.filter(assignment=self.assignment).exists())
        self.assertEqual(AuditEvent.objects.get(action="completion_disputed").details["category"], "WORKER_NO_SHOW")
        # Confirming afterwards is refused while the dispute is open.
        self.assertEqual(self.confirm_and_pay().status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(WageObligation.objects.filter(assignment=self.assignment).exists())
        # Silence does not turn a disputed request into a wage either.
        CompletionRecord.objects.filter(assignment=self.assignment).update(
            submitted_at=timezone.now() - datetime.timedelta(hours=25))
        self.as_user(self.biz_user).get(reverse("wage-list"))
        self.assertFalse(WageObligation.objects.filter(assignment=self.assignment).exists())

    def test_only_that_jobs_business_can_say_not_done(self):
        self.request_wage()
        self.assertEqual(self.not_done(self.other_biz, category="WORK_INCOMPLETE").status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.not_done(self.admin, category="WORK_INCOMPLETE").status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.not_done(self.worker, category="WORK_INCOMPLETE").status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Dispute.objects.exists())


class SilenceAndRemindersTests(WageRequestTestBase):

    def _age_request(self, hours):
        CompletionRecord.objects.filter(assignment=self.assignment).update(
            submitted_at=timezone.now() - datetime.timedelta(hours=hours))

    def test_silence_auto_confirms_after_24_hours_and_the_wage_is_due(self):
        self.request_wage()
        self._age_request(23)
        self.as_user(self.biz_user).get(reverse("wage-list"))
        self.assertEqual(CompletionRecord.objects.get(assignment=self.assignment).status, CompletionStatus.SUBMITTED)

        self._age_request(25)
        self.as_user(self.biz_user).get(reverse("wage-list"))
        self.assertEqual(CompletionRecord.objects.get(assignment=self.assignment).status, CompletionStatus.CONFIRMED)
        wage = WageObligation.objects.get(assignment=self.assignment)
        self.assertEqual((wage.status, wage.amount), (WageObligationStatus.DUE, 9000))
        self.assertTrue(AuditEvent.objects.filter(action="completion_auto_confirmed").exists())

    def _unpaid_wage(self, age_hours, wage_status=WageObligationStatus.DUE):
        wage = WageObligation.objects.create(
            assignment=self.assignment, amount=9000, currency="ILS",
            due_date=timezone.localdate(), status=wage_status,
        )
        WageObligation.objects.filter(pk=wage.pk).update(created_at=timezone.now() - datetime.timedelta(hours=age_hours))
        return wage

    def _reminders(self, user):
        return list(Notification.objects.filter(
            recipient=user,
            notification_type__in=[NotificationType.WAGE_UNPAID_1D, NotificationType.WAGE_UNPAID_3D],
        ).values_list("notification_type", flat=True))

    def test_business_is_reminded_after_one_and_three_days(self):
        wage = self._unpaid_wage(age_hours=12)
        self.as_user(self.biz_user).get(reverse("notification-list"))
        self.assertEqual(self._reminders(self.biz_user), [])

        WageObligation.objects.filter(pk=wage.pk).update(created_at=timezone.now() - datetime.timedelta(hours=25))
        self.as_user(self.biz_user).get(reverse("notification-list"))
        self.as_user(self.biz_user).get(reverse("wage-list"))  # no duplicate
        self.assertEqual(self._reminders(self.biz_user), [NotificationType.WAGE_UNPAID_1D])

        WageObligation.objects.filter(pk=wage.pk).update(created_at=timezone.now() - datetime.timedelta(hours=73))
        self.as_user(self.biz_user).get(reverse("notification-list"))
        self.assertEqual(sorted(self._reminders(self.biz_user)),
                         sorted([NotificationType.WAGE_UNPAID_1D, NotificationType.WAGE_UNPAID_3D]))
        self.assertEqual(self._reminders(self.worker), [])

    def test_no_reminder_once_payment_is_declared(self):
        self._unpaid_wage(age_hours=80, wage_status=WageObligationStatus.AWAITING_ACK)
        self.as_user(self.biz_user).get(reverse("notification-list"))
        self.assertEqual(self._reminders(self.biz_user), [])

    def test_after_three_days_the_wage_is_in_the_admins_unpaid_list(self):
        wage = self._unpaid_wage(age_hours=49)
        url = reverse("admin-unpaid-wages")
        self.assertEqual(self.as_user(self.admin).get(url).data, [])
        WageObligation.objects.filter(pk=wage.pk).update(created_at=timezone.now() - datetime.timedelta(hours=73))
        rows = self.as_user(self.admin).get(url).data
        self.assertEqual([r["id"] for r in rows], [str(wage.pk)])
        self.assertEqual(rows[0]["business_phone"], self.biz_user.phone)
        for user in (self.biz_user, self.worker):
            self.assertEqual(self.as_user(user).get(url).status_code, status.HTTP_403_FORBIDDEN)
