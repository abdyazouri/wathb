"""The observer dashboard: a summary of everything in the database plus simple lists, one filter bar.

Default: no dates, no search, no exclusions (test data counts; future work dates count).
The filter bar narrows the summary and every list:
- From / To, each kind of record by its own date: businesses and workers by the day they registered;
  jobs, tasks and wages by the job's work date; payment declarations by the day declared; disputes by
  the day opened;
- search: business name, worker name or job title (named level only, so it cannot reveal names).
The observer's own scope (businesses, dates) still limits everything. Never returned: phone numbers,
IDs, wallets, dispute text.
"""
import datetime
from dataclasses import dataclass

from django.db.models import Count, Q
from django.utils import timezone

from accounts.models import BusinessProfile, Role, User, VerificationStatus
from assignments.models import Assignment, AssignmentStatus
from disputes.models import Dispute, DisputeStatus
from jobs.models import JobListing, JobListingStatus
from wages.models import PaymentDeclaration, PaymentDeclarationStatus, WageObligation, WageObligationStatus

JOB_STATUSES = list(JobListingStatus.values)
TASK_STATUSES = list(AssignmentStatus.values)
WAGE_STATUSES = list(WageObligationStatus.values)
DISPUTE_STATUSES = list(DisputeStatus.values)


def _parse(value):
    try:
        return datetime.date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Filters:
    """What the filter bar asks for, already limited by the observer's scope dates."""
    start: datetime.date = None
    end: datetime.date = None
    q: str = ""

    def dates(self, field, is_date=False):
        lookup = field if is_date else f"{field}__date"
        cond = Q()
        if self.start:
            cond &= Q(**{f"{lookup}__gte": self.start})
        if self.end:
            cond &= Q(**{f"{lookup}__lte": self.end})
        return cond

    def text(self, *fields):
        """Q matching the search in any of the fields (empty search: everything)."""
        if not self.q:
            return Q()
        cond = Q()
        for f in fields:
            cond |= Q(**{f"{f}__icontains": self.q})
        return cond


def filters_for(observer_scope, start=None, end=None, q="", allow_search=True):
    start, end = _parse(start), _parse(end)
    if observer_scope.start_date:
        start = max(start, observer_scope.start_date) if start else observer_scope.start_date
    if observer_scope.end_date:
        end = min(end, observer_scope.end_date) if end else observer_scope.end_date
    if start and end and end < start:
        end = start
    return Filters(start, end, (q or "").strip()[:100] if allow_search else "")


# Search fields per record (business name, worker name, job title).
BUSINESS_TEXT = ("legal_name", "trade_name")
WORKER_TEXT = ("worker_profile__full_name",)
JOB_TEXT = ("title", "business__legal_name", "business__trade_name", "assignments__worker__worker_profile__full_name")
TASK_TEXT = ("job__title", "job__business__legal_name", "job__business__trade_name", "worker__worker_profile__full_name")


def _prefixed(prefix, fields):
    return tuple(prefix + f for f in fields)


class Records:
    """The querysets the dashboard shows, for one scope and one set of filters."""

    def __init__(self, observer_scope, f):
        self.f = f
        self.all = observer_scope.all_businesses
        self.ids = set() if self.all else set(observer_scope.businesses.values_list("pk", flat=True))

    def _scope(self, path):
        return Q() if self.all else Q(**{f"{path}business_id__in": self.ids})

    def businesses(self):
        scope = Q() if self.all else Q(pk__in=self.ids)
        return BusinessProfile.objects.filter(scope, self.f.dates("user__date_joined"), self.f.text(*BUSINESS_TEXT))

    def workers(self):
        qs = User.objects.filter(role=Role.WORKER)
        if not self.all:
            qs = qs.filter(Q(job_applications__job__business_id__in=self.ids)
                           | Q(assignments__job__business_id__in=self.ids))
        return qs.filter(self.f.dates("date_joined"), self.f.text(*WORKER_TEXT)).distinct()

    def jobs(self):
        return JobListing.objects.filter(self._scope(""), self.f.dates("work_date", is_date=True),
                                         self.f.text(*JOB_TEXT)).distinct()

    def tasks(self):
        return Assignment.objects.filter(self._scope("job__"), self.f.dates("job__work_date", is_date=True),
                                         self.f.text(*TASK_TEXT)).distinct()

    def wages(self):
        return WageObligation.objects.filter(self._scope("assignment__job__"),
                                             self.f.dates("assignment__job__work_date", is_date=True),
                                             self.f.text(*_prefixed("assignment__", TASK_TEXT))).distinct()

    def declarations(self):
        return PaymentDeclaration.objects.filter(self._scope("wage_obligation__assignment__job__"),
                                                 self.f.dates("declared_at"),
                                                 self.f.text(*_prefixed("wage_obligation__assignment__", TASK_TEXT))
                                                 ).distinct()

    def disputes(self):
        return Dispute.objects.filter(self._scope("assignment__job__"), self.f.dates("created_at"),
                                      self.f.text(*_prefixed("assignment__", TASK_TEXT))).distinct()


def _by_status(qs, field, statuses):
    counts = dict(qs.order_by().values(field).annotate(n=Count("pk", distinct=True)).values_list(field, "n"))
    return {s: counts.get(s, 0) for s in statuses}


def summary(records):
    """Plain totals by status (zeros included)."""
    businesses, workers, jobs = records.businesses(), records.workers(), records.jobs()
    tasks, wages, declarations, disputes = records.tasks(), records.wages(), records.declarations(), records.disputes()
    return {
        "businesses": {"total": businesses.count(),
                       "verified": businesses.filter(verification_status=VerificationStatus.APPROVED).count(),
                       "pending": businesses.filter(verification_status=VerificationStatus.PENDING).count()},
        "workers": {"total": workers.count(), "verified": workers.filter(is_verified=True).count(),
                    "pending": workers.filter(is_verified=False).count()},
        "jobs": {"total": jobs.count(), "by_status": _by_status(jobs, "status", JOB_STATUSES),
                 "upcoming": jobs.filter(work_date__gt=timezone.localdate()).count()},
        "tasks": {"total": tasks.count(), "by_status": _by_status(tasks, "status", TASK_STATUSES)},
        "wages": {"total": wages.count(), "by_status": _by_status(wages, "status", WAGE_STATUSES)},
        "payments_declared": declarations.count(),
        "receipts_confirmed": declarations.filter(status=PaymentDeclarationStatus.ACKNOWLEDGED).count(),
        "disputes": {"total": disputes.count(), "by_status": _by_status(disputes, "status", DISPUTE_STATUSES)},
    }
