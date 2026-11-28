from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.crypto import constant_time_compare
from django.utils.encoding import force_bytes
from django.utils.http import base36_to_int, urlsafe_base64_encode


class ObserverPasswordTokenGenerator(PasswordResetTokenGenerator):
    """One-time «set your password» link for a new observer.

    Valid for OBSERVER_LINK_TIMEOUT_SECONDS (48 hours), not the global PASSWORD_RESET_TIMEOUT,
    and dead as soon as the password is set (the password hash is part of the token).
    """

    key_salt = "observers.tokens.ObserverPasswordTokenGenerator"

    def check_token(self, user, token):
        if not (user and token):
            return False
        try:
            ts_b36, _ = token.split("-")
            ts = base36_to_int(ts_b36)
        except ValueError:
            return False
        for secret in [self.secret, *self.secret_fallbacks]:
            if constant_time_compare(self._make_token_with_timestamp(user, ts, secret), token):
                break
        else:
            return False
        return (self._num_seconds(self._now()) - ts) <= settings.OBSERVER_LINK_TIMEOUT_SECONDS


observer_password_token = ObserverPasswordTokenGenerator()


def set_password_link(user):
    """Absolute URL of the one-time link. Share it privately; it is never logged."""
    from django.urls import reverse

    uid = urlsafe_base64_encode(force_bytes(user.pk))
    path = reverse("observers:set-password", args=[uid, observer_password_token.make_token(user)])
    return settings.OBSERVER_BASE_URL.rstrip("/") + path
