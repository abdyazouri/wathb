"""Creating and managing observer accounts (used by the admin screens and the management commands)."""
import uuid

from django.db import transaction

from accounts.models import Role, User
from observers.models import ObserverProfile, ObserverScope
from observers.tokens import set_password_link

OBSERVER_PHONE_PREFIX = "observer-"


def _placeholder_phone():
    # Not a phone number: never passes normalize_phone, so the mobile apps can never sign in with it.
    return OBSERVER_PHONE_PREFIX + uuid.uuid4().hex[:11]  # fits User.phone max_length=20


@transaction.atomic
def create_observer(*, name, organisation, email, level, language, expires_at, business_ids=None,
                    start_date=None, end_date=None, scope=None, created_by=None):
    """Returns (profile, one-time set-password link). No password is ever set or shown here."""
    email = email.strip().lower()
    if User.objects.filter(email__iexact=email).exists():
        raise ValueError(f"An account with {email} already exists.")
    user = User(phone=_placeholder_phone(), email=email, role=Role.OBSERVER, is_verified=False, is_staff=False)
    user.set_unusable_password()
    user.save()
    if scope is None:
        scope = ObserverScope.objects.create(
            name=f"{organisation} — {name}", all_businesses=not business_ids,
            start_date=start_date, end_date=end_date,
        )
        if business_ids:
            scope.businesses.set(business_ids)
    profile = ObserverProfile.objects.create(
        user=user, display_name=name, organisation=organisation, level=level, language=language,
        scope=scope, expires_at=expires_at, created_by=created_by,
    )
    return profile, set_password_link(user)
