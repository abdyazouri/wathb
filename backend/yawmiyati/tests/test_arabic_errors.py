import ast
import datetime
import re
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.db import models
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import translation
from rest_framework import exceptions, fields
from rest_framework.test import APITestCase

from accounts.models import BusinessProfile, Role, User, WorkerProfile
from yawmiyati.exception_handler import custom_exception_handler

ARABIC = re.compile(r"[؀-ۿ]")


def assert_arabic(test, text):
    test.assertRegex(str(text), ARABIC, msg=f"not Arabic: {text!r}")


class ApiErrorsAreArabicTests(APITestCase):
    """/api/ errors are Arabic whatever the client's Accept-Language."""

    def test_unauthenticated_detail_is_arabic_even_for_english_clients(self):
        response = self.client.get(reverse("auth-me"), HTTP_ACCEPT_LANGUAGE="en")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["detail"], "لم يتم تزويد بيانات الدخول.")
        self.assertEqual(response["Content-Language"], "ar")

    def test_validation_errors_are_arabic(self):
        response = self.client.post(reverse("auth-register"), {}, format="json", HTTP_ACCEPT_LANGUAGE="en")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["error"], "validation_error")
        self.assertEqual(response.data["detail"], "بعض الحقول غير صالحة.")
        self.assertEqual(response.data["fields"]["password"], ["هذا الحقل مطلوب."])

    def test_register_role_and_profile_messages_are_arabic(self):
        body = {"phone": "0599050001", "password": "Str0ng-Pass!", "role": "WORKER", "consent_version": 1}
        response = self.client.post(reverse("auth-register"), body, format="json")
        self.assertEqual(response.status_code, 400)
        assert_arabic(self, response.data["fields"]["full_name"][0])
        body.update(role="ADMIN")
        response = self.client.post(reverse("auth-register"), body, format="json")
        assert_arabic(self, response.data["fields"]["role"][0])

    def test_register_duplicate_email_is_arabic(self):
        User.objects.create_user("0599050002", "P@ss1234", role=Role.WORKER, email="taken@example.com")
        body = {
            "phone": "0599050003", "password": "Str0ng-Pass!", "role": "WORKER",
            "consent_version": 1, "full_name": "عامل", "email": "taken@example.com",
        }
        response = self.client.post(reverse("auth-register"), body, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["fields"]["email"], ["البريد الإلكتروني هذا مسجّل مسبقاً."])

    def test_wrong_login_is_arabic(self):
        User.objects.create_user("0599050004", "P@ss1234", role=Role.WORKER)
        response = self.client.post(
            reverse("auth-login"), {"phone": "0599050004", "password": "wrong"}, HTTP_ACCEPT_LANGUAGE="en"
        )
        self.assertEqual(response.status_code, 401)
        assert_arabic(self, response.data["detail"])

    def test_invalid_token_is_arabic(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer not-a-token")
        response = self.client.get(reverse("auth-me"), HTTP_ACCEPT_LANGUAGE="en")
        self.assertEqual(response.status_code, 401)
        assert_arabic(self, response.data["detail"])

    def test_role_permission_denied_is_arabic(self):
        worker = User.objects.create_user("0599050005", "P@ss1234", role=Role.WORKER)
        self.client.force_authenticate(user=worker)
        response = self.client.get(reverse("business-profile-alt"))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["detail"], "ليس لديك صلاحية للقيام بهذا الإجراء.")

    def test_unknown_api_url_returns_arabic_json(self):
        response = self.client.get("/api/v1/does-not-exist/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "غير موجود.")

    def test_me_patch_duplicate_phone_is_arabic_400(self):
        User.objects.create_user("0599050006", "P@ss1234", role=Role.WORKER)
        me = User.objects.create_user("0599050007", "P@ss1234", role=Role.WORKER)
        self.client.force_authenticate(user=me)
        response = self.client.patch(reverse("auth-me"), {"phone": "0599050006"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["phone"], "رقم الهاتف هذا مسجّل مسبقاً.")

    def test_status_in_messages_uses_arabic_label(self):
        biz = User.objects.create_user("0599050008", "P@ss1234", role=Role.BUSINESS, is_verified=True)
        bp = BusinessProfile.objects.create(
            user=biz, legal_name="منشأة", contact_name="مالك", contact_phone="0599000000",
            verification_status="APPROVED",
        )
        from jobs.models import JobListing
        job = JobListing.objects.create(
            business=bp, title="t", description="d", location_address="a", location_city="غزة",
            work_date=datetime.date.today(), start_time="08:00", end_time="10:00",
            wage_amount=1000, payment_method="PALPAY",
        )
        self.client.force_authenticate(user=biz)
        response = self.client.post(reverse("job-publish", args=[job.pk]))
        self.assertEqual(response.data["detail"], "لا يمكن نشر وظيفة حالتها «مسودة».")
        self.assertNotIn("DRAFT", response.data["detail"])

    def test_wage_display_basis_is_arabic(self):
        from jobs.models import JobListing
        from jobs.serializers import JobListingSerializer
        user = User.objects.create_user("0599050009", "P@ss1234", role=Role.BUSINESS)
        bp = BusinessProfile.objects.create(user=user, legal_name="م", contact_name="م", contact_phone="0")
        job = JobListing(business=bp, wage_amount=25000, wage_basis="PER_DAY")
        self.assertEqual(JobListingSerializer().get_wage_display(job), "٢٥٠ ₪ / يوم")


class ExceptionHandlerTests(SimpleTestCase):

    def _handle(self, exc):
        return custom_exception_handler(exc, {"view": None, "request": None})

    def test_throttled_wait_is_arabic(self):
        response = self._handle(exceptions.Throttled(wait=12))
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data["detail"], "تم تقييد الطلب. الرجاء المحاولة بعد 12 ثانية.")

    def test_bare_validation_error_returns_its_message(self):
        response = self._handle(exceptions.ValidationError("يمكن حذف المسودات فقط."))
        self.assertEqual(response.data["detail"], "يمكن حذف المسودات فقط.")

    def test_english_detail_falls_back_to_arabic(self):
        with self.assertLogs("yawmiyati.exception_handler", level="WARNING"):
            response = self._handle(exceptions.PermissionDenied("Some English message."))
        self.assertEqual(response.data["detail"], "ليس لديك صلاحية للقيام بهذا الإجراء.")

    def test_english_field_error_falls_back_to_arabic(self):
        with self.assertLogs("yawmiyati.exception_handler", level="WARNING"):
            response = self._handle(exceptions.ValidationError({"x": ["English only."], "y": ["هذا الحقل مطلوب."]}))
        self.assertEqual(response.data["fields"], {"x": ["قيمة غير صالحة."], "y": ["هذا الحقل مطلوب."]})


class ArabicCatalogTests(SimpleTestCase):
    """The project catalog fills gaps in DRF's built-in 'ar' translation."""

    def test_project_catalog_gap_strings(self):
        with translation.override("ar"):
            with self.assertRaises(exceptions.ValidationError) as ctx:
                fields.UUIDField().run_validation("nope")
            assert_arabic(self, ctx.exception.detail[0])
            assert_arabic(self, exceptions.ValidationError().detail[0])
            assert_arabic(self, str(fields.Field.default_error_messages["null"]))


class EnumLabelsAreArabicTests(SimpleTestCase):

    def test_every_project_choice_label_is_arabic(self):
        project_apps = {"accounts", "jobs", "assignments", "wages", "disputes", "funding", "notifications"}
        checked = 0
        for model in apps.get_models():
            if model._meta.app_label not in project_apps:
                continue
            for field in model._meta.get_fields():
                for value, label in getattr(field, "choices", None) or []:
                    assert_arabic(self, label)
                    checked += 1
        self.assertGreater(checked, 50)


class NoEnglishErrorLiteralsTests(SimpleTestCase):
    """Static guard: hard-coded API error messages must contain Arabic."""

    APPS = ["accounts", "assignments", "disputes", "funding", "jobs", "notifications", "wages", "reporting", "audit"]

    def _literal_text(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            return "".join(v.value for v in node.values if isinstance(v, ast.Constant))
        return None

    def test_detail_and_validation_messages_are_arabic(self):
        offenders = []
        base = Path(settings.BASE_DIR)
        for app in self.APPS:
            for name in ("views.py", "serializers.py", "permissions.py"):
                path = base / app / name
                if not path.exists():
                    continue
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    texts = []
                    if isinstance(node, ast.Dict):
                        texts = [self._literal_text(v) for v in node.values]
                    elif isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", "")) in (
                        "ValidationError", "PermissionDenied", "NotFound",
                    ):
                        texts = [self._literal_text(a) for a in node.args]
                    for text in texts:
                        if text and re.search(r"[A-Za-z]{3,}", text) and not ARABIC.search(text):
                            offenders.append(f"{app}/{name}:{node.lineno}: {text!r}")
        # Dict literals also hold non-message data; only flag sentences.
        offenders = [o for o in offenders if re.search(r"[A-Za-z]+ [A-Za-z]+", o.split(": ", 1)[1])]
        self.assertEqual(offenders, [])
