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


@override_settings(TRIAL_START_DATE="2026-12-01", TRIAL_END_DATE="2026-12-24")
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

    def make_observer(self, level=ObserverLevel.PSEUDONYMISED, lang="ar", business_ids=None, start=None, end=None,
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

    def pages(self, client):
        out = {}
        for name in ("overview", "businesses", "activity", "export"):
            r = client.get(reverse(f"observers:{name}"))
            out[name] = (r.status_code, r.content.decode())
        return out


class MetricsTests(ObserverTestBase):
    def test_default_counts_everything_by_status_with_no_date_range(self):
        profile = self.make_observer(ObserverLevel.AGGREGATE)
        period, all_time = metrics.period_for(profile.scope)
        self.assertTrue(all_time)
        self.assertEqual((period.start, period.end), (None, None))
        n = metrics.compute(metrics.Scope(profile.scope), period)
        self.assertEqual(n["businesses"]["total"], 2)
        self.assertEqual(n["businesses"]["by_status"]["APPROVED"], 2)
        self.assertEqual((n["workers"]["total"], n["workers"]["verified"], n["workers"]["pending"]), (2, 0, 2))
        self.assertEqual(n["jobs"]["total"], 4)  # November, December and the future 9 December job
        self.assertEqual(n["jobs"]["by_status"]["FILLED"], 4)
        self.assertEqual(n["jobs"]["upcoming"], 1)
        self.assertEqual(sum(n["jobs"]["by_status"].values()), n["jobs"]["total"])
        self.assertEqual(n["applications"]["by_status"]["ACCEPTED"], 2)
        self.assertEqual(n["tasks"]["by_status"]["COMPLETED"], 2)
        self.assertEqual((n["wages"]["by_status"]["VERIFIED_PAID"], n["wages"]["by_status"]["AWAITING_ACK"]), (1, 1))
        self.assertEqual((n["disputes"]["total"], n["disputes"]["by_status"]["OPEN"]), (1, 1))
        self.assertEqual((n["work_days_completed"], n["payments_declared"], n["receipts_confirmed"]), (2, 2, 1))
        self.assertEqual(n["businesses_posted_again"], 1)
        self.assertEqual((n["paid_same_day_pct"], n["confirmed_by_workers_pct"]), (50, 50))
        self.assertEqual(n["median_hours_to_payment"], 10.5)

    def test_dates_filter_only_when_picked(self):
        profile = self.make_observer(ObserverLevel.AGGREGATE)
        period, all_time = metrics.period_for(profile.scope, "2026-12-01", "2026-12-24")
        self.assertFalse(all_time)
        n = metrics.compute(metrics.Scope(profile.scope), period)
        self.assertEqual(n["jobs"]["total"], 3)  # by work date; the 21 November job is out
        self.assertEqual(n["businesses_posted_again"], 1)
        # Either date alone.
        self.assertEqual(metrics.period_for(profile.scope, "2026-12-08")[0], metrics.Period(datetime.date(2026, 12, 8)))
        later = metrics.compute(metrics.Scope(profile.scope), metrics.period_for(profile.scope, "2026-12-08")[0])
        self.assertEqual(later["jobs"]["total"], 1)  # only the future 9 December job

    def test_test_businesses_count_like_any_other(self):
        BusinessProfile.objects.filter(pk=self.biz_b.pk).update(is_test=True)
        profile = self.make_observer(ObserverLevel.NAMED)
        n = metrics.compute(metrics.Scope(profile.scope), metrics.Period())
        self.assertEqual((n["businesses"]["total"], n["jobs"]["total"], n["disputes"]["total"]), (2, 4, 1))
        self.assertIn("مزرعة الخير", self.signed_in(profile).get(reverse("observers:businesses")).content.decode())

    @override_settings(TRIAL_START_DATE="", TRIAL_END_DATE="")
    def test_trial_quick_filter_only_when_the_dates_are_set(self):
        self.assertIsNone(metrics.trial_period())
        body = self.signed_in(self.make_observer()).get(reverse("observers:overview")).content.decode()
        self.assertNotIn("فترة التجربة", body)


class VisibilityTests(ObserverTestBase):
    def assert_never_leaks(self, pages):
        for name, (_, body) in pages.items():
            for phone in PHONES:
                self.assertNotIn(phone, body, f"phone {phone} on {name}")
            self.assertNotIn(DISPUTE_TEXT, body, name)
            self.assertNotIn(FULL_REFERENCE, body, name)
            self.assertNotIn("a" * 64, body, name)  # national ID hash

    def test_aggregate_sees_numbers_only(self):
        pages = self.pages(self.signed_in(self.make_observer(ObserverLevel.AGGREGATE)))
        self.assertEqual(pages["overview"][0], 200)
        self.assertEqual(pages["businesses"][0], 403)
        self.assertEqual(pages["activity"][0], 403)
        self.assertEqual(pages["export"][0], 200)
        for _, body in pages.values():
            for secret in ("مخبز السعادة", "مزرعة الخير", "سامي الأحمد", "ليلى حسن", "عامل #", "منشأة #"):
                self.assertNotIn(secret, body)
        self.assert_never_leaks(pages)

    def test_pseudonymised_shows_numbers_instead_of_names(self):
        pages = self.pages(self.signed_in(self.make_observer(ObserverLevel.PSEUDONYMISED)))
        for name in ("businesses", "activity"):
            status, body = pages[name]
            self.assertEqual(status, 200)
            self.assertIn("منشأة #", body)
            for secret in ("مخبز السعادة", "مزرعة الخير", "سامي الأحمد", "ليلى حسن", "خبّاز صباحي", "…7766"):
                self.assertNotIn(secret, body, name)
        self.assertIn("عامل #", pages["activity"][1])
        self.assertIn("لم يُستلم الأجر", pages["activity"][1])  # the category, never the text
        self.assert_never_leaks(pages)

    def test_named_shows_names_but_no_phones(self):
        pages = self.pages(self.signed_in(self.make_observer(ObserverLevel.NAMED, lang="en")))
        body = pages["activity"][1]
        for name in ("مخبز السعادة", "مزرعة الخير", "سامي الأحمد", "ليلى حسن"):
            self.assertIn(name, body)
        self.assertIn("…7766", body)  # last 4 digits of the Jawwal Pay reference at most
        self.assertIn("Wage not received", body)
        self.assertIn('dir="ltr"', pages["overview"][1])
        self.assert_never_leaks(pages)

    def test_csv_has_aggregates_only_and_everything_by_default(self):
        client = self.signed_in(self.make_observer(ObserverLevel.NAMED))
        body = client.get(reverse("observers:export")).content.decode().lstrip("\ufeff")
        lines = body.strip().splitlines()
        self.assertTrue(lines[0].startswith("week_start,week_end,jobs,applications,tasks"))
        for expected in ("period,all to all", "businesses_total,2", "jobs_total,4", "jobs_filled,4", "jobs_upcoming,1",
                         "workers_total,2", "wages_verified_paid,1", "disputes_open,1", "paid_same_day_pct,50"):
            self.assertIn(expected, lines)
        for secret in ("مخبز", "مزرعة", "سامي", "ليلى", "7766"):
            self.assertNotIn(secret, body)
        filtered = client.get(reverse("observers:export") + "?from=2026-12-01&to=2026-12-24").content.decode()
        self.assertIn("jobs_total,3", filtered.splitlines())
        self.assertIn("period,2026-12-01 to 2026-12-24", filtered.splitlines())

    def test_every_business_and_every_event(self):
        make_business("+970599111005", "منشأة جديدة بلا وظائف", "0599111009")
        client = self.signed_in(self.make_observer(ObserverLevel.NAMED))
        self.assertIn("منشأة جديدة بلا وظائف", client.get(reverse("observers:businesses")).content.decode())
        activity = client.get(reverse("observers:activity")).content.decode()
        self.assertIn("سجّلت منشأة", activity)
        self.assertIn("يوم العمل 2026-12-09", activity)  # a job posted for a future work date

    def test_date_filter_controls(self):
        client = self.signed_in(self.make_observer())
        body = client.get(reverse("observers:overview")).content.decode()
        self.assertIn("كل الفترة", body)
        self.assertIn('name="from" value=""', body)
        self.assertIn('href="?from=2026-12-01&amp;to=2026-12-24"', body)  # trial period
        self.assertIn('href="?from=2026-11-08&amp;to=2026-12-05"', body)  # last 4 weeks
        self.assertNotIn("مسح التواريخ", body)
        body = client.get(reverse("observers:overview") + "?from=2026-12-01").content.decode()
        self.assertIn("مسح التواريخ", body)
        self.assertIn('name="from" value="2026-12-01"', body)
        self.assertIn('export.csv?from=2026-12-01"', body)

    def test_pseudonyms_are_random_stored_once_and_shared(self):
        self.pages(self.signed_in(self.make_observer(ObserverLevel.PSEUDONYMISED)))
        first = dict(Pseudonym.objects.filter(kind=PseudonymKind.BUSINESS).values_list("object_id", "number"))
        self.pages(self.signed_in(self.make_observer(ObserverLevel.PSEUDONYMISED)))
        again = dict(Pseudonym.objects.filter(kind=PseudonymKind.BUSINESS).values_list("object_id", "number"))
        self.assertEqual(first, again)
        self.assertEqual(set(first), {str(self.biz_a.pk), str(self.biz_b.pk)})
        self.assertEqual(len(set(first.values())), 2)


class ScopeTests(ObserverTestBase):
    def test_business_scope(self):
        profile = self.make_observer(ObserverLevel.NAMED, business_ids=[self.biz_b.pk])
        n = metrics.compute(metrics.Scope(profile.scope), metrics.period_for(profile.scope)[0])
        self.assertEqual((n["businesses"]["total"], n["jobs"]["total"], n["work_days_completed"],
                          n["disputes"]["total"], n["workers"]["total"]), (1, 1, 1, 1, 1))
        pages = self.pages(self.signed_in(profile))
        self.assertIn("مزرعة الخير", pages["businesses"][1])
        self.assertNotIn("مخبز السعادة", pages["businesses"][1])
        self.assertNotIn("مخبز السعادة", pages["activity"][1])

    def test_date_scope_clips_the_requested_period(self):
        profile = self.make_observer(ObserverLevel.AGGREGATE, start=datetime.date(2026, 12, 3))
        period, _ = metrics.period_for(profile.scope, "2026-11-01", "2026-12-24")
        self.assertEqual(period.start, datetime.date(2026, 12, 3))
        self.assertEqual(metrics.period_for(profile.scope)[0], metrics.Period(datetime.date(2026, 12, 3)))  # no picks too
        n = metrics.compute(metrics.Scope(profile.scope), metrics.period_for(profile.scope)[0])
        self.assertEqual(n["jobs"]["total"], 2)  # work dates 3 and 9 December
        client = self.signed_in(profile)
        body = client.get(reverse("observers:overview") + "?from=2026-11-01").content.decode()
        self.assertIn("2026-12-03", body)


class AccessTests(ObserverTestBase):
    def test_expired_observer_cannot_sign_in(self):
        profile = self.make_observer(expires=datetime.date(2026, 1, 1))
        r = self.client.post(reverse("observers:login"), {"email": profile.user.email, "password": PASSWORD})
        self.assertEqual(r.status_code, 401)

    def test_inactive_observer_cannot_sign_in_and_is_signed_out(self):
        profile = self.make_observer()
        client = self.signed_in(profile)
        User.objects.filter(pk=profile.user.pk).update(is_active=False)
        r = client.get(reverse("observers:overview"))
        self.assertRedirects(r, reverse("observers:login"), fetch_redirect_response=False)
        self.assertEqual(client.get(reverse("observers:activity")).status_code, 302)
        r = self.client.post(reverse("observers:login"), {"email": profile.user.email, "password": PASSWORD})
        self.assertEqual(r.status_code, 401)

    def test_expiry_during_a_session_signs_out(self):
        profile = self.make_observer()
        client = self.signed_in(profile)
        ObserverProfile.objects.filter(pk=profile.pk).update(expires_at=datetime.date(2026, 1, 1))
        self.assertEqual(client.get(reverse("observers:overview")).status_code, 302)

    def test_session_ends_after_4_hours(self):
        client = self.signed_in(self.make_observer())
        session = client.session
        session["observer_login_at"] = time.time() - 4 * 3600 - 1
        session.save()
        self.assertEqual(client.get(reverse("observers:overview")).status_code, 302)

    def test_dashboard_pages_carry_noindex(self):
        r = self.signed_in(self.make_observer()).get(reverse("observers:overview"))
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
        for name in ("overview", "businesses", "activity", "export"):
            for method in ("post", "put", "patch", "delete"):
                r = getattr(client, method)(reverse(f"observers:{name}"))
                self.assertEqual(r.status_code, 403, f"{method} {name}")


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
    def test_sign_in_and_every_page_view_is_audited(self):
        profile = self.make_observer(ObserverLevel.NAMED)
        client = self.signed_in(profile)
        self.pages(client)
        actions = list(AuditEvent.objects.filter(actor=profile.user).values_list("action", flat=True))
        self.assertIn("observer_login", actions)
        self.assertEqual(actions.count("observer_view"), 4)
        pages = set(AuditEvent.objects.filter(actor=profile.user, action="observer_view")
                    .values_list("details__page", flat=True))
        self.assertEqual(pages, {"overview", "businesses", "activity", "export"})

    def test_denied_views_are_audited(self):
        profile = self.make_observer(ObserverLevel.AGGREGATE)
        self.signed_in(profile).get(reverse("observers:activity"))
        self.assertTrue(AuditEvent.objects.filter(actor=profile.user, action="observer_view_denied").exists())

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
