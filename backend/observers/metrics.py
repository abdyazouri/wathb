"""Numbers for the observer dashboard: everything in the database, broken down by status.

No default date range: with no dates picked every record counts, including future work dates.
Dates are an optional filter, each kind of record by its own date:
- businesses and workers: the day they registered;
- jobs, offers and tasks, work days and wages: the job's work date;
- applications: the day applied; payment declarations and receipts: the day declared;
- disputes: the day opened.
The observer's own scope (businesses, dates) still limits what they see. Nothing here returns phone
numbers, IDs, wallets or dispute text.
"""
import datetime
import statistics
from dataclasses import dataclass

from django.conf import settings
from django.db.models import Count, Min, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from accounts.models import BusinessProfile, Role, User, VerificationStatus
from assignments.models import Assignment, AssignmentStatus, CompletionRecord, CompletionStatus
from audit.models import AuditEvent
from disputes.models import Dispute, DisputeStatus
from jobs.models import ApplicationStatus, JobApplication, JobListing, JobListingStatus
from wages.models import PaymentDeclaration, PaymentDeclarationStatus, WageObligation, WageObligationStatus

WORKER_ACK_ACTION = "payment_acknowledged"
RECEIPT_ACTIONS = ("payment_acknowledged", "payment_auto_acknowledged")

# Status lists (order shown on the dashboard and in the CSV).
BUSINESS_STATUSES = list(VerificationStatus.values)
JOB_STATUSES = list(JobListingStatus.values)
APPLICATION_STATUSES = list(ApplicationStatus.values)
TASK_STATUSES = list(AssignmentStatus.values)
WAGE_STATUSES = list(WageObligationStatus.values)
DISPUTE_STATUSES = list(DisputeStatus.values)


@dataclass(frozen=True)
class Period:
    """Inclusive Gaza dates; None on a side means no limit on that side."""
    start: datetime.date = None
    end: datetime.date = None

    @property
    def is_all(self):
        return self.start is None and self.end is None

    def q(self, field, is_date=False):
        """Q limiting a DateField (is_date) or DateTimeField (by its Gaza date) to the period."""
        lookup = field if is_date else f"{field}__date"
        q = Q()
        if self.start:
            q &= Q(**{f"{lookup}__gte": self.start})
        if self.end:
            q &= Q(**{f"{lookup}__lte": self.end})
        return q

    def contains(self, day):
        return (self.start is None or day >= self.start) and (self.end is None or day <= self.end)


def _parse(value):
    try:
        return datetime.date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


def trial_period():
    """TRIAL_START_DATE..TRIAL_END_DATE when both are set (a quick filter), else None."""
    start, end = _parse(settings.TRIAL_START_DATE), _parse(settings.TRIAL_END_DATE)
    return Period(start, end) if start and end and start <= end else None


def period_for(observer_scope, start=None, end=None):
    """(period, all_time). Nothing picked: no date limit at all. The scope's own dates still apply."""
    chosen_start, chosen_end = _parse(start), _parse(end)
    start, end = chosen_start, chosen_end
    if observer_scope.start_date:
        start = max(start, observer_scope.start_date) if start else observer_scope.start_date
    if observer_scope.end_date:
        end = min(end, observer_scope.end_date) if end else observer_scope.end_date
    if start and end and end < start:
        end = start
    return Period(start, end), not (chosen_start or chosen_end)


class Scope:
    """The businesses an observer scope covers (or one business inside it)."""

    def __init__(self, observer_scope, business_ids=None):
        self.all = observer_scope.all_businesses and business_ids is None
        allowed = None if observer_scope.all_businesses else set(observer_scope.businesses.values_list("pk", flat=True))
        if business_ids is None:
            self.ids = allowed or set()
        else:
            self.ids = set(business_ids) if allowed is None else set(business_ids) & allowed

    def q(self, path):
        """Q on «<path>business_id» (path like "assignment__job__")."""
        return Q() if self.all else Q(**{f"{path}business_id__in": self.ids})

    def businesses(self):
        qs = BusinessProfile.objects.all()
        return qs if self.all else qs.filter(pk__in=self.ids)

    def workers(self):
        qs = User.objects.filter(role=Role.WORKER)
        if self.all:
            return qs
        return qs.filter(Q(job_applications__job__business_id__in=self.ids)
                         | Q(assignments__job__business_id__in=self.ids)).distinct()


def _pct(part, whole):
    return round(100 * part / whole) if whole else None


def _local_date(dt):
    return timezone.localtime(dt).date()


def _by_status(qs, field, statuses):
    counts = dict(qs.order_by().values_list(field).annotate(n=Count("pk")).values_list(field, "n"))
    return {s: counts.get(s, 0) for s in statuses}


def compute(scope, period):
    """Totals and status breakdowns for one scope and period (Period() = everything)."""
    businesses = scope.businesses().filter(period.q("user__date_joined"))
    workers = scope.workers().filter(period.q("date_joined"))
    jobs = JobListing.objects.filter(scope.q(""), period.q("work_date", is_date=True))
    applications = JobApplication.objects.filter(scope.q("job__"), period.q("applied_at"))
    tasks = Assignment.objects.filter(scope.q("job__"), period.q("job__work_date", is_date=True))
    wages_qs = WageObligation.objects.filter(scope.q("assignment__job__"),
                                             period.q("assignment__job__work_date", is_date=True))
    declarations = PaymentDeclaration.objects.filter(scope.q("wage_obligation__assignment__job__"),
                                                     period.q("declared_at"))
    disputes = Dispute.objects.filter(scope.q("assignment__job__"), period.q("created_at"))

    # Businesses that posted jobs in two or more different weeks (by the day the job was posted).
    weeks_by_business = {}
    for business_id, posted in jobs.annotate(posted=Coalesce("published_at", "created_at")).values_list(
            "business_id", "posted"):
        weeks_by_business.setdefault(business_id, set()).add(_local_date(posted).isocalendar()[:2])

    # Payment percentages, on whatever wages have been declared.
    paid = list(wages_qs.annotate(first_declared=Min("declarations__declared_at"))
                .filter(first_declared__isnull=False).select_related("assignment__job"))
    acked = set(AuditEvent.objects.filter(action=WORKER_ACK_ACTION, model_name="WageObligation",
                                          object_id__in=[str(w.pk) for w in paid]).values_list("object_id", flat=True))
    completed_at = dict(CompletionRecord.objects.filter(assignment_id__in=[w.assignment_id for w in paid],
                                                        confirmed_at__isnull=False)
                        .values_list("assignment_id", "confirmed_at"))
    same_day = sum(1 for w in paid if _local_date(w.first_declared) == w.assignment.job.work_date)
    hours = [(w.first_declared - completed_at[w.assignment_id]).total_seconds() / 3600
             for w in paid if w.assignment_id in completed_at and w.first_declared >= completed_at[w.assignment_id]]

    return {
        "businesses": {"total": businesses.count(),
                       "by_status": _by_status(businesses, "verification_status", BUSINESS_STATUSES)},
        "workers": {"total": workers.count(), "verified": workers.filter(is_verified=True).count(),
                    "pending": workers.filter(is_verified=False).count()},
        "jobs": {"total": jobs.count(), "by_status": _by_status(jobs, "status", JOB_STATUSES),
                 "upcoming": jobs.filter(work_date__gt=timezone.localdate()).count()},
        "applications": {"total": applications.count(),
                         "by_status": _by_status(applications, "status", APPLICATION_STATUSES)},
        "tasks": {"total": tasks.count(), "by_status": _by_status(tasks, "status", TASK_STATUSES)},
        "wages": {"total": wages_qs.count(), "by_status": _by_status(wages_qs, "status", WAGE_STATUSES)},
        "disputes": {"total": disputes.count(), "by_status": _by_status(disputes, "status", DISPUTE_STATUSES)},
        "work_days_completed": CompletionRecord.objects.filter(
            scope.q("assignment__job__"), period.q("assignment__job__work_date", is_date=True),
            status=CompletionStatus.CONFIRMED).count(),
        "payments_declared": declarations.count(),
        "receipts_confirmed": declarations.filter(status=PaymentDeclarationStatus.ACKNOWLEDGED).count(),
        "businesses_posted_again": sum(1 for weeks in weeks_by_business.values() if len(weeks) >= 2),
        "wages_paid": len(paid),
        "paid_same_day_pct": _pct(same_day, len(paid)),
        "confirmed_by_workers_pct": _pct(len(acked), len(paid)),
        "median_hours_to_payment": round(statistics.median(hours), 1) if hours else None,
    }


# ── weekly series (chart and CSV) ───────────────────────────────────────────────

WEEKLY_FIELDS = ["jobs", "applications", "tasks", "work_days_completed", "wages", "payments_declared",
                 "receipts_confirmed", "disputes"]


def _weekly_counts(scope, period):
    """{monday: {field: count}} for every week that has a record (each record by its own date)."""
    series = {}

    def add(field, day):
        if day is None or not period.contains(day):
            return
        monday = day - datetime.timedelta(days=day.weekday())
        series.setdefault(monday, {f: 0 for f in WEEKLY_FIELDS})[field] += 1

    for d in JobListing.objects.filter(scope.q("")).values_list("work_date", flat=True):
        add("jobs", d)
    for dt in JobApplication.objects.filter(scope.q("job__")).values_list("applied_at", flat=True):
        add("applications", _local_date(dt))
    for d in Assignment.objects.filter(scope.q("job__")).values_list("job__work_date", flat=True):
        add("tasks", d)
    for d in CompletionRecord.objects.filter(scope.q("assignment__job__"), status=CompletionStatus.CONFIRMED) \
            .values_list("assignment__job__work_date", flat=True):
        add("work_days_completed", d)
    for d in WageObligation.objects.filter(scope.q("assignment__job__")).values_list("assignment__job__work_date", flat=True):
        add("wages", d)
    for dt, st in PaymentDeclaration.objects.filter(scope.q("wage_obligation__assignment__job__")) \
            .values_list("declared_at", "status"):
        add("payments_declared", _local_date(dt))
        if st == PaymentDeclarationStatus.ACKNOWLEDGED:
            add("receipts_confirmed", _local_date(dt))
    for dt in Dispute.objects.filter(scope.q("assignment__job__")).values_list("created_at", flat=True):
        add("disputes", _local_date(dt))
    return series


def weekly(scope, period):
    """Every week from the first to the last week with a record (or the chosen dates), empty weeks included."""
    series = _weekly_counts(scope, period)
    first = min(series) if series else None
    last = max(series) if series else None
    if period.start:
        first = period.start - datetime.timedelta(days=period.start.weekday())
    if period.end:
        last = period.end - datetime.timedelta(days=period.end.weekday())
    if first is None or last is None:
        return []
    rows, monday = [], first
    while monday <= last:
        start = max(monday, period.start) if period.start else monday
        end = monday + datetime.timedelta(days=6)
        end = min(end, period.end) if period.end else end
        rows.append({"start": start, "end": end, **series.get(monday, {f: 0 for f in WEEKLY_FIELDS})})
        monday += datetime.timedelta(days=7)
    return rows


# ── businesses page ─────────────────────────────────────────────────────────────

def business_rows(observer_scope, period):
    """Every business in scope, including those with no jobs yet."""
    rows = []
    for business in Scope(observer_scope).businesses().order_by("pk"):
        one = Scope(observer_scope, [business.pk])
        n = compute(one, period)
        open_disputes = Dispute.objects.filter(
            one.q("assignment__job__"), period.q("created_at"), status__in=[DisputeStatus.OPEN, DisputeStatus.IN_REVIEW]
        ).count()
        rows.append({"business": business, "status": business.verification_status,
                     "jobs": n["jobs"]["total"], "upcoming": n["jobs"]["upcoming"],
                     "work_days_completed": n["work_days_completed"], "paid_same_day_pct": n["paid_same_day_pct"],
                     "confirmed_by_workers_pct": n["confirmed_by_workers_pct"], "open_disputes": open_disputes})
    return rows


# ── activity page ───────────────────────────────────────────────────────────────

def activity(observer_scope, period):
    """Every event, newest first; a job posted for a future work date is listed with that date.
    Raw objects only; the view decides what each visibility level may show."""
    scope = Scope(observer_scope)
    events = []

    def add(at, kind, **data):
        if at and period.contains(_local_date(at)):
            events.append({"at": at, "type": kind, **data})

    for b in scope.businesses().select_related("user"):
        add(b.user.date_joined, "business_registered", business=b)
    for job in JobListing.objects.filter(scope.q("")).select_related("business"):
        add(job.published_at or job.created_at, "job_posted", business=job.business, job=job)
    for app in JobApplication.objects.filter(scope.q("job__")).select_related("job__business", "worker"):
        add(app.applied_at, "application_submitted", business=app.job.business, worker=app.worker, job=app.job)
    for a in Assignment.objects.filter(scope.q("job__")).select_related("job__business", "worker"):
        base = {"business": a.job.business, "worker": a.worker, "job": a.job}
        add(a.offered_at, "offer_made", **base)
        add(a.accepted_at, "offer_accepted", **base)
        if a.status == AssignmentStatus.CANCELLED:
            add(a.cancelled_at, "task_cancelled", **base)
    for c in CompletionRecord.objects.filter(scope.q("assignment__job__"), status=CompletionStatus.CONFIRMED) \
            .select_related("assignment__job__business", "assignment__worker"):
        add(c.confirmed_at, "work_completed", business=c.assignment.job.business, worker=c.assignment.worker,
            job=c.assignment.job)
    for d in PaymentDeclaration.objects.filter(scope.q("wage_obligation__assignment__job__")) \
            .select_related("wage_obligation__assignment__job__business", "wage_obligation__assignment__worker"):
        a = d.wage_obligation.assignment
        add(d.declared_at, "payment_declared", business=a.job.business, worker=a.worker, job=a.job,
            amount=d.declared_amount, currency=d.currency, reference=d.transaction_reference)
    wages = {str(w.pk): w for w in WageObligation.objects.filter(scope.q("assignment__job__"))
             .select_related("assignment__job__business", "assignment__worker")}
    for ev in AuditEvent.objects.filter(action__in=RECEIPT_ACTIONS, model_name="WageObligation", object_id__in=list(wages)):
        a = wages[ev.object_id].assignment
        add(ev.timestamp, "receipt_confirmed", business=a.job.business, worker=a.worker, job=a.job,
            automatic=ev.action != WORKER_ACK_ACTION)
    for d in Dispute.objects.filter(scope.q("assignment__job__")).select_related("assignment__job__business",
                                                                                 "assignment__worker"):
        base = {"business": d.assignment.job.business, "worker": d.assignment.worker, "job": d.assignment.job,
                "category": d.category}
        add(d.created_at, "dispute_opened", **base)
        add(d.resolved_at, "dispute_resolved", **base)
    events.sort(key=lambda ev: ev["at"], reverse=True)
    return events
