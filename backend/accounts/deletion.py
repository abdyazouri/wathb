"""Self-service account deletion.

Wage, assignment and dispute records are kept: only what identifies the
person is removed, the login is disabled and every refresh token blacklisted.
AuditEvent rows are never touched (they are immutable by design).
"""
import uuid

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import Role, User

DELETED_DISPLAY_NAME = "مستخدم محذوف"
DELETED_PHONE_PREFIX = "deleted-"

BLOCKER_MESSAGES = {
    "active_assignments": "مهام لم تنتهِ بعد",
    "unsettled_wages": "أجور لم يُؤكَّد دفعها",
    "open_disputes": "نزاعات مفتوحة",
}


def deletion_blockers(user):
    """Codes for everything that must be closed before the account can go."""
    from assignments.models import Assignment, AssignmentStatus
    from disputes.models import Dispute, DisputeStatus
    from wages.models import WageObligation, WageObligationStatus

    party = Q(worker=user) | Q(job__business__user=user)
    blockers = []

    if Assignment.objects.filter(party).filter(
        status__in=[AssignmentStatus.OFFERED, AssignmentStatus.ACCEPTED, AssignmentStatus.ACTIVE]
    ).exists():
        blockers.append("active_assignments")

    if WageObligation.objects.filter(
        Q(assignment__worker=user) | Q(assignment__job__business__user=user)
    ).exclude(
        status__in=[WageObligationStatus.VERIFIED_PAID, WageObligationStatus.CANCELLED]
    ).exists():
        blockers.append("unsettled_wages")

    if Dispute.objects.filter(
        Q(raised_by=user) | Q(assigned_to=user)
        | Q(assignment__worker=user) | Q(assignment__job__business__user=user),
        status__in=[DisputeStatus.OPEN, DisputeStatus.IN_REVIEW],
    ).exists():
        blockers.append("open_disputes")

    return blockers


def blockers_detail(blockers):
    items = "، ".join(BLOCKER_MESSAGES[b] for b in blockers)
    return f"لا يمكن حذف الحساب قبل إغلاق: {items}."


def _placeholder_phone(user):
    # Fits phone max_length=20, never passes normalize_phone, so it can't be
    # used to log in or register, and frees the real number for re-use.
    candidate = DELETED_PHONE_PREFIX + user.pk.hex[:12]
    while User.objects.filter(phone=candidate).exclude(pk=user.pk).exists():
        candidate = DELETED_PHONE_PREFIX + uuid.uuid4().hex[:12]
    return candidate


def _close_open_job_activity(user):
    """Stop a deleted account from being offered work or receiving applicants."""
    from jobs.models import ApplicationStatus, JobApplication, JobListing, JobListingStatus

    if user.role == Role.WORKER:
        JobApplication.objects.filter(worker=user, status=ApplicationStatus.PENDING).update(
            status=ApplicationStatus.WITHDRAWN
        )
        # Free text the worker wrote about themselves.
        JobApplication.objects.filter(worker=user).exclude(cover_note="").update(cover_note="")

    elif user.role == Role.BUSINESS:
        from jobs.views import _notify_worker

        open_jobs = JobListing.objects.filter(
            business__user=user,
            status__in=[JobListingStatus.DRAFT, JobListingStatus.PENDING_REVIEW, JobListingStatus.PUBLISHED],
        )
        for job in open_jobs:
            pending = job.applications.filter(status=ApplicationStatus.PENDING)
            workers = [app.worker for app in pending.select_related("worker")]
            pending.update(status=ApplicationStatus.CANCELLED)
            job.status = JobListingStatus.CANCELLED
            job.cancellation_reason = "حُذف حساب المنشأة."
            job.save(update_fields=["status", "cancellation_reason"])
            for worker in workers:
                _notify_worker(worker, "JOB_CANCELLED", job)


def _anonymize(user):
    from notifications.models import Notification

    try:
        profile = user.worker_profile
    except User.worker_profile.RelatedObjectDoesNotExist:
        profile = None
    if profile is not None:
        profile.full_name = DELETED_DISPLAY_NAME
        profile.location_city = ""
        profile.location_region = ""
        profile.skills = ""
        profile.experience_summary = ""
        profile.national_id_hash = ""
        profile.is_available = False
        profile.save()

    try:
        business = user.business_profile
    except User.business_profile.RelatedObjectDoesNotExist:
        business = None
    if business is not None:
        # The commercial identity (legal_name, trade_name, registration_number,
        # city) stays on past jobs, wages and disputes. The owner's contact
        # details and the street address (often the owner's home) go.
        business.contact_name = ""
        business.contact_phone = ""
        business.location_address = ""
        business.save(update_fields=["contact_name", "contact_phone", "location_address"])

    Notification.objects.filter(recipient=user).delete()

    user.phone = _placeholder_phone(user)
    user.email = None
    user.set_unusable_password()
    user.is_active = False
    user.is_verified = False
    user.is_staff = False
    user.is_superuser = False
    user.deleted_at = timezone.now()
    user.save()


def _blacklist_refresh_tokens(user):
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)


def delete_account(user):
    """Returns blocker codes (nothing changed) or [] once the account is deleted."""
    from audit.models import AuditEvent

    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        blockers = deletion_blockers(user)
        if blockers:
            return blockers

        role = user.role
        _close_open_job_activity(user)
        _anonymize(user)
        _blacklist_refresh_tokens(user)
        AuditEvent.objects.create(
            actor=user,
            action="account_deleted",
            model_name="User",
            object_id=str(user.pk),
            details={"role": role},
        )
    return []
