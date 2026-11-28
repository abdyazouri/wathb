"""Trial and activity numbers for the observer dashboard.

Every number respects the observer's scope (businesses and dates) and a period of Gaza calendar days.
By default the period is all time (first record to today); dates are an optional filter. Businesses
marked is_test, and everything linked to them, never count.
Definitions (approved by the product owner):
- active worker: has an accepted, active or completed task whose work day is in the period;
- active business: posted a job in the period, or has such a task;
- paid the same day: the first payment declaration falls on the task's work day (Gaza time);
- confirmed by workers: the worker acknowledged receipt (not auto-acknowledged);
- hours to payment: from the work completion confirmation to the first payment declaration (median);
- posted again: businesses with jobs posted in two or more different weeks of the period.
Nothing here returns phone numbers, IDs, wallets or dispute text.
"""
import datetime
import statistics
from dataclasses import dataclass

from django.conf import settings
from django.db.models import Min, Q
from django.utils import timezone

from accounts.models import BusinessProfile
from assignments.models import Assignment, AssignmentStatus, CompletionRecord, CompletionStatus
from audit.models import AuditEvent
from disputes.models import Dispute, DisputeStatus
from jobs.models import JobListing
from wages.models import PaymentDeclaration, WageObligation

WORKER_ACK_ACTION = "payment_acknowledged"
RECEIPT_ACTIONS = ("payment_acknowledged", "payment_auto_acknowledged")
WORKING_STATUSES = (AssignmentStatus.ACCEPTED, AssignmentStatus.ACTIVE, AssignmentStatus.COMPLETED)


@dataclass(frozen=True)
class Period:
    start: datetime.date
    end: datetime.date

    def weeks(self):
        """Monday-to-Sunday weeks covering the period, each clipped to it."""
        monday = self.start - datetime.timedelta(days=self.start.weekday())
        while monday <= self.end:
            yield Period(max(monday, self.start), min(monday + datetime.timedelta(days=6), self.end))
            monday += datetime.timedelta(days=7)


def _parse(value):
    try:
        return datetime.date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


def trial_period():
    """TRIAL_START_DATE..TRIAL_END_DATE when both are set (a quick filter), else None."""
    start, end = _parse(settings.TRIAL_START_DATE), _parse(settings.TRIAL_END_DATE)
    return Period(start, end) if start and end and start <= end else None


def first_record_date(observer_scope):
    """The first job posted within the scope (Gaza date), or today when there is none."""
    first = JobListing.objects.filter(Scope(observer_scope).q(""), published_at__isnull=False).aggregate(
        first=Min("published_at"))["first"]
    return _local_date(first) if first else timezone.localdate()


def period_for(observer_scope, start=None, end=None):
    """(period, all_time). No dates: all time, from the first record to today. Either date may be given
    alone. The scope's own dates always limit the result, whatever is asked."""
    chosen_start, chosen_end = _parse(start), _parse(end)
    start = chosen_start or first_record_date(observer_scope)
    end = chosen_end or timezone.localdate()
    if observer_scope.start_date:
        start = max(start, observer_scope.start_date)
    if observer_scope.end_date:
        end = min(end, observer_scope.end_date)
    if end < start:
        end = start
    return Period(start, end), not (chosen_start or chosen_end)


class Scope:
    """Business filter for one observer scope (or one business inside it)."""

    def __init__(self, observer_scope, business_ids=None):
        self.all = observer_scope.all_businesses and business_ids is None
        if business_ids is not None:
            allowed = None if observer_scope.all_businesses else set(observer_scope.businesses.values_list("pk", flat=True))
            ids = set(business_ids)
            self.ids = ids if allowed is None else ids & allowed
        else:
            self.ids = set(observer_scope.businesses.values_list("pk", flat=True))

    def q(self, path):
        """Q on «<path>business» (path like "assignment__job__"); test businesses are always left out."""
        real = Q(**{f"{path}business__is_test": False})
        return real if self.all else real & Q(**{f"{path}business_id__in": self.ids})

    def businesses(self):
        qs = BusinessProfile.objects.filter(is_test=False)
        return qs if self.all else qs.filter(pk__in=self.ids)


def _pct(part, whole):
    return round(100 * part / whole) if whole else None


def _local_date(dt):
    return timezone.localtime(dt).date()


def compute(scope, period):
    """All overview numbers for one scope and period."""
    s, e = period.start, period.end
    jobs = JobListing.objects.filter(scope.q(""), published_at__date__range=(s, e))
    tasks = Assignment.objects.filter(scope.q("job__"), status__in=WORKING_STATUSES, job__work_date__range=(s, e))

    business_ids = set(jobs.values_list("business_id", flat=True)) | set(tasks.values_list("job__business_id", flat=True))
    weeks_by_business = {}
    for business_id, published in jobs.values_list("business_id", "published_at"):
        weeks_by_business.setdefault(business_id, set()).add(_local_date(published).isocalendar()[:2])

    wages = list(
        WageObligation.objects.filter(scope.q("assignment__job__"))
        .annotate(first_declared=Min("declarations__declared_at"))
        .filter(first_declared__date__range=(s, e))
        .select_related("assignment__job")
    )
    wage_ids = [str(w.pk) for w in wages]
    worker_acked = set(
        AuditEvent.objects.filter(action=WORKER_ACK_ACTION, model_name="WageObligation", object_id__in=wage_ids)
        .values_list("object_id", flat=True)
    )
    completed_at = dict(
        CompletionRecord.objects.filter(assignment_id__in=[w.assignment_id for w in wages], confirmed_at__isnull=False)
        .values_list("assignment_id", "confirmed_at")
    )
    same_day = sum(1 for w in wages if _local_date(w.first_declared) == w.assignment.job.work_date)
    hours = [
        (w.first_declared - completed_at[w.assignment_id]).total_seconds() / 3600
        for w in wages if w.assignment_id in completed_at and w.first_declared >= completed_at[w.assignment_id]
    ]

    disputes = Dispute.objects.filter(scope.q("assignment__job__"))
    return {
        "businesses_active": len(business_ids),
        "workers_active": tasks.values("worker_id").distinct().count(),
        "jobs_posted": jobs.count(),
        "businesses_posted_again": sum(1 for weeks in weeks_by_business.values() if len(weeks) >= 2),
        "offers_accepted": Assignment.objects.filter(scope.q("job__"), accepted_at__date__range=(s, e)).count(),
        "work_days_completed": CompletionRecord.objects.filter(
            scope.q("assignment__job__"), status=CompletionStatus.CONFIRMED, confirmed_at__date__range=(s, e)
        ).count(),
        "wages_declared": len(wages),
        "paid_same_day": same_day,
        "paid_same_day_pct": _pct(same_day, len(wages)),
        "confirmed_by_workers": len(worker_acked),
        "confirmed_by_workers_pct": _pct(len(worker_acked), len(wages)),
        "median_hours_to_payment": round(statistics.median(hours), 1) if hours else None,
        "disputes_opened": disputes.filter(created_at__date__range=(s, e)).count(),
        "disputes_resolved": disputes.filter(resolved_at__date__range=(s, e)).count(),
    }


WEEKLY_FIELDS = [
    "jobs_posted", "offers_accepted", "work_days_completed", "wages_declared", "paid_same_day",
    "paid_same_day_pct", "confirmed_by_workers", "confirmed_by_workers_pct", "median_hours_to_payment",
    "businesses_active", "workers_active", "disputes_opened", "disputes_resolved",
]


def weekly(scope, period):
    return [{"start": w.start, "end": w.end, **compute(scope, w)} for w in period.weeks()]


def business_rows(observer_scope, period):
    """One row per business in scope with activity in the period."""
    scope = Scope(observer_scope)
    s, e = period.start, period.end
    active = set(
        JobListing.objects.filter(scope.q(""), published_at__date__range=(s, e)).values_list("business_id", flat=True)
    ) | set(
        Assignment.objects.filter(scope.q("job__"), job__work_date__range=(s, e)).values_list("job__business_id", flat=True)
    )
    rows = []
    for business in BusinessProfile.objects.filter(pk__in=active).order_by("pk"):
        numbers = compute(Scope(observer_scope, [business.pk]), period)
        open_disputes = Dispute.objects.filter(
            assignment__job__business=business, status__in=[DisputeStatus.OPEN, DisputeStatus.IN_REVIEW],
            created_at__date__range=(s, e),
        ).count()
        rows.append({"business": business, "open_disputes": open_disputes, **numbers})
    return rows


def activity(observer_scope, period, limit=300):
    """Newest events first. Raw objects only; the view decides what each level may show."""
    scope = Scope(observer_scope)
    s, e = period.start, period.end
    events = []
    for job in JobListing.objects.filter(scope.q(""), published_at__date__range=(s, e)).select_related("business"):
        events.append({"at": job.published_at, "type": "job_posted", "business": job.business, "job": job})
    for a in Assignment.objects.filter(scope.q("job__"), accepted_at__date__range=(s, e)).select_related("job__business", "worker"):
        events.append({"at": a.accepted_at, "type": "offer_accepted", "business": a.job.business, "worker": a.worker, "job": a.job})
    for c in CompletionRecord.objects.filter(
        scope.q("assignment__job__"), status=CompletionStatus.CONFIRMED, confirmed_at__date__range=(s, e)
    ).select_related("assignment__job__business", "assignment__worker"):
        events.append({"at": c.confirmed_at, "type": "work_completed", "business": c.assignment.job.business,
                       "worker": c.assignment.worker, "job": c.assignment.job})
    for d in PaymentDeclaration.objects.filter(
        scope.q("wage_obligation__assignment__job__"), declared_at__date__range=(s, e)
    ).select_related("wage_obligation__assignment__job__business", "wage_obligation__assignment__worker"):
        a = d.wage_obligation.assignment
        events.append({"at": d.declared_at, "type": "payment_declared", "business": a.job.business, "worker": a.worker,
                       "job": a.job, "amount": d.declared_amount, "currency": d.currency,
                       "reference": d.transaction_reference})
    wages = {
        str(w.pk): w for w in WageObligation.objects.filter(scope.q("assignment__job__"))
        .select_related("assignment__job__business", "assignment__worker")
    }
    for ev in AuditEvent.objects.filter(action__in=RECEIPT_ACTIONS, model_name="WageObligation",
                                        object_id__in=list(wages), timestamp__date__range=(s, e)):
        a = wages[ev.object_id].assignment
        events.append({"at": ev.timestamp, "type": "receipt_confirmed", "business": a.job.business, "worker": a.worker,
                       "job": a.job, "automatic": ev.action != WORKER_ACK_ACTION})
    for d in Dispute.objects.filter(scope.q("assignment__job__")).filter(
        Q(created_at__date__range=(s, e)) | Q(resolved_at__date__range=(s, e))
    ).select_related("assignment__job__business", "assignment__worker"):
        base = {"business": d.assignment.job.business, "worker": d.assignment.worker, "job": d.assignment.job,
                "category": d.category}
        if s <= _local_date(d.created_at) <= e:
            events.append({"at": d.created_at, "type": "dispute_opened", **base})
        if d.resolved_at and s <= _local_date(d.resolved_at) <= e:
            events.append({"at": d.resolved_at, "type": "dispute_resolved", **base})
    events.sort(key=lambda ev: ev["at"], reverse=True)
    return events[:limit]
