import csv
import datetime
import time
from functools import wraps

from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.password_validation import (
    MinimumLengthValidator, get_default_password_validators, validate_password,
)
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import urlencode, urlsafe_base64_decode
from django.views.decorators.http import require_POST

from accounts.models import Role, User
from audit.models import AuditEvent
from observers import audit, metrics
from observers.backends import ObserverEmailBackend
from observers.i18n import OVERVIEW_CARDS, PERCENT_KEYS, text
from observers.models import ObserverLevel, Pseudonym, PseudonymKind
from observers.tokens import observer_password_token

LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 5
PASSWORD_MIN_LENGTH = 12


# ── access ──────────────────────────────────────────────────────────────────────

def observer_page(page, records=False):
    """Signed-in, usable observers only; every view is written to the audit log.
    records=True: individual activity, not shown at the aggregate level."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not (user.is_authenticated and user.role == Role.OBSERVER):
                return redirect("observers:login")
            profile = user.observer_profile
            query = {k: v for k, v in request.GET.items() if k in ("from", "to")}
            if records and profile.level == ObserverLevel.AGGREGATE:
                audit.log(request, "observer_view_denied", page=page, level=profile.level)
                return render(request, "observers/not_available.html", _context(request, profile, page), status=403)
            audit.log(request, "observer_view", page=page, level=profile.level, **query)
            return view(request, profile, *args, **kwargs)
        return wrapper
    return decorator


def _context(request, profile, page, **extra):
    t = text(profile.language)
    return {"t": t, "lang": profile.language, "dir": t["dir"], "profile": profile, "page": page,
            "level_label": t[f"level_{profile.level}"], **extra}


def _period(request, profile):
    """(period, filter context). All time unless the observer picked dates."""
    chosen = {k: request.GET.get(k, "").strip() for k in ("from", "to")}
    period, all_time = metrics.period_for(profile.scope, chosen["from"], chosen["to"])
    today = timezone.localdate()
    trial = metrics.trial_period()
    query = urlencode({k: v for k, v in chosen.items() if v})
    return period, {
        "all_time": all_time,
        "chosen_from": chosen["from"], "chosen_to": chosen["to"],
        "query": f"?{query}" if query else "",
        "trial_query": f"?from={trial.start}&to={trial.end}" if trial else None,
        "last4_query": f"?from={today - datetime.timedelta(days=27)}&to={today}",
    }


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
    return redirect("observers:overview")


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


# ── labels by visibility level ──────────────────────────────────────────────────

def _business_label(profile, t, business):
    if profile.level == ObserverLevel.NAMED:
        return business.legal_name
    return f"{t['business_word']} #{Pseudonym.number_for(PseudonymKind.BUSINESS, business.pk)}"


def _worker_label(profile, t, worker):
    if worker is None:
        return ""
    if profile.level == ObserverLevel.NAMED:
        try:
            return worker.worker_profile.full_name
        except Exception:
            return "—"
    return f"{t['worker_word']} #{Pseudonym.number_for(PseudonymKind.WORKER, worker.pk)}"


def _fmt(key, value):
    if value is None:
        return "—"
    return f"{value}%" if key in PERCENT_KEYS else str(value)


# ── pages ───────────────────────────────────────────────────────────────────────

def _chart(weeks):
    """Bars per week: jobs by work date and payments declared (inline SVG, no scripts)."""
    peak = max([1] + [max(w["jobs"], w["payments_declared"]) for w in weeks])
    height, bar, gap = 120, 14, 18
    bars = []
    for i, w in enumerate(weeks):
        x = 30 + i * (2 * bar + gap)
        for j, key in enumerate(("jobs", "payments_declared")):
            h = round(height * w[key] / peak)
            bars.append({"x": x + j * bar, "y": 10 + height - h, "h": h, "value": w[key], "series": j})
        bars[-1]["label_x"] = x + bar
        bars[-1]["label"] = w["start"].strftime("%m/%d")
    return {"bars": bars, "width": max(260, 40 + len(weeks) * (2 * bar + gap)), "height": height + 40,
            "base_y": 10 + height}


STATUS_GROUPS = [("businesses", "business"), ("jobs", "job"), ("applications", "application"),
                 ("tasks", "task"), ("wages", "wage"), ("disputes", "dispute")]


def _groups(t, n):
    """The totals by status, as shown on the overview (zeros included)."""
    groups = []
    for key, kind in STATUS_GROUPS:
        rows = [(t["statuses"][kind][s], c) for s, c in n[key]["by_status"].items()]
        if key == "jobs":
            rows.append((t["totals"]["upcoming"], n["jobs"]["upcoming"]))
        groups.append({"title": t["groups"][key], "total": n[key]["total"], "rows": rows})
    groups.insert(1, {"title": t["groups"]["workers"], "total": n["workers"]["total"],
                      "rows": [(t["totals"]["verified"], n["workers"]["verified"]),
                               (t["totals"]["pending"], n["workers"]["pending"])]})
    return groups


@observer_page("overview")
def overview(request, profile):
    t = text(profile.language)
    period, filters = _period(request, profile)
    scope = metrics.Scope(profile.scope)
    numbers = metrics.compute(scope, period)
    cards = [{"label": t["metrics"][k], "value": _fmt(k, numbers[k])} for k in OVERVIEW_CARDS]
    return render(request, "observers/overview.html", _context(
        request, profile, "overview", period=period, groups=_groups(t, numbers), cards=cards,
        chart=_chart(metrics.weekly(scope, period)), **filters))


@observer_page("businesses", records=True)
def businesses(request, profile):
    t = text(profile.language)
    period, filters = _period(request, profile)
    rows = [{
        "name": _business_label(profile, t, r["business"]),
        "status": t["statuses"]["business"].get(r["status"], r["status"]),
        "jobs": r["jobs"], "upcoming": r["upcoming"], "days": r["work_days_completed"],
        "same_day": _fmt("paid_same_day_pct", r["paid_same_day_pct"]),
        "confirmed": _fmt("confirmed_by_workers_pct", r["confirmed_by_workers_pct"]),
        "open_disputes": r["open_disputes"],
    } for r in metrics.business_rows(profile.scope, period)]
    return render(request, "observers/businesses.html",
                  _context(request, profile, "businesses", period=period, rows=rows, **filters))


@observer_page("activity", records=True)
def activity(request, profile):
    t = text(profile.language)
    period, filters = _period(request, profile)
    named = profile.level == ObserverLevel.NAMED
    rows = []
    for ev in metrics.activity(profile.scope, period):
        details = []
        if named and ev.get("job"):
            details.append(ev["job"].title)  # free text written by the business: named level only
        if ev["type"] == "job_posted":
            details.append(f"{t['work_date']} {ev['job'].work_date}")
        if ev["type"] == "payment_declared":
            details.append(f"{ev['amount'] // 100} {'₪' if ev['currency'] == 'ILS' else ev['currency']}")
            ref = (ev.get("reference") or "").strip()
            if named and ref:
                details.append(f"{t['reference']} …{ref[-4:]}")
        if ev["type"] == "receipt_confirmed" and ev.get("automatic"):
            details.append(t["automatic"])
        if ev["type"].startswith("dispute_"):
            details.append(t["categories"].get(ev["category"], ev["category"]))  # never the dispute text
        rows.append({
            "when": timezone.localtime(ev["at"]).strftime("%Y-%m-%d %H:%M"),
            "event": t["events"][ev["type"]],
            "business": _business_label(profile, t, ev["business"]),
            "worker": _worker_label(profile, t, ev.get("worker")),
            "details": " · ".join(details),
        })
    return render(request, "observers/activity.html",
                  _context(request, profile, "activity", period=period, rows=rows, **filters))


@observer_page("export")
def export_csv(request, profile):
    """Aggregate numbers only (no individual records): one row per week, then the totals by status.
    Everything by default, the chosen dates otherwise (same rule as the pages)."""
    period, _ = _period(request, profile)
    scope = metrics.Scope(profile.scope)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="wathb_{period.start or "all"}_{period.end or "all"}.csv"'
    response.write("\ufeff")  # Excel opens UTF-8 correctly
    writer = csv.writer(response)
    writer.writerow(["week_start", "week_end", *metrics.WEEKLY_FIELDS])
    for w in metrics.weekly(scope, period):
        writer.writerow([w["start"], w["end"], *[w[f] for f in metrics.WEEKLY_FIELDS]])
    n = metrics.compute(scope, period)
    writer.writerow([])
    writer.writerow(["metric", "value"])
    writer.writerow(["period", f"{period.start or 'all'} to {period.end or 'all'}"])
    for key in ("businesses", "jobs", "applications", "tasks", "wages", "disputes"):
        writer.writerow([f"{key}_total", n[key]["total"]])
        for status_value, count in n[key]["by_status"].items():
            writer.writerow([f"{key}_{status_value.lower()}", count])
    writer.writerow(["jobs_upcoming", n["jobs"]["upcoming"]])
    for key in ("total", "verified", "pending"):
        writer.writerow([f"workers_{key}", n["workers"][key]])
    for key in ("work_days_completed", "payments_declared", "receipts_confirmed", "businesses_posted_again",
                "paid_same_day_pct", "confirmed_by_workers_pct", "median_hours_to_payment"):
        writer.writerow([key, _csv(n[key])])
    return response


def _csv(value):
    return "" if value is None else value
