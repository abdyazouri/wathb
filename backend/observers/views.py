import datetime
import time
from functools import wraps

from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.password_validation import (
    MinimumLengthValidator, get_default_password_validators, validate_password,
)
from django.core.exceptions import ValidationError
from django.db.models import Count, Min
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.http import require_POST

from accounts.models import Role, User
from audit.models import AuditEvent
from observers import audit, metrics
from observers.backends import ObserverEmailBackend
from observers.i18n import text
from observers.models import ObserverLevel, Pseudonym, PseudonymKind
from observers.tokens import observer_password_token

LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 5
PASSWORD_MIN_LENGTH = 12


# ── access ──────────────────────────────────────────────────────────────────────

def observer_page(page):
    """Signed-in, usable observers only; every view (with its filters) is written to the audit log."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not (user.is_authenticated and user.role == Role.OBSERVER):
                return redirect("observers:login")
            profile = user.observer_profile
            query = {k: v[:100] for k, v in request.GET.items() if k in ("from", "to", "q") and v}
            audit.log(request, "observer_view", page=page, level=profile.level, **query)
            return view(request, profile, *args, **kwargs)
        return wrapper
    return decorator


def _context(request, profile, page, **extra):
    t = text(profile.language)
    return {"t": t, "lang": profile.language, "dir": t["dir"], "profile": profile, "page": page,
            "level_label": t[f"level_{profile.level}"], **extra}


# ── sign-in ─────────────────────────────────────────────────────────────────────

def _recent_failures(email, ip):
    """Failed attempts in the last 15 minutes, counted from the audit log (shared by all workers)."""
    since = timezone.now() - datetime.timedelta(seconds=LOGIN_WINDOW_SECONDS)
    recent = AuditEvent.objects.filter(action="observer_login_failed", timestamp__gte=since)
    by_email = recent.filter(details__email=email).count() if email else 0
    by_ip = recent.filter(ip_address=ip).count() if ip else 0
    return max(by_email, by_ip)


def login_view(request):
    lang = request.GET.get("lang", "ar") if request.GET.get("lang") in ("ar", "en") else "ar"
    t = text(lang)
    ctx = {"t": t, "lang": lang, "dir": t["dir"], "error": None,
           "notice": t["password_set"] if request.GET.get("done") else None}
    if request.method != "POST":
        return render(request, "observers/login.html", ctx)

    email = request.POST.get("email", "").strip().lower()
    password = request.POST.get("password", "")
    ip = audit.client_ip(request)
    if _recent_failures(email, ip) >= LOGIN_MAX_FAILURES:
        audit.log(request, "observer_login_blocked", email=email)
        ctx["error"] = t["login_locked"]
        return render(request, "observers/login.html", ctx, status=429)

    user = ObserverEmailBackend().authenticate(request, email=email, password=password)
    profile = getattr(user, "observer_profile", None) if user else None
    if user is None or profile is None or not profile.is_usable:
        audit.log(request, "observer_login_failed", email=email)
        ctx["error"] = t["login_failed"]
        return render(request, "observers/login.html", ctx, status=401)

    login(request, user, backend="observers.backends.ObserverEmailBackend")
    request.session.set_expiry(settings.OBSERVER_SESSION_SECONDS)
    request.session["observer_login_at"] = time.time()
    audit.log(request, "observer_login", user=user)
    return redirect("observers:dashboard")


@require_POST
def logout_view(request):
    if request.user.is_authenticated and request.user.role == Role.OBSERVER:
        audit.log(request, "observer_logout")
    logout(request)
    return redirect("observers:login")


def set_password_view(request, uidb64, token):
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)), role=Role.OBSERVER)
    except (User.DoesNotExist, ValueError, TypeError, ValidationError):
        user = None
    lang = getattr(getattr(user, "observer_profile", None), "language", "ar")
    t = text(lang)
    ctx = {"t": t, "lang": lang, "dir": t["dir"], "errors": []}
    if user is None or not observer_password_token.check_token(user, token):
        ctx["invalid"] = True
        return render(request, "observers/set_password.html", ctx, status=400)
    if request.method != "POST":
        return render(request, "observers/set_password.html", ctx)

    password, password2 = request.POST.get("password", ""), request.POST.get("password2", "")
    if password != password2:
        ctx["errors"] = [t["passwords_differ"]]
        return render(request, "observers/set_password.html", ctx, status=400)
    try:
        validate_password(password, user, password_validators=[
            *get_default_password_validators(), MinimumLengthValidator(min_length=PASSWORD_MIN_LENGTH),
        ])
    except ValidationError as exc:
        ctx["errors"] = list(exc.messages)
        return render(request, "observers/set_password.html", ctx, status=400)
    user.set_password(password)  # also invalidates this link
    user.save(update_fields=["password"])
    audit.log(request, "observer_password_set", user=user)
    return redirect(f"{_login_url()}?done=1&lang={lang}")


def _login_url():
    from django.urls import reverse
    return reverse("observers:login")


# ── names by visibility level ───────────────────────────────────────────────────
# Named (the default) shows names; pseudonymised shows «عامل #12» / «منشأة #3» and no job titles;
# aggregate shows the summary only. Phone numbers, IDs and wallets are never shown.

def _business_label(profile, t, business):
    if profile.level == ObserverLevel.NAMED:
        return business.legal_name
    return f"{t['business_word']} #{Pseudonym.number_for(PseudonymKind.BUSINESS, business.pk)}"


def _worker_label(profile, t, worker):
    if worker is None:
        return "—"
    if profile.level == ObserverLevel.NAMED:
        try:
            return worker.worker_profile.full_name
        except Exception:
            return "—"
    return f"{t['worker_word']} #{Pseudonym.number_for(PseudonymKind.WORKER, worker.pk)}"


def _job_title(profile, job):
    return job.title if profile.level == ObserverLevel.NAMED else "—"


def _date(dt):
    return timezone.localtime(dt).date() if isinstance(dt, datetime.datetime) else dt


# ── the dashboard ───────────────────────────────────────────────────────────────

def _lists(profile, t, records):
    """Simple lists, newest first: businesses, workers, jobs, wages."""
    st = t["statuses"]
    businesses = [{
        "name": _business_label(profile, t, b), "status": st["business"].get(b.verification_status, b.verification_status),
        "registered": _date(b.user.date_joined), "jobs": b.n_jobs,
    } for b in records.businesses().select_related("user").annotate(n_jobs=Count("job_listings", distinct=True))
        .order_by("-user__date_joined")]
    workers = [{
        "name": _worker_label(profile, t, w), "status": t["verified"] if w.is_verified else t["pending"],
        "registered": _date(w.date_joined), "tasks": w.n_tasks,
    } for w in records.workers().select_related("worker_profile").annotate(n_tasks=Count("assignments", distinct=True))
        .order_by("-date_joined")]
    jobs = [{
        "title": _job_title(profile, j), "business": _business_label(profile, t, j.business),
        "status": st["job"].get(j.status, j.status), "work_date": j.work_date,
        "posted": _date(j.published_at or j.created_at),
    } for j in records.jobs().select_related("business").order_by("-work_date", "-created_at")]
    wages = [{
        "worker": _worker_label(profile, t, w.assignment.worker), "business": _business_label(profile, t, w.assignment.job.business),
        "job": _job_title(profile, w.assignment.job), "amount": f"{w.amount // 100} {'₪' if w.currency == 'ILS' else w.currency}",
        "status": st["wage"].get(w.status, w.status), "work_date": w.assignment.job.work_date,
        "declared": _date(w.first_declared) if w.first_declared else None,
    } for w in records.wages().select_related("assignment__job__business", "assignment__worker__worker_profile")
        .annotate(first_declared=Min("declarations__declared_at")).order_by("-assignment__job__work_date")]
    return {"businesses": businesses, "workers": workers, "jobs": jobs, "wages": wages}


def _summary_groups(t, n):
    st = t["statuses"]
    jobs = [(st["job"][s], c) for s, c in n["jobs"]["by_status"].items()] + [(t["upcoming"], n["jobs"]["upcoming"])]
    return [
        {"title": t["groups"]["businesses"], "total": n["businesses"]["total"],
         "rows": [(t["verified"], n["businesses"]["verified"]), (t["pending"], n["businesses"]["pending"])]},
        {"title": t["groups"]["workers"], "total": n["workers"]["total"],
         "rows": [(t["verified"], n["workers"]["verified"]), (t["pending"], n["workers"]["pending"])]},
        {"title": t["groups"]["jobs"], "total": n["jobs"]["total"], "rows": jobs},
        {"title": t["groups"]["tasks"], "total": n["tasks"]["total"],
         "rows": [(st["task"][s], c) for s, c in n["tasks"]["by_status"].items()]},
        {"title": t["groups"]["wages"], "total": n["wages"]["total"],
         "rows": [(st["wage"][s], c) for s, c in n["wages"]["by_status"].items()]
                 + [(t["payments_declared"], n["payments_declared"]), (t["receipts_confirmed"], n["receipts_confirmed"])]},
        {"title": t["groups"]["disputes"], "total": n["disputes"]["total"],
         "rows": [(st["dispute"][s], c) for s, c in n["disputes"]["by_status"].items()]},
    ]


@observer_page("dashboard")
def dashboard(request, profile):
    t = text(profile.language)
    can_search = profile.level == ObserverLevel.NAMED  # searching by name must not reveal names
    f = metrics.filters_for(profile.scope, request.GET.get("from"), request.GET.get("to"), request.GET.get("q"),
                            allow_search=can_search)
    records = metrics.Records(profile.scope, f)
    ctx = _context(request, profile, "dashboard", filters=f, can_search=can_search,
                   filtered=bool(f.start or f.end or f.q or request.GET.get("from") or request.GET.get("to")),
                   groups=_summary_groups(t, metrics.summary(records)))
    if profile.level != ObserverLevel.AGGREGATE:
        ctx["lists"] = _lists(profile, t, records)
    return render(request, "observers/dashboard.html", ctx)
