"""Observer role: read-only, least privilege, visibility levels, scope, expiry, audit, no mobile sign-in."""
import datetime
import io
import re
import time
import uuid
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver, resolve, reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import BusinessProfile, Role, User, WorkerProfile
from assignments.models import Assignment, AssignmentStatus, CompletionRecord, CompletionStatus
from audit.models import AuditEvent
from disputes.models import Dispute, DisputeCategory
from jobs.models import ApplicationStatus, JobApplication, JobListing, JobListingStatus
from observers import metrics
from observers.models import ObserverLevel, ObserverProfile, ObserverScope, Pseudonym, PseudonymKind
from observers.services import create_observer
from observers.tokens import observer_password_token
from wages.models import PaymentDeclaration, PaymentDeclarationStatus, WageObligation, WageObligationStatus

GAZA = ZoneInfo("Asia/Gaza")
PASSWORD = "Observer-Pass-2026!"

# Everything that must never reach an observer.
PHONES = ["+970599111001", "+970599111002", "+970599111003", "+970599111004", "0599111001", "0599111002",
          "0599111003", "0599111004", "0599111009", "599111"]
DISPUTE_TEXT = "تفاصيل سرية في سبب النزاع"
FULL_REFERENCE = "JP-99887766"


def at(day, hour):
    return datetime.datetime(2026, 12, day, hour, 0, tzinfo=GAZA)


def make_business(phone, name, contact_phone):
    user = User.objects.create_user(phone, "Biz-Pass-123", role=Role.BUSINESS)
    return BusinessProfile.objects.create(user=user, legal_name=name, contact_name="المالك",
                                          contact_phone=contact_phone, verification_status="APPROVED")


def make_worker(phone, name):
    user = User.objects.create_user(phone, "Wrk-Pass-123", role=Role.WORKER)
    WorkerProfile.objects.create(user=user, full_name=name, national_id_hash="a" * 64)
    return user


def make_job(business, title, work_day, published):
    job = JobListing.objects.create(
        business=business, title=title, description="d", location_address="عنوان", location_city="غزة",
        work_date=work_day, start_time="08:00", end_time="16:00", num_workers_needed=1, wage_amount=5000,
        wage_currency="ILS", wage_basis="PER_DAY", payment_method="JAWWAL_PAY", status=JobListingStatus.FILLED,
    )
    JobListing.objects.filter(pk=job.pk).update(published_at=published)
    return job


def make_paid_task(job, worker, accepted, completed, declared, reference="", acknowledged=None):
    app = JobApplication.objects.create(job=job, worker=worker, status=ApplicationStatus.ACCEPTED)
    task = Assignment.objects.create(job=job, worker=worker, application=app, terms_snapshot={},
                                     status=AssignmentStatus.COMPLETED, accepted_at=accepted)
    CompletionRecord.objects.create(assignment=task, submitted_by=worker, status=CompletionStatus.CONFIRMED,
                                    confirmed_at=completed)
    wage = WageObligation.objects.create(assignment=task, amount=5000, currency="ILS", due_date=job.work_date,
                                         status=WageObligationStatus.VERIFIED_PAID if acknowledged else WageObligationStatus.AWAITING_ACK)
    decl = PaymentDeclaration.objects.create(
        wage_obligation=wage, declared_amount=5000, currency="ILS", payment_date=job.work_date,
        payment_method="JAWWAL_PAY", transaction_reference=reference, declared_by=job.business.user,
        status=PaymentDeclarationStatus.ACKNOWLEDGED if acknowledged else PaymentDeclarationStatus.SUBMITTED,
    )
    PaymentDeclaration.objects.filter(pk=decl.pk).update(declared_at=declared)
    if acknowledged:
        ev = AuditEvent.objects.create(actor=worker, action="payment_acknowledged", model_name="WageObligation",
                                       object_id=str(wage.pk))
        AuditEvent.objects.filter(pk=ev.pk).update(timestamp=acknowledged)
    return task


class ObserverTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.biz_a = make_business("+970599111001", "مخبز السعادة", "0599111009")
        cls.biz_b = make_business("+970599111002", "مزرعة الخير", "0599111009")
        cls.w1 = make_worker("+970599111003", "سامي الأحمد")
        cls.w2 = make_worker("+970599111004", "ليلى حسن")
        a1 = make_job(cls.biz_a, "خبّاز صباحي — مخبز السعادة", datetime.date(2026, 12, 2), at(1, 9))
        make_job(cls.biz_a, "تنظيف المخبز", datetime.date(2026, 12, 9), at(8, 9))  # second week: posted again
        b1 = make_job(cls.biz_b, "قطف زيتون", datetime.date(2026, 12, 3), at(2, 9))
        make_job(cls.biz_a, "قبل التجربة", datetime.date(2026, 11, 21), datetime.datetime(2026, 11, 20, 9, tzinfo=GAZA))
        # Paid on the work day (Dec 2) and confirmed by the worker; 3 hours from completion to payment.
        make_paid_task(a1, cls.w1, at(1, 12), at(2, 15), at(2, 18), reference=FULL_REFERENCE, acknowledged=at(2, 20))
        # Paid the next day, not confirmed; 18 hours from completion to payment; then disputed.
        task_b = make_paid_task(b1, cls.w2, at(2, 12), at(3, 16), at(4, 10))
        dispute = Dispute.objects.create(category=DisputeCategory.PAYMENT_NOT_RECEIVED, assignment=task_b,
                                         wage_obligation=task_b.wage_obligation, raised_by=cls.w2,
                                         description=DISPUTE_TEXT)
        Dispute.objects.filter(pk=dispute.pk).update(created_at=at(5, 9))

    def setUp(self):
        # "Today" is 5 December 2026: the job on 9 December is in the future and must still count.
        patcher = mock.patch("django.utils.timezone.localdate", return_value=datetime.date(2026, 12, 5))
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_observer(self, level=ObserverLevel.NAMED, lang="ar", business_ids=None, start=None, end=None,
                      expires=datetime.date(2027, 3, 1), email=None):
        profile, link = create_observer(
            name="مراقب", organisation="Tech for Palestine", email=email or f"{uuid.uuid4().hex[:8]}@example.org",
            level=level, language=lang, expires_at=expires, business_ids=business_ids, start_date=start, end_date=end,
        )
        profile.user.set_password(PASSWORD)
        profile.user.save()
        return profile

    def signed_in(self, profile):
        client = self.client_class()
        r = client.post(reverse("observers:login"), {"email": profile.user.email, "password": PASSWORD})
        self.assertEqual(r.status_code, 302, getattr(r, "content", b"")[:300])
        return client

    def dashboard(self, client, query=""):
        r = client.get(reverse("observers:dashboard") + query)
        return r.status_code, r.content.decode()


def summary_for(profile, start=None, end=None, q=""):
    f = metrics.filters_for(profile.scope, start, end, q)
    return metrics.summary(metrics.Records(profile.scope, f))


class SummaryTests(ObserverTestBase):
    def test_default_counts_everything_by_status(self):
        n = summary_for(self.make_observer())
        self.assertEqual(n["businesses"], {"total": 2, "verified": 2, "pending": 0})
        self.assertEqual(n["workers"], {"total": 2, "verified": 0, "pending": 2})
        self.assertEqual(n["jobs"]["total"], 4)  # November, December and the future 9 December job
        self.assertEqual(n["jobs"]["by_status"]["FILLED"], 4)
        self.assertEqual(n["jobs"]["upcoming"], 1)
        self.assertEqual(sum(n["jobs"]["by_status"].values()), 4)
        self.assertEqual((n["tasks"]["total"], n["tasks"]["by_status"]["COMPLETED"]), (2, 2))
        self.assertEqual((n["wages"]["by_status"]["VERIFIED_PAID"], n["wages"]["by_status"]["AWAITING_ACK"]), (1, 1))
        self.assertEqual((n["payments_declared"], n["receipts_confirmed"]), (2, 1))
        self.assertEqual((n["disputes"]["total"], n["disputes"]["by_status"]["OPEN"]), (1, 1))

    def test_dates_filter_each_record_by_its_own_date(self):
        profile = self.make_observer()
        self.assertEqual(summary_for(profile, "2026-12-01", "2026-12-24")["jobs"]["total"], 3)  # by work date
        self.assertEqual(summary_for(profile, "2026-12-08")["jobs"]["total"], 1)  # only the future job
        self.assertEqual(summary_for(profile, None, "2026-11-30")["jobs"]["total"], 1)

    def test_search_by_business_worker_or_job_title(self):
        profile = self.make_observer()
        by_business = summary_for(profile, q="مخبز السعادة")
        self.assertEqual((by_business["businesses"]["total"], by_business["jobs"]["total"],
                          by_business["wages"]["total"]), (1, 3, 1))
        by_worker = summary_for(profile, q="ليلى")
        self.assertEqual((by_worker["workers"]["total"], by_worker["tasks"]["total"], by_worker["jobs"]["total"],
                          by_worker["disputes"]["total"]), (1, 1, 1, 1))
        self.assertEqual(summary_for(profile, q="قطف")["jobs"]["total"], 1)

    def test_is_test_has_no_effect(self):
        BusinessProfile.objects.filter(pk=self.biz_b.pk).update(is_test=True)
        n = summary_for(self.make_observer())
        self.assertEqual((n["businesses"]["total"], n["jobs"]["total"], n["disputes"]["total"]), (2, 4, 1))


class DashboardTests(ObserverTestBase):
    def assert_never_leaks(self, body):
        for phone in PHONES:
            self.assertNotIn(phone, body)
        self.assertNotIn(DISPUTE_TEXT, body)
        self.assertNotIn(FULL_REFERENCE, body)
        self.assertNotIn("7766", body)
        self.assertNotIn("a" * 64, body)  # national ID hash

    def test_named_by_default_shows_names_and_lists_but_never_phones(self):
        status, body = self.dashboard(self.signed_in(self.make_observer()))
        self.assertEqual(status, 200)
        for name in ("مخبز السعادة", "مزرعة الخير", "سامي الأحمد", "ليلى حسن", "قطف زيتون"):
            self.assertIn(name, body)
        self.assertIn("كل البيانات", body)
        self.assertIn('name="q"', body)
        self.assert_never_leaks(body)

    def test_every_business_and_future_jobs_are_listed(self):
        make_business("+970599111005", "منشأة سجّلت اليوم", "0599111009")
        _, body = self.dashboard(self.signed_in(self.make_observer()))
        self.assertIn("منشأة سجّلت اليوم", body)  # no jobs yet
        self.assertIn("2026-12-09", body)  # a job dated after today

    def test_filter_bar_without_quick_buttons(self):
        client = self.signed_in(self.make_observer())
        _, body = self.dashboard(client)
        for gone in ("كل الفترة", "فترة التجربة", "آخر ٤ أسابيع"):
            self.assertNotIn(gone, body)
        self.assertNotIn('href="?">مسح', body)
        _, body = self.dashboard(client, "?from=2026-12-08&q=تنظيف")
        self.assertIn('href="?">مسح', body)
        self.assertIn('value="تنظيف"', body)
        self.assertIn("تنظيف المخبز", body)
        self.assertNotIn("قطف زيتون", body)

    def test_pseudonymised_level_still_hides_names(self):
        _, body = self.dashboard(self.signed_in(self.make_observer(ObserverLevel.PSEUDONYMISED, lang="en")))
        self.assertIn("Business #", body)
        self.assertIn("Worker #", body)
        for secret in ("مخبز السعادة", "مزرعة الخير", "سامي الأحمد", "ليلى حسن", "قطف زيتون"):
            self.assertNotIn(secret, body)
        self.assertNotIn('name="q"', body)  # searching by name would reveal names
        self.assert_never_leaks(body)

    def test_aggregate_level_shows_the_summary_only(self):
        _, body = self.dashboard(self.signed_in(self.make_observer(ObserverLevel.AGGREGATE)))
        self.assertIn("الملخّص", body)
        for secret in ("مخبز السعادة", "سامي الأحمد", "منشأة #", "عامل #"):
            self.assertNotIn(secret, body)

    def test_new_and_existing_observers_are_named(self):
        import importlib
        from django.apps import apps as django_apps
        call_command("create_observer", "--name", "N", "--org", "T4P", "--email", "n@example.org",
                     "--expires", "2027-03-01", stdout=io.StringIO())
        self.assertEqual(ObserverProfile.objects.get(user__email="n@example.org").level, ObserverLevel.NAMED)
        old = self.make_observer(ObserverLevel.PSEUDONYMISED)
        importlib.import_module("observers.migrations.0002_named_by_default").switch_to_named(django_apps, None)
        old.refresh_from_db()
        self.assertEqual(old.level, ObserverLevel.NAMED)

    def test_pseudonyms_are_random_stored_once_and_shared(self):
        self.dashboard(self.signed_in(self.make_observer(ObserverLevel.PSEUDONYMISED)))
        first = dict(Pseudonym.objects.filter(kind=PseudonymKind.BUSINESS).values_list("object_id", "number"))
        self.dashboard(self.signed_in(self.make_observer(ObserverLevel.PSEUDONYMISED)))
        again = dict(Pseudonym.objects.filter(kind=PseudonymKind.BUSINESS).values_list("object_id", "number"))
        self.assertEqual(first, again)
        self.assertEqual(set(first), {str(self.biz_a.pk), str(self.biz_b.pk)})


class ScopeTests(ObserverTestBase):
    def test_business_scope(self):
        profile = self.make_observer(business_ids=[self.biz_b.pk])
        n = summary_for(profile)
        self.assertEqual((n["businesses"]["total"], n["jobs"]["total"], n["disputes"]["total"], n["workers"]["total"]),
                         (1, 1, 1, 1))
        _, body = self.dashboard(self.signed_in(profile))
        self.assertIn("مزرعة الخير", body)
        self.assertNotIn("مخبز السعادة", body)

    def test_scope_dates_limit_whatever_is_picked(self):
        profile = self.make_observer(start=datetime.date(2026, 12, 3))
        f = metrics.filters_for(profile.scope, "2026-11-01", "2026-12-24")
        self.assertEqual(f.start, datetime.date(2026, 12, 3))
        self.assertEqual(summary_for(profile)["jobs"]["total"], 2)  # work dates 3 and 9 December
        _, body = self.dashboard(self.signed_in(profile), "?from=2026-11-01")
        self.assertIn('value="2026-12-03"', body)


class AccessTests(ObserverTestBase):
    def test_expired_observer_cannot_sign_in(self):
        profile = self.make_observer(expires=datetime.date(2026, 1, 1))
        r = self.client.post(reverse("observers:login"), {"email": profile.user.email, "password": PASSWORD})
        self.assertEqual(r.status_code, 401)

    def test_inactive_observer_cannot_sign_in_and_is_signed_out(self):
        profile = self.make_observer()
        client = self.signed_in(profile)
        User.objects.filter(pk=profile.user.pk).update(is_active=False)
        r = client.get(reverse("observers:dashboard"))
        self.assertRedirects(r, reverse("observers:login"), fetch_redirect_response=False)
        r = self.client.post(reverse("observers:login"), {"email": profile.user.email, "password": PASSWORD})
        self.assertEqual(r.status_code, 401)

    def test_expiry_during_a_session_signs_out(self):
        profile = self.make_observer()
        client = self.signed_in(profile)
        ObserverProfile.objects.filter(pk=profile.pk).update(expires_at=datetime.date(2026, 1, 1))
        self.assertEqual(client.get(reverse("observers:dashboard")).status_code, 302)

    def test_session_ends_after_4_hours(self):
        client = self.signed_in(self.make_observer())
        session = client.session
        session["observer_login_at"] = time.time() - 4 * 3600 - 1
        session.save()
        self.assertEqual(client.get(reverse("observers:dashboard")).status_code, 302)

    def test_dashboard_pages_carry_noindex(self):
        r = self.signed_in(self.make_observer()).get(reverse("observers:dashboard"))
        self.assertEqual(r["X-Robots-Tag"], "noindex, nofollow")
        self.assertIn('<meta name="robots" content="noindex, nofollow">', r.content.decode())
        self.assertEqual(self.client.get(reverse("observers:login"))["X-Robots-Tag"], "noindex, nofollow")


def api_routes():
    """Every route under /api/v1/ with sample values for its parameters."""
    def walk(patterns, prefix):
        for p in patterns:
            route = prefix + str(p.pattern)
            if isinstance(p, URLResolver):
                yield from walk(p.url_patterns, route)
            elif isinstance(p, URLPattern):
                yield route
    for route in walk(get_resolver().url_patterns, "/"):
        if not route.startswith("/api/v1/"):
            continue
        route = re.sub(r"<uuid:\w+>", str(uuid.uuid4()), route)
        route = re.sub(r"<int:\w+>", "1", route)
        route = re.sub(r"<(?:str|slug|path):\w+>|<\w+>", "x", route)
        yield route


class ReadOnlyTests(ObserverTestBase):
    def test_observer_token_gets_403_on_every_api_endpoint(self):
        profile = self.make_observer(ObserverLevel.NAMED)
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(profile.user).access_token}")
        checked, public = 0, []
        for route in api_routes():
            view_class = getattr(resolve(route).func, "cls", None)
            if view_class is None or not view_class.authentication_classes:
                public.append(route)  # sign-in, token refresh, app config, health: no identity is used
                continue
            for method in ("post", "put", "patch", "delete"):
                r = getattr(api, method)(route, {}, format="json")
                self.assertIn(r.status_code, (403, 405), f"{method.upper()} {route} → {r.status_code}")
                checked += 1
        self.assertGreater(checked, 100)
        self.assertTrue(all(r.startswith(("/api/v1/auth/", "/api/v1/app/", "/api/v1/health/")) for r in public), public)
        writes = AuditEvent.objects.exclude(action__startswith="observer_")
        self.assertFalse(writes.filter(actor=profile.user).exists())

    def test_observer_session_is_refused_outside_the_dashboard(self):
        client = self.signed_in(self.make_observer(ObserverLevel.NAMED))
        for path in ("/api/v1/jobs/", "/api/v1/admin/reports/pilot-summary/", "/django-admin/",
                     "/django-admin/observers/observerprofile/"):
            self.assertEqual(client.get(path).status_code, 403, path)
            self.assertEqual(client.post(path, {}).status_code, 403, path)

    def test_dashboard_refuses_every_write(self):
        client = self.signed_in(self.make_observer(ObserverLevel.NAMED))
        for method in ("post", "put", "patch", "delete"):
            r = getattr(client, method)(reverse("observers:dashboard"))
            self.assertEqual(r.status_code, 403, method)


class MobileAppTests(ObserverTestBase):
    def test_observer_cannot_get_an_app_token(self):
        profile = self.make_observer()
        api = APIClient()
        self.assertEqual(api.post("/api/v1/auth/login/", {"phone": profile.user.phone, "password": PASSWORD},
                                  format="json").status_code, 401)
        self.assertEqual(api.post("/api/v1/auth/login/", {"phone": profile.user.email, "password": PASSWORD},
                                  format="json").status_code, 401)
        # Even an observer that somehow had a real phone number is refused by the app login.
        User.objects.filter(pk=profile.user.pk).update(phone="+970599111077")
        self.assertEqual(api.post("/api/v1/auth/login/", {"phone": "0599111077", "password": PASSWORD},
                                  format="json").status_code, 401)

    def test_observers_cannot_self_register(self):
        r = APIClient().post("/api/v1/auth/register/", {"phone": "0599111088", "password": "Strong-Pass-123",
                                                        "role": "OBSERVER", "consent_version": 1}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(User.objects.filter(role=Role.OBSERVER, phone="+970599111088").exists())


class AuditTests(ObserverTestBase):
    def test_sign_in_and_every_view_with_its_filters_is_audited(self):
        profile = self.make_observer()
        client = self.signed_in(profile)
        self.dashboard(client)
        self.dashboard(client, "?from=2026-12-01&q=مخبز")
        actions = list(AuditEvent.objects.filter(actor=profile.user).values_list("action", flat=True))
        self.assertIn("observer_login", actions)
        self.assertEqual(actions.count("observer_view"), 2)
        filtered = AuditEvent.objects.get(actor=profile.user, action="observer_view", details__q="مخبز")
        self.assertEqual((filtered.details["page"], filtered.details["from"]), ("dashboard", "2026-12-01"))

    def test_failed_sign_ins_are_audited_and_rate_limited(self):
        profile = self.make_observer()
        url = reverse("observers:login")
        for _ in range(5):
            self.assertEqual(self.client.post(url, {"email": profile.user.email, "password": "wrong"}).status_code, 401)
        self.assertEqual(AuditEvent.objects.filter(action="observer_login_failed").count(), 5)
        r = self.client.post(url, {"email": profile.user.email, "password": PASSWORD})  # right password, still locked
        self.assertEqual(r.status_code, 429)
        self.assertTrue(AuditEvent.objects.filter(action="observer_login_blocked").exists())
        # Another email from the same IP is locked too.
        other = self.make_observer()
        self.assertEqual(self.client.post(url, {"email": other.user.email, "password": PASSWORD}).status_code, 429)


class AccountTests(ObserverTestBase):
    def test_set_password_link_is_one_time_and_needs_a_strong_password(self):
        profile, link = create_observer(name="T", organisation="Wathb team", email="t@example.org",
                                        level=ObserverLevel.AGGREGATE, language="ar",
                                        expires_at=datetime.date(2027, 1, 1))
        self.assertFalse(profile.user.has_usable_password())
        path = link.split("onrender.com", 1)[-1]
        self.assertEqual(self.client.get(path).status_code, 200)
        weak = self.client.post(path, {"password": "short1", "password2": "short1"})
        self.assertEqual(weak.status_code, 400)
        r = self.client.post(path, {"password": PASSWORD, "password2": PASSWORD})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.get(path).status_code, 400)  # used: dead
        self.assertTrue(AuditEvent.objects.filter(action="observer_password_set").exists())

    def test_set_password_link_expires_after_48_hours(self):
        profile, _ = create_observer(name="T", organisation="Wathb team", email="t2@example.org",
                                     level=ObserverLevel.AGGREGATE, language="ar", expires_at=datetime.date(2027, 1, 1))
        token = observer_password_token.make_token(profile.user)
        later = datetime.datetime.now() + datetime.timedelta(hours=48, minutes=1)
        with mock.patch.object(type(observer_password_token), "_now", return_value=later):
            self.assertFalse(observer_password_token.check_token(profile.user, token))
        self.assertTrue(observer_password_token.check_token(profile.user, token))

    def test_create_observer_command_prints_the_link_and_no_password(self):
        out = io.StringIO()
        call_command("create_observer", "--name", "Partner", "--org", "Tech for Palestine", "--email",
                     "partner@example.org", "--level", "aggregate", "--lang", "en", "--expires", "2027-03-01",
                     stdout=out)
        text = out.getvalue()
        self.assertIn("/observer/set-password/", text)
        self.assertNotIn("password=", text.lower())
        user = User.objects.get(email="partner@example.org")
        self.assertEqual(user.role, Role.OBSERVER)
        self.assertFalse(user.has_usable_password())
        self.assertTrue(user.phone.startswith("observer-"))

    def test_update_observer_command_extends_and_deactivates(self):
        profile = self.make_observer(email="u@example.org")
        call_command("update_observer", "--email", "u@example.org", "--extend", "2027-06-01", "--deactivate",
                     stdout=io.StringIO())
        profile.refresh_from_db()
        profile.user.refresh_from_db()
        self.assertEqual(profile.expires_at, datetime.date(2027, 6, 1))
        self.assertFalse(profile.user.is_active)
        self.assertFalse(profile.is_usable)
