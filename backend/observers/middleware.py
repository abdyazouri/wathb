import time

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from accounts.models import Role

PREFIX = "/observer/"
# The only observer requests that may POST: they change no Wathb data.
POST_ALLOWED = ("login/", "logout/", "set-password/")


class ObserverAccessMiddleware:
    """Server-side read-only rule for observers, on every request.

    - An expired or inactive observer, or a session older than OBSERVER_SESSION_SECONDS, is signed out.
    - Outside /observer/ (the API, Django admin, anything else) an observer gets 403.
    - Under /observer/ only GET/HEAD are allowed, except sign-in, sign-out and setting the password.
    - Every observer page carries X-Robots-Tag: noindex.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        on_dashboard = request.path.startswith(PREFIX)
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.role == Role.OBSERVER:
            profile = getattr(user, "observer_profile", None)
            started = request.session.get("observer_login_at", 0)
            if profile is None or not profile.is_usable or time.time() - started > settings.OBSERVER_SESSION_SECONDS:
                logout(request)
                if on_dashboard:
                    return redirect("observers:login")
                return HttpResponseForbidden("Observer access is read-only and limited to the dashboard.")
            if not on_dashboard:
                return HttpResponseForbidden("Observer access is read-only and limited to the dashboard.")
            rest = request.path[len(PREFIX):]
            if request.method not in ("GET", "HEAD") and not rest.startswith(POST_ALLOWED):
                return HttpResponseForbidden("Observer access is read-only.")

        response = self.get_response(request)
        if on_dashboard:
            response["X-Robots-Tag"] = "noindex, nofollow"
        return response
