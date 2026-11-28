"""Admin API for observers: ADMIN only, one-time link returned once, every action audited."""
import datetime

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import BusinessProfile, Role, User
from audit.models import AuditEvent
from observers.models import ObserverLevel, ObserverProfile
from observers.services import create_observer

URL = "/api/v1/admin/observers/"
PASSWORD = "Observer-Pass-2026!"
BODY = {"name": "T4P test", "organisation": "Tech for Palestine", "email": "t4p-test@example.org",
        "level": "pseudonymised", "language": "en", "expires_at": "2027-03-01"}


def client_for(user):
    c = APIClient()
    if user is not None:
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return c


class ObserverAdminApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user("+970599222001", "Admin-Pass-123", role=Role.ADMIN, is_verified=True)
        cls.worker = User.objects.create_user("+970599222002", "Wrk-Pass-123", role=Role.WORKER)
        biz_user = User.objects.create_user("+970599222003", "Biz-Pass-123", role=Role.BUSINESS)
        cls.business = BusinessProfile.objects.create(user=biz_user, legal_name="منشأة", contact_name="م",
                                                      contact_phone="0599222009", verification_status="APPROVED")

    def create(self, **extra):
        return client_for(self.admin).post(URL, {**BODY, **extra}, format="json")

    def test_admin_creates_an_observer_and_gets_the_link_once(self):
        r = self.create()
        self.assertEqual(r.status_code, 201, r.data)
        link = r.data["set_password_link"]
        self.assertIn("/observer/set-password/", link)
        profile = ObserverProfile.objects.get(user__email="t4p-test@example.org")
        self.assertEqual((profile.level, profile.language, profile.expires_at),
                         (ObserverLevel.PSEUDONYMISED, "en", datetime.date(2027, 3, 1)))
        self.assertTrue(profile.scope.all_businesses)
        self.assertEqual(profile.user.role, Role.OBSERVER)
        self.assertFalse(profile.user.has_usable_password())

        # Never again: the list carries no link, and the audit log never stores it.
        listing = client_for(self.admin).get(URL)
        self.assertEqual(listing.status_code, 200)
        self.assertNotIn("set-password", str(listing.data))
        event = AuditEvent.objects.get(action="observer_created", object_id=str(profile.pk))
        self.assertEqual(event.actor, self.admin)
        self.assertFalse(AuditEvent.objects.filter(details__icontains="set-password").exists())
        self.assertNotIn("set-password", str(list(AuditEvent.objects.values_list("details", flat=True))))

        # The link works once.
        path = link.split(".com", 1)[1]
        web = self.client_class()
        self.assertEqual(web.get(path).status_code, 200)
        self.assertEqual(web.post(path, {"password": PASSWORD, "password2": PASSWORD}).status_code, 302)
        self.assertEqual(web.get(path).status_code, 400)
        self.assertEqual(web.post("/observer/login/", {"email": "t4p-test@example.org",
                                                       "password": PASSWORD}).status_code, 302)

    def test_scope_with_chosen_businesses_and_dates(self):
        r = self.create(business_ids=[self.business.pk], start_date="2026-12-01", end_date="2026-12-24")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["observer"]["business_ids"], [self.business.pk])
        self.assertFalse(r.data["observer"]["all_businesses"])
        self.assertEqual(self.create(email="x@example.org", business_ids=[999999]).status_code, 400)
        self.assertEqual(self.create(email="y@example.org", start_date="2026-12-24",
                                     end_date="2026-12-01").status_code, 400)

    def test_duplicate_email_is_refused(self):
        self.assertEqual(self.create().status_code, 201)
        self.assertEqual(self.create().status_code, 409)

    def test_new_link_is_audited_without_the_link(self):
        profile, _ = create_observer(name="A", organisation="Wathb team", email="a@example.org",
                                     level=ObserverLevel.AGGREGATE, language="ar", expires_at=datetime.date(2027, 1, 1))
        r = client_for(self.admin).post(f"{URL}{profile.pk}/link/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("/observer/set-password/", r.data["set_password_link"])
        event = AuditEvent.objects.get(action="observer_link_issued", object_id=str(profile.pk))
        self.assertNotIn("set-password", str(event.details))

    def test_extend_deactivate_activate_and_change_level_are_audited(self):
        profile, _ = create_observer(name="A", organisation="Wathb team", email="b@example.org",
                                     level=ObserverLevel.AGGREGATE, language="ar", expires_at=datetime.date(2027, 1, 1))
        admin = client_for(self.admin)
        r = admin.patch(f"{URL}{profile.pk}/", {"expires_at": "2027-06-01", "level": "named"}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data["expires_at"], r.data["level"]), ("2027-06-01", "named"))
        self.assertFalse(admin.patch(f"{URL}{profile.pk}/", {"is_active": False}, format="json").data["is_active"])
        profile.user.refresh_from_db()
        self.assertFalse(profile.user.is_active)
        self.assertTrue(admin.patch(f"{URL}{profile.pk}/", {"is_active": True}, format="json").data["is_active"])
        updates = AuditEvent.objects.filter(action="observer_updated", object_id=str(profile.pk))
        self.assertEqual(updates.count(), 3)
        first = updates.order_by("timestamp").first().details["changes"]
        self.assertEqual(first["level"], ["aggregate", "named"])
        self.assertEqual(admin.patch(f"{URL}{profile.pk}/", {}, format="json").status_code, 400)
        self.assertEqual(admin.patch(f"{URL}999999/", {"level": "named"}, format="json").status_code, 404)

    def test_only_admins(self):
        profile, _ = create_observer(name="O", organisation="T4P", email="o@example.org",
                                     level=ObserverLevel.NAMED, language="en", expires_at=datetime.date(2027, 1, 1))
        for user in (self.worker, self.business.user, profile.user):
            c = client_for(user)
            self.assertEqual(c.get(URL).status_code, 403, user.role)
            self.assertEqual(c.post(URL, {**BODY, "email": "z@example.org"}, format="json").status_code, 403, user.role)
            self.assertEqual(c.patch(f"{URL}{profile.pk}/", {"level": "aggregate"}, format="json").status_code, 403)
            self.assertEqual(c.post(f"{URL}{profile.pk}/link/").status_code, 403, user.role)
        self.assertEqual(client_for(None).post(URL, BODY, format="json").status_code, 401)
        self.assertFalse(User.objects.filter(email="z@example.org").exists())
        profile.refresh_from_db()
        self.assertEqual(profile.level, ObserverLevel.NAMED)
