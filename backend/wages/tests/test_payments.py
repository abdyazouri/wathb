"""Work item 2: «تحويل الأجر» — automatic (provider) and manual modes."""
import datetime
import json
import logging
import threading
import time

from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase, APITransactionTestCase

from accounts.models import Role, User
from audit.models import AuditEvent
from notifications.models import Notification
from wages.models import (
    PaymentAttempt, PaymentAttemptStatus, PaymentDeclaration, PaymentDeclarationStatus,
    WageObligation, WageObligationStatus,
)
from wages.payments import get_provider, payment_mode
from wages.payments.fake import VALID_CODE, FakeProvider
from wages.tests.test_wages import make_business, make_job_and_assignment, make_obligation, make_worker

AUTOMATIC = override_settings(JAWWAL_PAY_AUTOMATIC=True, PAYMENT_PROVIDER="fake")
WRONG_CODE = "654321"


class CapturedLogs(logging.Handler):
    """Every log record from every logger, formatted with its traceback."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.text = []
        self.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))

    def emit(self, record):
        self.text.append(self.format(record))

    def __enter__(self):
        root = logging.getLogger()
        self._old_level = root.level
        root.setLevel(logging.DEBUG)
        root.addHandler(self)
        return self

    def __exit__(self, *exc):
        root = logging.getLogger()
        root.removeHandler(self)
        root.setLevel(self._old_level)


def _fixture(test):
    test.biz_user, test.biz_profile = make_business("+970599030001")
    test.biz_profile.jawwal_pay_wallet = "+970599030009"
    test.biz_profile.save(update_fields=["jawwal_pay_wallet"])
    test.worker = make_worker("+970599030002")
    test.job, test.assignment = make_job_and_assignment(test.biz_profile, test.worker, wage_amount=8500)
    test.obligation = make_obligation(test.assignment, wage_amount=8500, obligation_status=WageObligationStatus.DUE)


class PaymentTestBase(APITestCase):

    def setUp(self):
        FakeProvider.reset()
        _fixture(self)

    def as_user(self, user):
        self.client.force_authenticate(user=user)
        return self.client

    def info(self, user=None):
        return self.as_user(user or self.biz_user).get(reverse("wage-payment", args=[self.obligation.pk]))

    def initiate(self, user=None, **body):
        return self.as_user(user or self.biz_user).post(
            reverse("wage-payment-initiate", args=[self.obligation.pk]), body, format="json")

    def confirm(self, code=VALID_CODE, user=None):
        return self.as_user(user or self.biz_user).post(
            reverse("wage-payment-confirm", args=[self.obligation.pk]), {"code": code}, format="json")

    def age_code(self, seconds=61):
        PaymentAttempt.objects.filter(wage_obligation=self.obligation).update(
            code_sent_at=timezone.now() - datetime.timedelta(seconds=seconds))

    def assert_paid_once(self):
        self.obligation.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.AWAITING_ACK)
        self.assertEqual(len(FakeProvider.completed), 1)
        self.assertEqual(PaymentAttempt.objects.filter(wage_obligation=self.obligation,
                                                       status=PaymentAttemptStatus.SUCCEEDED).count(), 1)
        self.assertEqual(PaymentDeclaration.objects.filter(wage_obligation=self.obligation).count(), 1)


@AUTOMATIC
class AutomaticPaymentTests(PaymentTestBase):

    def test_screen_shows_worker_wallet_and_agreed_amount(self):
        r = self.info()
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data["mode"], "automatic")
        self.assertEqual((r.data["worker_wallet"], r.data["amount"], r.data["needs_wallet"]),
                         (self.worker.phone, 8500, False))

    def test_send_then_code_pays_the_worker(self):
        r = self.initiate()
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.assertEqual(r.data["attempt"]["status"], PaymentAttemptStatus.INITIATED)
        r = self.confirm()
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.assert_paid_once()
        declaration = PaymentDeclaration.objects.get(wage_obligation=self.obligation)
        self.assertTrue(declaration.provider_confirmed)
        self.assertEqual((declaration.declared_amount, declaration.payment_method), (8500, "JAWWAL_PAY"))
        attempt = PaymentAttempt.objects.get(wage_obligation=self.obligation)
        self.assertTrue(attempt.provider_reference and attempt.completed_at and attempt.code_sent_at)
        note = Notification.objects.get(recipient=self.worker, related_id=str(self.obligation.pk))
        self.assertEqual(note.title, "وصلك أجرك: ٨٥ ₪")
        actions = list(AuditEvent.objects.order_by("timestamp").values_list("action", flat=True))
        self.assertEqual(actions, ["payment_initiated", "payment_succeeded"])

    def test_amount_comes_from_the_agreed_terms_only(self):
        self.job.wage_amount = 1
        self.job.save(update_fields=["wage_amount"])
        self.initiate(amount=1, declared_amount=1)
        self.confirm()
        request = FakeProvider.transfers[FakeProvider.completed[0]]["request"]
        self.assertEqual((request.amount, request.payee_wallet, request.payer_wallet),
                         (8500, self.worker.phone, "+970599030009"))

    def test_double_tap_pays_once(self):
        self.initiate()
        first, second = self.confirm(), self.confirm()
        self.assertEqual((first.status_code, second.status_code), (status.HTTP_200_OK, status.HTTP_200_OK))
        self.assert_paid_once()
        self.assertEqual(self.initiate().status_code, status.HTTP_409_CONFLICT)
        r = self.as_user(self.biz_user).post(reverse("wage-declare-payment", args=[self.obligation.pk]), {})
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assert_paid_once()

    def test_resend_only_after_60_seconds_and_same_transfer(self):
        self.initiate()
        r = self.initiate()
        self.assertEqual(r.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.age_code()
        r = self.initiate()
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.assertEqual(PaymentAttempt.objects.filter(wage_obligation=self.obligation).count(), 1)
        self.assertEqual(len(FakeProvider.transfers), 1)
        self.assertTrue(AuditEvent.objects.filter(action="payment_code_resent").exists())

    def test_wrong_code_can_be_retried(self):
        self.initiate()
        r = self.confirm(WRONG_CODE)
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(r.data["failure"], "WRONG_CODE")
        self.assertEqual(PaymentAttempt.objects.get(wage_obligation=self.obligation).status,
                         PaymentAttemptStatus.INITIATED)
        self.confirm()
        self.assert_paid_once()

    def test_expired_code_asks_for_a_new_one(self):
        self.initiate()
        FakeProvider.script = ["CODE_EXPIRED"]
        r = self.confirm()
        self.assertEqual((r.status_code, r.data["failure"]), (status.HTTP_400_BAD_REQUEST, "CODE_EXPIRED"))
        self.age_code()
        self.assertEqual(self.initiate().status_code, status.HTTP_200_OK)
        self.confirm()
        self.assert_paid_once()

    def test_insufficient_balance_fails_and_a_new_attempt_is_allowed(self):
        self.initiate()
        FakeProvider.script = ["INSUFFICIENT_BALANCE"]
        r = self.confirm()
        self.assertEqual(r.data["failure"], "INSUFFICIENT_BALANCE")
        self.obligation.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.DUE)
        self.assertEqual(self.initiate().status_code, status.HTTP_200_OK)
        self.assertEqual(PaymentAttempt.objects.filter(wage_obligation=self.obligation).count(), 2)
        self.confirm()
        self.assert_paid_once()

    def test_recipient_without_wallet(self):
        FakeProvider.script = ["RECIPIENT_NO_WALLET"]
        r = self.initiate()
        self.assertEqual((r.status_code, r.data["failure"]), (status.HTTP_400_BAD_REQUEST, "RECIPIENT_NO_WALLET"))
        self.assertEqual(PaymentAttempt.objects.get().status, PaymentAttemptStatus.FAILED)

    def test_timeout_after_the_money_moved_is_reconciled_not_repaid(self):
        self.initiate()
        FakeProvider.script = ["TIMEOUT_AFTER_SUCCESS"]
        r = self.confirm()
        self.assertEqual(r.status_code, status.HTTP_504_GATEWAY_TIMEOUT)
        self.assertEqual(PaymentAttempt.objects.get().status, PaymentAttemptStatus.UNKNOWN)
        self.obligation.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.DUE)
        # The retry asks the provider first and finds the transfer done.
        r = self.initiate()
        self.assertEqual(r.status_code, status.HTTP_409_CONFLICT)
        self.assert_paid_once()
        self.assertTrue(AuditEvent.objects.filter(action="payment_reconciled").exists())

    def test_timeout_before_the_money_moved_resumes_the_same_transfer(self):
        self.initiate()
        FakeProvider.script = ["TIMEOUT"]
        self.assertEqual(self.confirm().status_code, status.HTTP_504_GATEWAY_TIMEOUT)
        self.assertEqual(self.confirm().status_code, status.HTTP_409_CONFLICT)  # still checking
        self.age_code()
        r = self.initiate()  # get_status → still waiting for the code → resend
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.assertEqual(PaymentAttempt.objects.count(), 1)
        self.confirm()
        self.assert_paid_once()

    def test_business_must_link_a_wallet_first(self):
        self.biz_profile.jawwal_pay_wallet = ""
        self.biz_profile.save(update_fields=["jawwal_pay_wallet"])
        self.assertTrue(self.info().data["needs_wallet"])
        r = self.initiate()
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(r.data["needs_wallet"])
        self.assertFalse(PaymentAttempt.objects.exists())

    def test_only_the_jobs_business_can_pay(self):
        other_biz, _ = make_business("+970599030003")
        admin = User.objects.create_user("+970599030004", "P@ss1234", role=Role.ADMIN, is_staff=True)
        for user, expected in ((other_biz, 404), (self.worker, 403), (admin, 403)):
            self.assertEqual(self.info(user).status_code, expected)
            self.assertEqual(self.initiate(user).status_code, expected)
            self.assertEqual(self.confirm(user=user).status_code, expected)
        self.client.force_authenticate(user=None)
        r = self.client.post(reverse("wage-payment-initiate", args=[self.obligation.pk]))
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(PaymentAttempt.objects.exists())
        self.assertEqual(FakeProvider.completed, [])


@AUTOMATIC
class CodeIsNeverKeptTests(PaymentTestBase):

    def _everything_written(self, responses):
        parts = [r.content.decode() for r in responses]
        parts += [json.dumps(e.details, ensure_ascii=False) for e in AuditEvent.objects.all()]
        parts += [f"{n.title} {n.body}" for n in Notification.objects.all()]
        for model in (PaymentAttempt, PaymentDeclaration, WageObligation):
            for row in model.objects.all():
                parts += [str(getattr(row, f.attname)) for f in model._meta.fields]
        return "\n".join(parts)

    def test_code_is_not_in_responses_audit_rows_or_logs(self):
        self.client.raise_request_exception = False
        with CapturedLogs() as logs:
            responses = [self.initiate(), self.confirm(WRONG_CODE)]
            FakeProvider.script = ["CRASH"]
            crashed = self.confirm(WRONG_CODE)
            self.assertEqual(crashed.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
            responses += [crashed, self.confirm(VALID_CODE)]
        written = self._everything_written(responses) + "\n".join(logs.text)
        self.assertTrue(logs.text, "expected the crash to be logged")
        for code in (WRONG_CODE, VALID_CODE):
            self.assertNotIn(code, written)
        self.assert_paid_once()


class AutomaticPaymentConcurrencyTests(APITransactionTestCase):

    def setUp(self):
        FakeProvider.reset()
        _fixture(self)

    @AUTOMATIC
    def test_concurrent_confirmations_pay_once(self):
        client = APIClient()
        client.force_authenticate(user=self.biz_user)
        client.post(reverse("wage-payment-initiate", args=[self.obligation.pk]), {}, format="json")
        codes = []
        barrier = threading.Barrier(2)

        def confirm():
            try:
                c = APIClient()
                c.force_authenticate(user=self.biz_user)
                barrier.wait()
                codes.append(c.post(reverse("wage-payment-confirm", args=[self.obligation.pk]),
                                    {"code": VALID_CODE}, format="json").status_code)
            finally:
                connection.close()

        threads = [threading.Thread(target=confirm) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)
        self.assertEqual(sorted(codes), [200, 200])
        self.assertEqual(len(FakeProvider.completed), 1)
        self.assertEqual(PaymentDeclaration.objects.filter(wage_obligation=self.obligation).count(), 1)

    @AUTOMATIC
    def test_concurrent_sends_open_one_attempt(self):
        results = []
        barrier = threading.Barrier(2)

        def send():
            try:
                c = APIClient()
                c.force_authenticate(user=self.biz_user)
                barrier.wait()
                results.append(c.post(reverse("wage-payment-initiate", args=[self.obligation.pk]),
                                      {}, format="json").status_code)
            finally:
                connection.close()

        threads = [threading.Thread(target=send) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)
        self.assertEqual(sorted(results), [200, 429])
        self.assertEqual(PaymentAttempt.objects.filter(wage_obligation=self.obligation).count(), 1)


class ProviderSafetyTests(APITestCase):

    def test_fake_provider_refuses_production_settings(self):
        with override_settings(IS_PRODUCTION=True, PAYMENT_PROVIDER="fake"):
            with self.assertRaises(ImproperlyConfigured):
                FakeProvider()
            with self.assertRaises(ImproperlyConfigured):
                get_provider()

    def test_production_settings_reject_the_fake_provider(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[2] / "yawmiyati" / "settings" / "production.py").read_text()
        self.assertIn("IS_PRODUCTION = True", source)
        self.assertIn('if PAYMENT_PROVIDER == "fake":', source)

    def test_jawwal_adapter_is_not_live_so_the_flag_stays_manual(self):
        with override_settings(JAWWAL_PAY_AUTOMATIC=True, PAYMENT_PROVIDER="jawwal"):
            self.assertEqual(payment_mode(), "manual")
        with override_settings(JAWWAL_PAY_AUTOMATIC=False, PAYMENT_PROVIDER="fake"):
            self.assertEqual(payment_mode(), "manual")


class AcknowledgementWindowTests(PaymentTestBase):

    def _declare(self, provider_confirmed, age_hours):
        declaration = PaymentDeclaration.objects.create(
            wage_obligation=self.obligation, declared_amount=8500, currency="ILS",
            payment_date=timezone.localdate(), payment_method="JAWWAL_PAY", declared_by=self.biz_user,
            provider_confirmed=provider_confirmed,
        )
        PaymentDeclaration.objects.filter(pk=declaration.pk).update(
            declared_at=timezone.now() - datetime.timedelta(hours=age_hours))
        self.obligation.status = WageObligationStatus.AWAITING_ACK
        self.obligation.save(update_fields=["status"])
        return declaration

    def test_provider_confirmed_payment_is_acknowledged_after_24_hours(self):
        declaration = self._declare(provider_confirmed=True, age_hours=23)
        self.as_user(self.worker).get(reverse("wage-list"))
        self.obligation.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.AWAITING_ACK)

        PaymentDeclaration.objects.filter(pk=declaration.pk).update(
            declared_at=timezone.now() - datetime.timedelta(hours=25))
        self.as_user(self.worker).get(reverse("wage-list"))
        self.obligation.refresh_from_db()
        declaration.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.VERIFIED_PAID)
        self.assertEqual(declaration.status, PaymentDeclarationStatus.ACKNOWLEDGED)
        self.assertTrue(AuditEvent.objects.filter(action="payment_auto_acknowledged").exists())

    def test_manual_declaration_is_never_acknowledged_automatically(self):
        self._declare(provider_confirmed=False, age_hours=72)
        self.as_user(self.worker).get(reverse("wage-list"))
        self.as_user(self.worker).get(reverse("notification-list"))
        self.obligation.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.AWAITING_ACK)

    def test_worker_can_say_not_received_within_24_hours(self):
        self._declare(provider_confirmed=True, age_hours=2)
        r = self.as_user(self.worker).post(reverse("wage-dispute-payment", args=[self.obligation.pk]),
                                           {"description": "لم يصلني شيء"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.obligation.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.DISPUTED)


class ManualModeTests(PaymentTestBase):

    def test_screen_shows_wallet_and_amount_for_a_manual_transfer(self):
        r = self.info()
        self.assertEqual((r.data["mode"], r.data["worker_wallet"], r.data["amount_display"], r.data["needs_wallet"]),
                         ("manual", self.worker.phone, "٨٥ ₪", False))
        self.assertEqual(self.initiate().status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(PaymentAttempt.objects.exists())

    def test_manual_confirmation_keeps_the_workers_acknowledgement(self):
        r = self.as_user(self.biz_user).post(reverse("wage-declare-payment", args=[self.obligation.pk]),
                                             {"transaction_reference": "JP-777", "declared_amount": 1}, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED, r.data)
        declaration = PaymentDeclaration.objects.get(wage_obligation=self.obligation)
        self.assertEqual((declaration.declared_amount, declaration.provider_confirmed), (8500, False))
        PaymentDeclaration.objects.filter(pk=declaration.pk).update(
            declared_at=timezone.now() - datetime.timedelta(days=3))
        self.as_user(self.worker).get(reverse("wage-list"))
        self.obligation.refresh_from_db()
        self.assertEqual(self.obligation.status, WageObligationStatus.AWAITING_ACK)
        self.assertTrue(AuditEvent.objects.filter(action="payment_declared").exists())


class BusinessWalletTests(APITestCase):

    def setUp(self):
        self.biz_user, self.biz_profile = make_business("+970599030011")
        self.client.force_authenticate(user=self.biz_user)

    def test_wallet_is_validated_normalised_and_audited(self):
        url = reverse("business-profile-alt")
        r = self.client.patch(url, {"jawwal_pay_wallet": "12345"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
        r = self.client.patch(url, {"jawwal_pay_wallet": "0599123456"}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.biz_profile.refresh_from_db()
        self.assertEqual(self.biz_profile.jawwal_pay_wallet, "+970599123456")
        event = AuditEvent.objects.get(action="business_wallet_changed")
        self.assertEqual(event.details, {"from": "", "to": "…3456"})
